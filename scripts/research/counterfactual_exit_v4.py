"""反事实退出分析 v4 — min_stop_distance + momentum_stop 联合精调."""
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
        # min_stop_distance_pct sweep (universal, with mom5%)
        ("msd=2%+mom5%", {**base, "momentum_stop_pct": 0.05, "min_stop_distance_pct": 0.02}),
        ("msd=3%+mom5%", {**base, "momentum_stop_pct": 0.05, "min_stop_distance_pct": 0.03}),
        ("msd=4%+mom5%", {**base, "momentum_stop_pct": 0.05, "min_stop_distance_pct": 0.04}),
        ("msd=5%+mom5%", {**base, "momentum_stop_pct": 0.05, "min_stop_distance_pct": 0.05}),
        # msd alone (no mom change)
        ("msd=3% (no mom change)", {**base, "min_stop_distance_pct": 0.03}),
        ("msd=3%+mom8%", {**base, "momentum_stop_pct": 0.08, "min_stop_distance_pct": 0.03}),
        ("msd=3%+mom7%", {**base, "momentum_stop_pct": 0.07, "min_stop_distance_pct": 0.03}),
        # msd + atr wider
        ("msd=3%+mom5%+atr1.8", {**base, "momentum_stop_pct": 0.05, "min_stop_distance_pct": 0.03, "stop_loss_atr_mult": 1.8}),
        ("msd=3%+mom5%+atr2.0", {**base, "momentum_stop_pct": 0.05, "min_stop_distance_pct": 0.03, "stop_loss_atr_mult": 2.0}),
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
    print(f"{'Variant':<40s} {'Sharpe':>7s} {'TotRet':>8s} {'WR%':>6s} {'avgPnL':>7s} {'avgHold':>7s} {'N':>4s}")
    print("-" * 100)
    for name, m, _ in results:
        print(f"{name:<40s} {m['sharpe']:7.4f} {m['total_return']*100:+7.1f}% {m['win_rate']*100:5.1f}% {m['avg_pnl']*100:+6.2f}% {m['avg_hold']:6.1f}d {m['n']:4d}")

    print(f"\n{'='*100}")
    print("Exit reason breakdown for top variants:")
    for name, m, cf in results[:5]:
        reasons = {}
        stop_pnls = []
        mom_pnls = []
        for t in cf:
            r = t["exit_reason"]
            reasons[r] = reasons.get(r, 0) + 1
            if r == "stop_loss":
                stop_pnls.append(t["pnl_pct"])
            if r == "momentum_stop":
                mom_pnls.append(t["pnl_pct"])
        print(f"\n  [{name}] Sharpe={m['sharpe']:.4f} Tot={m['total_return']*100:+.1f}% WR={m['win_rate']*100:.1f}%")
        for r, cnt in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    {r:20s}: {cnt:3d}", end="")
            if r == "stop_loss" and stop_pnls:
                print(f"  avg={sum(stop_pnls)/len(stop_pnls)*100:+.2f}%", end="")
            if r == "momentum_stop" and mom_pnls:
                print(f"  avg={sum(mom_pnls)/len(mom_pnls)*100:+.2f}%", end="")
            print()

    save = [{"name": n, "metrics": m} for n, m, _ in results]
    out = Path("data/backtest/zhuang_counterfactual_exit_v4.json")
    with open(out, "w") as f:
        json.dump(save, f, indent=2)
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
