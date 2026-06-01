#!/usr/bin/env python3
"""
A1' HK 南向资金 overlay 预检查.

driver: A1 北向 2024-08 起官方停更, akshare 无替代; pivot 到南向 (HK overlay).
       南向数据 12y 完整, 99.96% 非 NaN, 至今实盘可用.

hypothesis: HK 入场前 N 日南向累计净流入 > 0 是 quality 信号 — 资金面好时 HK
            momentum 入场 win rate / pnl 应显著高于资金面差时.

注意: 南向是市场日级总流入 (亿元), 不是个股级. 测的是 "regime overlay" 而非
      "stock-specific flow", 类似 HS300 MA200 regime filter.

方法: 从最新 HK equity_momentum 8y trades.csv 抽 winner / loser 各组,
     算入场前 5/10/20 日南向累计净流入分布. 看是否显著差异.

决策门:
  - winner 5d cum > 0 占比 比 loser >10pp → 推进完整 sweep
  - 差异 < 5pp → 软证伪
  - 5-10pp → AMBIGUOUS, 报告决定

用法:
  python scripts/research/hk_southbound_overlay_precheck.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_system.strategies.equity_factor.data.loader import DataLoader  # type: ignore

TRADES_PATH = ROOT / "data" / "backtest" / "equity_momentum_hk_share_2018-01-01_2026-05-25" / "trades.csv"
OUT_DIR = ROOT / "data" / "backtest" / "_a1prime_southbound_precheck"
OUT_DIR.mkdir(parents=True, exist_ok=True)

LOOKBACK_DAYS = [5, 10, 20]


def cumulative_southbound_before(sb_df: pd.DataFrame, entry_date: pd.Timestamp, lookback: int) -> float | None:
    """计算入场前 lookback 个 trading days 的南向累计净流入 (亿元)."""
    window = sb_df[(sb_df["date"] < entry_date) & (sb_df["date"] >= entry_date - pd.Timedelta(days=lookback * 2))]
    window = window.dropna(subset=["net_buy"]).tail(lookback)
    if len(window) < max(1, lookback // 2):  # 至少有 lookback/2 天数据
        return None
    return float(window["net_buy"].sum())


def main():
    trades = pd.read_csv(TRADES_PATH, dtype={"symbol": str})
    trades["entry_date"] = pd.to_datetime(trades["entry_date"])
    trades["winner"] = trades["pnl_pct"] > 0
    print(f"trades: {len(trades)}, winner: {trades['winner'].sum()}, loser: {(~trades['winner']).sum()}")
    print(f"win rate: {trades['winner'].mean() * 100:.1f}%")
    print(f"date range: {trades['entry_date'].min()} → {trades['entry_date'].max()}")
    print()

    loader = DataLoader(cache_dir=ROOT / "data" / "cache", refresh_days=30)
    sb_df = loader.get_hk_southbound_flow()
    sb_df["date"] = pd.to_datetime(sb_df["date"])
    sb_df = sb_df.sort_values("date").reset_index(drop=True)
    print(f"南向数据: {len(sb_df)} 行, range {sb_df['date'].min()} → {sb_df['date'].max()}")
    print(f"  non-NaN: {sb_df['net_buy'].notna().sum()} ({sb_df['net_buy'].notna().mean()*100:.1f}%)")
    print()

    # 对每笔 trade 算 lookback 累计
    for lb in LOOKBACK_DAYS:
        trades[f"sb_cum_{lb}d"] = trades["entry_date"].apply(
            lambda d: cumulative_southbound_before(sb_df, d, lb)
        )

    trades.to_csv(OUT_DIR / "trades_with_southbound.csv", index=False)
    print(f"[出口] {OUT_DIR / 'trades_with_southbound.csv'}")
    print()

    win = trades[trades["winner"]]
    lose = trades[~trades["winner"]]

    print("=" * 70)
    print("南向累计净流入分布 (winner vs loser)")
    print("=" * 70)
    print(f"{'lookback':<10} {'桶':<10} {'n':>5} {'cov%':>6} "
          f"{'mean (亿)':>10} {'median':>8} {'>0 占比':>9}")

    summary = {}
    for lb in LOOKBACK_DAYS:
        col = f"sb_cum_{lb}d"
        for label, df in [("winner", win), ("loser", lose)]:
            v = df[col].dropna()
            if len(v) == 0:
                print(f"{lb:<10}d {label:<10} 0 cov-NA")
                continue
            mean_v = v.mean()
            median_v = v.median()
            pos_ratio = (v > 0).mean() * 100
            cov = len(v) / len(df) * 100
            print(f"{lb:<10}d {label:<10} {len(v):>5} {cov:>5.1f}% "
                  f"{mean_v:>9.2f}  {median_v:>7.2f}  {pos_ratio:>7.1f}%")
            summary[f"{lb}d_{label}"] = {
                "n": int(len(v)), "coverage": round(cov, 1),
                "mean": round(float(mean_v), 2),
                "median": round(float(median_v), 2),
                "pos_pct": round(pos_ratio, 1),
            }

    # 决策
    print("\n" + "=" * 70)
    print("A1' 决策门")
    print("=" * 70)
    verdict_lines = []
    for lb in LOOKBACK_DAYS:
        w = summary.get(f"{lb}d_winner", {})
        l = summary.get(f"{lb}d_loser", {})
        if not w or not l:
            continue
        diff_pct = w["pos_pct"] - l["pos_pct"]
        diff_mean = w["mean"] - l["mean"]
        if diff_pct >= 10:
            v = f"PROCEED (Δ>0 ratio {diff_pct:+.1f}pp ≥ 10pp)"
        elif diff_pct >= 5:
            v = f"AMBIGUOUS (Δ {diff_pct:+.1f}pp 5-10pp)"
        else:
            v = f"ABORT (Δ {diff_pct:+.1f}pp < 5pp)"
        line = (f"  {lb:2d}d: winner >0 ratio {w['pos_pct']:.1f}% vs loser {l['pos_pct']:.1f}% "
                f"(Δ {diff_pct:+.1f}pp) | mean Δ {diff_mean:+.2f} 亿 → {v}")
        print(line)
        verdict_lines.append(line)
        summary[f"{lb}d_verdict"] = v

    # 汇总
    overall = max([summary.get(f"{lb}d_verdict", "ABORT") for lb in LOOKBACK_DAYS],
                  key=lambda v: 2 if "PROCEED" in v else 1 if "AMBIGUOUS" in v else 0)
    summary["overall_verdict"] = overall
    print(f"\n>>> 综合判断: {overall}")

    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\n[出口] {OUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
