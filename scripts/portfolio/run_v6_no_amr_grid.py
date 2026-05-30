#!/usr/bin/env python3
"""
v6 weight grid — PM 决策：A_mr 4y/8y solo Sharpe 都为负，承认结构性天花板，
把 v5 里 A_mr 10% 权重移到其他 5 资产，重新 grid search。

输入 5 资产（A_mr 直接 drop）：
  - HK_mom (cap 35%)
  - A_mom  (cap 25%)
  - zhuang (cap 40%, capacity 约束)
  - QQQ    (cap 25%)
  - GLD    (cap 25%)

输出：top Sharpe / DD-constrained top / cross-段稳健性（2020 / 2021 / 2022 熊 / 2023-24 / 2025-26）。

用法:
  python scripts/portfolio/run_v6_no_amr_grid.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "portfolio"))

from run_p1_weight_grid_search import (  # type: ignore
    load_strategy_equity, load_passive_equity, metrics_from_returns, gen_weight_grid,
)

TRADING_DAYS = 252
WINDOW_START = "2020-01-02"
WINDOW_END = "2026-04-30"
STEP = 0.05

# 5-asset 路径（A_mr 已删除）
PATHS = {
    "HK_mom":  ROOT / "data/backtest/equity_hk_momentum_hk_share_2018-01-01_2026-05-25/equity.csv",
    "A_mom":   ROOT / "data/backtest/equity_momentum_a_share_2018-01-01_2026-05-25/equity.csv",
    "zhuang":  ROOT / "data/backtest/zhuang_a_share_2018-01-01_2026-05-25/equity_curve.csv",
}

# 单资产 cap（capacity / 集中度约束）
ASSET_CAPS = {
    "HK_mom":  0.35,   # 流动性最好；从 v5 25% 抬高到 35% 让 grid 探
    "A_mom":   0.25,   # solo Sharpe 弱 (L9-A 8y 0.36)；不能给太多
    "zhuang":  0.40,   # capacity 约束 (≤30M AUM)，硬上限
    "QQQ":     0.25,   # 高 vol (25%)，cap 25% 防拖 Sharpe
    "GLD":     0.25,   # cap 25% 防独立大头
}

# v5 baseline (含 A_mr) 等价折算：把 A_mr 10% 平摊到 zhuang/HK
V5_BASELINE_IF_NO_AMR = {
    "HK_mom":  0.25, "A_mom": 0.10, "zhuang": 0.40, "QQQ": 0.05, "GLD": 0.10,
    # 注：这里 sum=0.90，A_mr 10% 是未分配（仅作 v5 直接展示）
}

# 跨段稳健性 — 与 [[portfolio_p1_p2]] P1+ 一致 5 个段
SEGMENTS = [
    ("2020 疫情",       "2020-01-02", "2020-12-31"),
    ("2021 牛/顶",      "2021-01-04", "2021-12-31"),
    ("2022 熊",         "2022-01-04", "2022-12-30"),
    ("2023-24 震荡",    "2023-01-03", "2024-12-31"),
    ("2025-26 反弹",    "2025-01-02", "2026-04-30"),
]


def gen_capped_grid(asset_names: list[str], caps: dict[str, float], step: float):
    """生成 sum=1, w_i ∈ [0, caps[asset]] 的所有权重组合."""
    units = int(round(1.0 / step))
    cap_units = [int(round(caps[a] / step)) for a in asset_names]
    n = len(asset_names)
    out = []
    def rec(remaining: int, depth: int, prefix: list[int]):
        if depth == n - 1:
            if 0 <= remaining <= cap_units[depth]:
                out.append(tuple(prefix + [remaining]))
            return
        # 剩余必须能被后面 (n-depth-1) 个资产吸收
        max_rest = sum(cap_units[depth+1:])
        lo = max(0, remaining - max_rest)
        hi = min(cap_units[depth], remaining)
        for u in range(lo, hi + 1):
            rec(remaining - u, depth + 1, prefix + [u])
    rec(units, 0, [])
    return np.array(out, dtype=np.float64) * step


def main():
    print(f"=== v6 grid search (A_mr → 0) ===")
    print(f"  window: {WINDOW_START} → {WINDOW_END}")
    print(f"  step:   {STEP}  caps: {ASSET_CAPS}")
    print()

    # 1. 加载 3 个 backtest + 2 个 passive
    print("[1/4] 加载 5 资产 equity curves...")
    eq_map: dict[str, pd.Series] = {}
    for name, path in PATHS.items():
        if not path.exists():
            print(f"  [FATAL] {name}: {path} 不存在", file=sys.stderr)
            sys.exit(2)
        eq_map[name] = load_strategy_equity(path, name)
        print(f"  {name:<10} {len(eq_map[name]):>5} 行  "
              f"{eq_map[name].index[0].date()} → {eq_map[name].index[-1].date()}")
    for tk in ["QQQ", "GLD"]:
        eq_map[tk] = load_passive_equity(tk, WINDOW_START, WINDOW_END)
        print(f"  {tk:<10} {len(eq_map[tk]):>5} 行  "
              f"{eq_map[tk].index[0].date()} → {eq_map[tk].index[-1].date()} (yfinance)")

    df = pd.DataFrame({k: v for k, v in eq_map.items()})
    df = df[(df.index >= WINDOW_START) & (df.index <= WINDOW_END)]
    df = df.dropna()
    rets_full = df.pct_change().dropna()
    asset_names = list(rets_full.columns)
    R = rets_full.values
    print(f"  对齐后 {len(rets_full)} 个交易日 ({rets_full.index[0].date()} → {rets_full.index[-1].date()})")

    # 2. solo metrics
    print("\n[2/4] 单资产 metrics (5y/2020-2026):")
    solo_rows = []
    for i, name in enumerate(asset_names):
        m = metrics_from_returns(R[:, i])
        solo_rows.append({"name": name, **m})
        print(f"  {name:<10} Sharpe={m['sharpe']:+.3f}  Ann={m['annual_return']*100:+.2f}%  "
              f"DD={m['max_drawdown']*100:+.2f}%  Vol={m['annual_vol']*100:.2f}%  "
              f"Tot={m['total_return']*100:+.1f}%")
    corr = rets_full.corr()
    print("\n相关性矩阵:")
    print(corr.round(3).to_string())

    # 3. 当前 v5 (90% 配资，A_mr 10% 空出) baseline
    print(f"\n[3/4] v5 (A_mr=0, 90% 配资) baseline:")
    w_v5 = np.array([V5_BASELINE_IF_NO_AMR.get(c, 0) for c in asset_names])
    # 归一化（剩余 10% 当作现金 0 回报，这是不公平 baseline；下面跑 grid 全配 100%）
    port_v5 = R @ w_v5
    m_v5 = metrics_from_returns(port_v5)
    print(f"  (90% 配, 10% 现金) Sharpe={m_v5['sharpe']:+.3f}  Ann={m_v5['annual_return']*100:+.2f}%  "
          f"DD={m_v5['max_drawdown']*100:+.2f}%")

    # 4. Grid search (full-window)
    print(f"\n[4/4] grid search (sum=100%)...")
    t0 = time.time()
    W = gen_capped_grid(asset_names, ASSET_CAPS, STEP)
    print(f"  组合数 {len(W):,}  生成 {time.time()-t0:.2f}s")
    port_returns = R @ W.T
    mu = port_returns.mean(axis=0) * TRADING_DAYS
    sigma = port_returns.std(axis=0) * np.sqrt(TRADING_DAYS)
    sharpe = np.where(sigma > 1e-12, mu / sigma, 0.0)
    cum = np.cumprod(1 + port_returns, axis=0)
    cummax = np.maximum.accumulate(cum, axis=0)
    dd = (cum / cummax - 1).min(axis=0)
    total = cum[-1] - 1

    results = pd.DataFrame({
        "sharpe": sharpe, "annual_return": mu, "annual_vol": sigma,
        "max_drawdown": dd, "total_return": total,
    })
    for i, name in enumerate(asset_names):
        results[name] = W[:, i]

    def fmt(row):
        return " / ".join(f"{n} {int(round(row[n]*100))}%" for n in asset_names)

    def show_top(df_sub, label, n=10):
        print(f"\n=== {label} (top {n}) ===")
        print(f"{'rank':<5} {'Sharpe':>8} {'Ann%':>7} {'DD%':>7} {'Vol%':>7} {'Tot%':>7}  权重")
        for k, (_, r) in enumerate(df_sub.head(n).iterrows(), 1):
            print(f"{k:<5} {r['sharpe']:+8.3f} {r['annual_return']*100:+7.2f} "
                  f"{r['max_drawdown']*100:+7.2f} {r['annual_vol']*100:7.2f} "
                  f"{r['total_return']*100:+7.1f}  {fmt(r)}")

    top_sharpe = results.sort_values("sharpe", ascending=False).head(20)
    top_dd7    = results[results.max_drawdown >= -0.07].sort_values("sharpe", ascending=False).head(20)
    top_dd10   = results[results.max_drawdown >= -0.10].sort_values("sharpe", ascending=False).head(20)
    top_ret    = results.sort_values("annual_return", ascending=False).head(20)
    min_dd     = results.sort_values("max_drawdown", ascending=False).head(20)

    show_top(top_sharpe, "Top by Sharpe")
    show_top(top_dd7, "Top by Sharpe @ DD>=-7%")
    show_top(top_dd10, "Top by Sharpe @ DD>=-10%")
    show_top(top_ret, "Top by Annual Return")
    show_top(min_dd, "Top by Min DrawDown")

    # 5. 跨段稳健性：用 #1 by Sharpe 的权重在 5 段验证
    print(f"\n=== 跨段稳健性 (Top1-Sharpe 权重在每段表现) ===")
    best = top_sharpe.iloc[0]
    w_best = np.array([best[n] for n in asset_names])
    print(f"权重: {fmt(best)}")
    print(f"全窗口: Sharpe {best['sharpe']:+.3f} / Ann {best['annual_return']*100:+.2f}% / DD {best['max_drawdown']*100:+.2f}%")
    seg_rows = []
    for label, s, e in SEGMENTS:
        seg = rets_full[(rets_full.index >= s) & (rets_full.index <= e)]
        if len(seg) < 30:
            continue
        port = seg.values @ w_best
        m = metrics_from_returns(port)
        seg_rows.append({"segment": label, "start": s, "end": e, **m})
        print(f"  {label:<14} {s} → {e}  Sharpe {m['sharpe']:+.3f}  Ann {m['annual_return']*100:+.2f}%  DD {m['max_drawdown']*100:+.2f}%")

    # 6. 落产物
    out_md = ROOT / "data/backtest/portfolio_v6_no_amr.md"
    out_json = out_md.with_suffix(".json")

    def df_to_md(df_sub, title, n=10):
        lines = [f"\n## {title}", "",
                 "| rank | Sharpe | Ann% | DD% | Vol% | Tot% | " + " | ".join(asset_names) + " |",
                 "|---|" + "|".join(["---"] * (5 + len(asset_names) + 1)) + "|"]
        for k, (_, r) in enumerate(df_sub.head(n).iterrows(), 1):
            ws = " | ".join(f"{int(round(r[n]*100))}%" for n in asset_names)
            lines.append(f"| {k} | {r['sharpe']:+.3f} | {r['annual_return']*100:+.2f} | "
                         f"{r['max_drawdown']*100:+.2f} | {r['annual_vol']*100:.2f} | "
                         f"{r['total_return']*100:+.1f} | {ws} |")
        return "\n".join(lines)

    lines = [
        "# v6 grid (A_mr → 0, 5 资产重 grid)",
        "",
        f"窗口: {rets_full.index[0].date()} → {rets_full.index[-1].date()} ({len(rets_full)} 天)  组合 {len(W):,}",
        f"caps: {ASSET_CAPS}",
        "",
        "## 单资产 metrics",
        "",
        "| 资产 | Sharpe | 年化 | DD | 年化波动 | 总收益 |",
        "|---|---|---|---|---|---|",
    ]
    for r in solo_rows:
        lines.append(f"| {r['name']} | {r['sharpe']:+.3f} | {r['annual_return']*100:+.2f}% | "
                     f"{r['max_drawdown']*100:+.2f}% | {r['annual_vol']*100:.2f}% | {r['total_return']*100:+.1f}% |")
    lines += [
        "",
        "## 相关性矩阵",
        "",
        "```",
        corr.round(3).to_string(),
        "```",
        "",
    ]
    lines.append(df_to_md(top_sharpe, "Top by Sharpe"))
    lines.append(df_to_md(top_dd7,    "Top by Sharpe @ DD>=-7%"))
    lines.append(df_to_md(top_dd10,   "Top by Sharpe @ DD>=-10%"))
    lines.append(df_to_md(top_ret,    "Top by Annual Return"))
    lines.append(df_to_md(min_dd,     "Top by Min DrawDown"))

    lines += ["", "## 跨段稳健性 (Top1-Sharpe 权重)", "",
              f"权重: **{fmt(best)}**",
              "",
              f"全窗口: Sharpe {best['sharpe']:+.3f} / Ann {best['annual_return']*100:+.2f}% / "
              f"DD {best['max_drawdown']*100:+.2f}%", "",
              "| 段 | 区间 | Sharpe | Ann% | DD% |",
              "|---|---|---|---|---|"]
    for r in seg_rows:
        lines.append(f"| {r['segment']} | {r['start']}~{r['end']} | {r['sharpe']:+.3f} | "
                     f"{r['annual_return']*100:+.2f} | {r['max_drawdown']*100:+.2f} |")
    out_md.write_text("\n".join(lines), encoding="utf-8")

    payload = {
        "window": [str(rets_full.index[0].date()), str(rets_full.index[-1].date())],
        "trading_days": int(len(rets_full)),
        "caps": ASSET_CAPS,
        "n_combos": int(len(W)),
        "asset_names": asset_names,
        "solo": solo_rows,
        "corr": corr.round(4).to_dict(),
        "top_sharpe": top_sharpe.head(20).to_dict(orient="records"),
        "top_sharpe_dd7": top_dd7.head(20).to_dict(orient="records"),
        "top_sharpe_dd10": top_dd10.head(20).to_dict(orient="records"),
        "top_annual_ret": top_ret.head(20).to_dict(orient="records"),
        "min_dd": min_dd.head(20).to_dict(orient="records"),
        "best_weights_seg_robustness": seg_rows,
        "best_weights": {n: float(best[n]) for n in asset_names},
    }
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    print(f"\n[出口] {out_md}")
    print(f"[出口] {out_json}")


if __name__ == "__main__":
    main()
