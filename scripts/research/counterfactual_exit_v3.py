"""反事实退出分析 v3 — stop_loss 放宽 + mom_stop 精调."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from quant_system.strategies.zhuang.data.loader import ZhuangDataLoader
from quant_system.strategies.zhuang.signals.exit import check_exit_signal


def load_config():
    import yaml
    with open(Path(__file__).resolve().parent.parent.parent / "config/zhuang.yaml") as f:
        return yaml.safe_load(f)


def compute_atr_at_entry(daily_df, entry_date, entry_price):
    mask = daily_df["date"].astype(str).str[:10] <= entry_date
    df_up_to = daily_df[mask]
    if len(df_up_to) < 15:
        return entry_price * 0.03
    tr_series = []
    for i in range(1, len(df_up_to)):
        h = float(df_up_to["high"].iloc[i])
        l = float(df_up_to["low"].iloc[i])
        pc = float(df_up_to["close"].iloc[i-1])
        tr_series.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(tr_series[-14:]) / 14 if len(tr_series) >= 14 else entry_price * 0.03


def replay_exit(trade, daily_df, exit_params):
    entry_date = str(trade["entry_date"])[:10]
    entry_price = float(trade["entry_price"])
    atr = compute_atr_at_entry(daily_df, entry_date, entry_price)

    mask = daily_df["date"].astype(str).str[:10] >= entry_date
    df_since = daily_df[mask].reset_index(drop=True)
    if df_since.empty:
        return None

    for i in range(len(df_since)):
        sub = df_since.iloc[:i+1]
        sig = check_exit_signal(
            code=str(trade["code"]),
            df_since_entry=sub,
            entry_price=entry_price,
            entry_date=entry_date,
            atr_at_entry=atr,
            **exit_params,
        )
        if sig.action == "EXIT":
            exit_px = float(sub["close"].iloc[-1])
            return {
                "pnl_pct": (exit_px - entry_price) / entry_price,
                "hold_days": i,
                "exit_reason": sig.reason.split(":")[0],
                "is_win": exit_px > entry_price,
            }

    last_close = float(df_since["close"].iloc[-1])
    return {
        "pnl_pct": (last_close - entry_price) / entry_price,
        "hold_days": len(df_since) - 1,
        "exit_reason": "hold_to_end",
        "is_win": last_close > entry_price,
    }


def compute_metrics(trades):
    pnls = [t["pnl_pct"] for t in trades]
    n = len(pnls)
    if n == 0:
        return {"sharpe": 0, "total_return": 0, "win_rate": 0, "n": 0, "avg_pnl": 0, "avg_hold": 0}
    wins = sum(1 for t in trades if t["is_win"])
    avg_pnl = sum(pnls) / n
    std_pnl = pd.Series(pnls).std()
    sharpe = avg_pnl / std_pnl if std_pnl > 0 else 0
    avg_hold = sum(t["hold_days"] for t in trades) / n
    return {
        "sharpe": sharpe,
        "total_return": sum(pnls),
        "win_rate": wins / n,
        "n": n,
        "avg_pnl": avg_pnl,
        "avg_hold": avg_hold,
    }


def main():
    config = load_config()
    strat = config.get("strategy", {})

    trades_path = Path("data/backtest/zhuang_a_share_2018-01-01_2026-06-09/trades.csv")
    df_trades = pd.read_csv(trades_path)
    print(f"{len(df_trades)} trades loaded")

    loader = ZhuangDataLoader(config, refresh_days=999, market="a_share")
    px_map = {}
    for code in df_trades["code"].unique():
        df = loader.get_daily(str(code), "2018-01-01", "2026-06-09")
        if not df.empty:
            px_map[str(code)] = df

    base = dict(
        stop_loss_atr_mult=float(strat.get("stop_loss_atr_mult", 1.5)),
        max_stop_loss_pct=float(strat.get("max_stop_loss_pct", 0.06)),
        min_stop_distance_pct=0.0,
        momentum_stop_pct=float(strat.get("momentum_stop_pct", 0.10)),
        dead_money_days=999,
        dead_money_pct=0.02,
        take_profit_pct=float(strat.get("take_profit_pct", 0.10)),
        max_hold_days=int(strat.get("max_hold_days", 10)),
        extend_hold_days=int(strat.get("extend_hold_days", 25)),
        extend_profit_pct=float(strat.get("extend_profit_pct", 0.05)),
        distribution_turnover_thresh=float(strat.get("distribution_turnover_thresh", 6.0)),
    )

    variants = [
        ("baseline", dict(base)),
        # Best from v2
        ("mom5%", {**base, "momentum_stop_pct": 0.05}),
        # Stop loss widening (with mom5%)
        ("S1: mom5%+atr2.0", {**base, "momentum_stop_pct": 0.05, "stop_loss_atr_mult": 2.0}),
        ("S2: mom5%+maxStop8%", {**base, "momentum_stop_pct": 0.05, "max_stop_loss_pct": 0.08}),
        ("S3: mom5%+atr2.0+maxStop8%", {**base, "momentum_stop_pct": 0.05, "stop_loss_atr_mult": 2.0, "max_stop_loss_pct": 0.08}),
        ("S4: mom5%+atr2.5+maxStop8%", {**base, "momentum_stop_pct": 0.05, "stop_loss_atr_mult": 2.5, "max_stop_loss_pct": 0.08}),
        ("S5: mom5%+atr2.0+maxStop10%", {**base, "momentum_stop_pct": 0.05, "stop_loss_atr_mult": 2.0, "max_stop_loss_pct": 0.10}),
        # Trade-off: wider stop but tighter mom
        ("S6: mom7%+atr2.0+maxStop8%", {**base, "momentum_stop_pct": 0.07, "stop_loss_atr_mult": 2.0, "max_stop_loss_pct": 0.08}),
        # Min stop distance for gap 0~0.5%
        ("S7: mom5%+minStopDist3%", {**base, "momentum_stop_pct": 0.05, "min_stop_distance_pct": 0.03}),
    ]

    results = []
    for name, params in variants:
        cf = []
        for _, trade in df_trades.iterrows():
            code = str(trade["code"])
            if code not in px_map:
                continue
            r = replay_exit(trade, px_map[code], params)
            if r:
                cf.append(r)
        m = compute_metrics(cf)
        results.append((name, m, cf))

    results.sort(key=lambda x: x[1]["sharpe"], reverse=True)

    print(f"\n{'='*100}")
    print(f"{'Variant':<45s} {'Sharpe':>7s} {'TotRet':>8s} {'WR%':>6s} {'avgPnL':>7s} {'avgHold':>7s} {'N':>4s}")
    print("-" * 100)
    for name, m, _ in results:
        print(f"{name:<45s} {m['sharpe']:7.4f} {m['total_return']*100:+7.1f}% {m['win_rate']*100:5.1f}% {m['avg_pnl']*100:+6.2f}% {m['avg_hold']:6.1f}d {m['n']:4d}")

    # Detail for top 5
    print(f"\n{'='*100}")
    print("Top 5 exit reason breakdown:")
    for name, m, cf in results[:5]:
        reasons = {}
        stop_avg = []
        for t in cf:
            r = t["exit_reason"]
            reasons[r] = reasons.get(r, 0) + 1
            if r == "stop_loss":
                stop_avg.append(t["pnl_pct"])
        print(f"\n  [{name}] Sharpe={m['sharpe']:.4f} Tot={m['total_return']*100:+.1f}%")
        for r, cnt in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    {r}: {cnt}")
        if stop_avg:
            print(f"    stop_loss avg PnL: {sum(stop_avg)/len(stop_avg)*100:+.2f}%")

    save = [{"name": n, "metrics": m} for n, m, _ in results]
    out = Path("data/backtest/zhuang_counterfactual_exit_v3.json")
    with open(out, "w") as f:
        json.dump(save, f, indent=2)
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
