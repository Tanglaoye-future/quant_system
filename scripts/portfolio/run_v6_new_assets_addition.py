#!/usr/bin/env python3
"""
v6 新资产加入测试 — v5 + 5/10% 新资产 (IBIT / TLT / CSI1000) 看组合 Sharpe 变化.

设计:
  对每个候选 X ∈ {IBIT, TLT, CSI1000}，固定 v5 权重比例缩放 + X 5%/10%:
    base v5: HK25/A_mom10/A_mr10/zhuang40/QQQ5/GLD10
    +5% X:   v5 各项 × 0.95 + X 5%
    +10% X:  v5 各项 × 0.90 + X 10%

  窗口受 X 上市日期限制:
    IBIT: 2024-01-11 → 2026-04-30 (2.5y, 短窗口)
    TLT/CSI1000: 与 v5 一致 2020-01-03 → 2026-04-30

  对照基准: 同窗口的 v5 静态 (公平比较，不跨窗口比 Sharpe).

输出: data/backtest/v6_new_assets_addition.md (+.json)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "portfolio"))
sys.path.insert(0, str(ROOT / "src"))

from run_p1_weight_grid_search import (  # type: ignore
    load_strategy_equity, load_passive_equity, metrics_from_returns,
)

TRADING_DAYS = 252

V5_WEIGHTS = {"HK_mom": 0.25, "A_mom": 0.10, "A_mr": 0.10, "zhuang": 0.40, "QQQ": 0.05, "GLD": 0.10}

PATHS = {
    "HK_mom":  ROOT / "data/backtest/equity_hk_momentum_hk_share_2018-01-01_2026-05-25/equity.csv",
    "A_mom":   ROOT / "data/backtest/equity_momentum_a_share_2018-01-01_2026-05-25/equity.csv",
    "A_mr":    ROOT / "data/backtest/mean_reversion_a_share_2018-01-01_2026-05-25/equity.csv",
    "zhuang":  ROOT / "data/backtest/zhuang_a_share_2018-01-01_2026-05-25/equity_curve.csv",
}

CANDIDATES = [
    # (ticker, source, window_start, window_end, desc)
    ("IBIT",   "yfinance",  "2024-01-11", "2026-04-30", "BTC 现货 ETF (BlackRock)"),
    ("TLT",    "yfinance",  "2020-01-02", "2026-04-30", "iShares 20+ Year Treasury"),
    ("510800", "akshare",   "2020-01-02", "2026-04-30", "中证 1000 ETF (A 股小盘)"),
]


def load_candidate(ticker: str, source: str, start: str, end: str) -> pd.Series:
    if source == "yfinance":
        return load_passive_equity(ticker, start, end)
    else:  # akshare A 股 ETF
        import akshare as ak
        df = ak.fund_etf_hist_em(symbol=ticker, period="daily",
                                 start_date=start.replace("-",""),
                                 end_date=end.replace("-",""),
                                 adjust="qfq")
        df = df.rename(columns={"日期":"date","收盘":"close"})[["date","close"]]
        df["date"] = pd.to_datetime(df["date"])
        close = pd.Series(df["close"].values, index=df["date"], dtype=float)
        eq = (close / close.iloc[0]) * 1_000_000
        eq.name = ticker
        return eq


def main():
    print("=== v6 new assets addition test ===\n")

    # 1. 加载 v5 6 资产
    print("[1/3] 加载 v5 6 资产 equity...")
    eq_map = {}
    for n, p in PATHS.items():
        eq_map[n] = load_strategy_equity(p, n)
    for tk in ["QQQ", "GLD"]:
        eq_map[tk] = load_passive_equity(tk, "2020-01-02", "2026-04-30")
    v5_df = pd.DataFrame({k: v for k, v in eq_map.items()})

    results = []

    # 2. 对每个候选跑 v5 baseline + v5 + 5% + v5 + 10% (同窗口对照)
    for ticker, source, w_start, w_end, desc in CANDIDATES:
        print(f"\n[2/3] 候选 {ticker} ({desc})...")
        try:
            cand = load_candidate(ticker, source, w_start, w_end)
            cand.name = ticker
        except Exception as e:
            print(f"  [FAIL] {ticker}: {str(e)[:80]}")
            continue

        # 7 资产对齐
        df = pd.concat({**{k: eq_map[k] for k in V5_WEIGHTS}, ticker: cand}, axis=1)
        df = df[(df.index >= w_start) & (df.index <= w_end)].dropna()
        if len(df) < 60:
            print(f"  对齐天数 {len(df)} 太少，跳过")
            continue
        rets = df.pct_change().dropna()
        asset_names = list(V5_WEIGHTS.keys()) + [ticker]
        print(f"  对齐 {len(rets)} 天 ({rets.index[0].date()} → {rets.index[-1].date()})")

        # base: 同窗口的 v5 静态
        w_base = np.array([V5_WEIGHTS[c] for c in V5_WEIGHTS])
        port_base = rets[list(V5_WEIGHTS.keys())].values @ w_base
        m_base = metrics_from_returns(port_base)
        print(f"  v5 同窗口 baseline: Sharpe {m_base['sharpe']:+.3f} / Ann {m_base['annual_return']*100:+.2f}% / DD {m_base['max_drawdown']*100:+.2f}%")

        for new_w in [0.05, 0.10]:
            # v5 各项缩放 (1 - new_w) + 新资产 new_w
            w_new = np.array([V5_WEIGHTS[c] * (1 - new_w) for c in V5_WEIGHTS] + [new_w])
            port_new = rets.values @ w_new
            m_new = metrics_from_returns(port_new)
            delta = m_new['sharpe'] - m_base['sharpe']
            flag = "✅" if delta > 0.02 else ("⚠️" if delta < -0.02 else " ")
            print(f"  +{int(new_w*100)}% {ticker:<8} Sharpe {m_new['sharpe']:+.3f} (Δ {delta:+.3f} {flag}) / "
                  f"Ann {m_new['annual_return']*100:+.2f}% / DD {m_new['max_drawdown']*100:+.2f}%")
            results.append({
                "candidate": ticker,
                "desc": desc,
                "window": [str(rets.index[0].date()), str(rets.index[-1].date())],
                "n_days": int(len(rets)),
                "v5_base_sharpe": m_base['sharpe'],
                "v5_base_ann": m_base['annual_return'],
                "v5_base_dd": m_base['max_drawdown'],
                "new_weight": new_w,
                "v6_sharpe": m_new['sharpe'],
                "v6_ann": m_new['annual_return'],
                "v6_dd": m_new['max_drawdown'],
                "delta_sharpe": delta,
            })

    # 3. 落产物
    print("\n[3/3] 写产物...")
    out_md = ROOT / "data/backtest/portfolio_v6_new_assets.md"
    lines = [
        "# v6 new assets addition test",
        "",
        "v5 6 资产 + 5%/10% 新资产 (同窗口公平对照).",
        "",
        "| 候选 | 窗口 | n_days | v5 base Sharpe | +5% Sharpe | Δ | +10% Sharpe | Δ |",
        "|---|---|---|---|---|---|---|---|",
    ]
    by_cand = {}
    for r in results:
        by_cand.setdefault(r["candidate"], []).append(r)
    for cand, rs in by_cand.items():
        if len(rs) < 2:
            continue
        r5, r10 = rs[0], rs[1]
        d5 = "✅" if r5["delta_sharpe"] > 0.02 else ("⚠️" if r5["delta_sharpe"] < -0.02 else "—")
        d10 = "✅" if r10["delta_sharpe"] > 0.02 else ("⚠️" if r10["delta_sharpe"] < -0.02 else "—")
        lines.append(f"| {cand} | {r5['window'][0]}~{r5['window'][1]} | {r5['n_days']} | "
                     f"{r5['v5_base_sharpe']:+.3f} | "
                     f"{r5['v6_sharpe']:+.3f} | {r5['delta_sharpe']:+.3f} {d5} | "
                     f"{r10['v6_sharpe']:+.3f} | {r10['delta_sharpe']:+.3f} {d10} |")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    out_json = out_md.with_suffix(".json")
    out_json.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    print(f"  [出口] {out_md}")
    print(f"  [出口] {out_json}")


if __name__ == "__main__":
    main()
