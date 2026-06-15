"""
反事实退出分析 — 对已有 backtest trades 重放不同退出规则.
秒级运行，不重跑 8 年全量回测。

用法: venv/bin/python scripts/research/counterfactual_exit.py
"""
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
    cfg_path = Path(__file__).resolve().parent.parent.parent / "config" / "zhuang.yaml"
    with open(cfg_path) as f:
        return yaml.safe_load(f)


def replay_exit(trade: pd.Series, daily_df: pd.DataFrame, exit_params: dict) -> dict | None:
    """
    重放一笔交易的退出逻辑，返回反事实 PnL。
    逐日检查退出信号，触发即止。未触发则持有到最后一天。
    """
    entry_date = str(trade["entry_date"])[:10]
    entry_price = float(trade["entry_price"])

    # 计算入场时 ATR
    mask_up_to_entry = daily_df["date"].astype(str).str[:10] <= entry_date
    df_up_to = daily_df[mask_up_to_entry]
    if len(df_up_to) < 15:
        return None
    tr_series = []
    for i in range(1, len(df_up_to)):
        h = float(df_up_to["high"].iloc[i])
        l = float(df_up_to["low"].iloc[i])
        pc = float(df_up_to["close"].iloc[i-1])
        tr = max(h - l, abs(h - pc), abs(l - pc))
        tr_series.append(tr)
    atr = sum(tr_series[-14:]) / 14 if len(tr_series) >= 14 else entry_price * 0.03

    # 截取入场后的行情
    mask = (daily_df["date"].astype(str).str[:10] >= entry_date)
    df_since = daily_df[mask].reset_index(drop=True)
    if df_since.empty:
        return None

    # 逐日检查
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
            hold_days = i
            pnl_pct = (exit_px - entry_price) / entry_price
            return {
                "code": str(trade["code"]),
                "entry_date": entry_date,
                "exit_date": str(sub["date"].iloc[-1])[:10],
                "entry_price": entry_price,
                "exit_price": exit_px,
                "pnl_pct": pnl_pct,
                "hold_days": hold_days,
                "exit_reason": sig.reason,
                "accumulation_score": float(trade.get("accumulation_score", 0)),
            }

    # 未触发任何退出 → 持有到最后
    last_close = float(df_since["close"].iloc[-1])
    pnl_pct = (last_close - entry_price) / entry_price
    return {
        "code": str(trade["code"]),
        "entry_date": entry_date,
        "exit_date": str(df_since["date"].iloc[-1])[:10],
        "entry_price": entry_price,
        "exit_price": last_close,
        "pnl_pct": pnl_pct,
        "hold_days": len(df_since) - 1,
        "exit_reason": "counterfactual_hold_to_end",
        "accumulation_score": float(trade.get("accumulation_score", 0)),
    }


def compute_metrics(trades: list[dict]) -> dict:
    pnls = [t["pnl_pct"] for t in trades]
    n = len(pnls)
    if n == 0:
        return {"sharpe": 0, "total_return": 0, "win_rate": 0, "n": 0}

    wins = sum(1 for p in pnls if p > 0)
    win_rate = wins / n
    total_return = sum(pnls)
    avg_pnl = total_return / n
    std_pnl = pd.Series(pnls).std()
    sharpe = avg_pnl / std_pnl if std_pnl > 0 else 0

    hold_days = [t["hold_days"] for t in trades]
    avg_hold = sum(hold_days) / n

    return {
        "sharpe": sharpe,
        "total_return": total_return,
        "win_rate": win_rate,
        "avg_pnl": avg_pnl,
        "n": n,
        "avg_hold_days": avg_hold,
    }


def main():
    config = load_config()
    strat = config.get("strategy", {})

    # 加载已有回测 trades
    trades_path = Path("data/backtest/zhuang_a_share_2018-01-01_2026-06-09/trades.csv")
    df_trades = pd.read_csv(trades_path)
    print(f"加载 {len(df_trades)} 笔交易")

    # 加载行情（复用 CSV 缓存）
    loader = ZhuangDataLoader(config, refresh_days=999, market="a_share")
    print("加载日线行情...")
    px_map: dict[str, pd.DataFrame] = {}
    for code in df_trades["code"].unique():
        df = loader.get_daily(str(code), "2018-01-01", "2026-06-09")
        if not df.empty:
            px_map[str(code)] = df

    # ── 变体定义 ────────────────────────────────────────────────────────
    base_exit = dict(
        stop_loss_atr_mult=float(strat.get("stop_loss_atr_mult", 1.5)),
        max_stop_loss_pct=float(strat.get("max_stop_loss_pct", 0.06)),
        min_stop_distance_pct=float(strat.get("min_stop_distance_pct", 0.0)),
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
        ("baseline", dict(base_exit)),
        ("A1: mom_stop 5%", {**base_exit, "momentum_stop_pct": 0.05}),
        ("A2: A1+dead_money(5d,2%)", {**base_exit, "momentum_stop_pct": 0.05, "dead_money_days": 5, "dead_money_pct": 0.02}),
        ("A3: A2+max_hold 7", {**base_exit, "momentum_stop_pct": 0.05, "dead_money_days": 5, "dead_money_pct": 0.02, "max_hold_days": 7}),
        ("A4: A3+atr 2.0", {**base_exit, "momentum_stop_pct": 0.05, "dead_money_days": 5, "dead_money_pct": 0.02, "max_hold_days": 7, "stop_loss_atr_mult": 2.0}),
        ("A5: A4+max_stop 8%", {**base_exit, "momentum_stop_pct": 0.05, "dead_money_days": 5, "dead_money_pct": 0.02, "max_hold_days": 7, "stop_loss_atr_mult": 2.0, "max_stop_loss_pct": 0.08}),
        ("A6: mom_stop 7%+dead_money(5d,2%)", {**base_exit, "momentum_stop_pct": 0.07, "dead_money_days": 5, "dead_money_pct": 0.02}),
        ("A7: dead_money(7d,1%)", {**base_exit, "momentum_stop_pct": 0.05, "dead_money_days": 7, "dead_money_pct": 0.01}),
        ("A8: mom 5%+dead(5d,2%)+max_hold 8", {**base_exit, "momentum_stop_pct": 0.05, "dead_money_days": 5, "dead_money_pct": 0.02, "max_hold_days": 8}),
    ]

    print(f"\n{'='*90}")
    print(f"  反事实退出分析 ({len(variants)} 变体 × {len(df_trades)} 笔交易)")
    print(f"{'='*90}\n")

    results = []
    for name, params in variants:
        cf_trades = []
        for _, trade in df_trades.iterrows():
            code = str(trade["code"])
            if code not in px_map:
                continue
            result = replay_exit(trade, px_map[code], params)
            if result:
                cf_trades.append(result)

        m = compute_metrics(cf_trades)
        # 按退出原因分类
        reasons = {}
        for t in cf_trades:
            reason_type = t["exit_reason"].split(":")[0]
            reasons[reason_type] = reasons.get(reason_type, 0) + 1

        results.append({"name": name, "metrics": m, "reasons": reasons})
        print(f"{name:<45s}  Sharpe={m['sharpe']:.4f}  Tot={m['total_return']*100:+6.1f}%  "
              f"WR={m['win_rate']*100:4.1f}%  avgPnL={m['avg_pnl']*100:+5.1f}%  "
              f"avgHold={m['avg_hold_days']:4.1f}d  N={m['n']}")

    # 汇总
    print(f"\n{'='*90}")
    print(f"{'Variant':<45s} {'Sharpe':>7s} {'TotRet%':>8s} {'WR%':>6s} {'avgPnL%':>8s} {'avgHold':>7s} {'N':>4s}")
    print("-" * 90)
    for r in results:
        m = r["metrics"]
        print(f"{r['name']:<45s} {m['sharpe']:7.4f} {m['total_return']*100:7.1f}% {m['win_rate']*100:5.1f}% {m['avg_pnl']*100:7.1f}% {m['avg_hold_days']:6.1f}d {m['n']:4d}")

    # 保存
    out_dir = Path("data/backtest")
    out_dir.mkdir(parents=True, exist_ok=True)
    save = []
    for r in results:
        save.append({"name": r["name"], "metrics": r["metrics"], "exit_reasons": r["reasons"]})
    with open(out_dir / "zhuang_counterfactual_exit.json", "w") as f:
        json.dump(save, f, indent=2)
    print(f"\nSaved to {out_dir / 'zhuang_counterfactual_exit.json'}")


if __name__ == "__main__":
    main()
