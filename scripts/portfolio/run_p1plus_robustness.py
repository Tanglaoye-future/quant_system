#!/usr/bin/env python3
"""
P1+: 组合权重稳健性检验（落 v5 前的最后一道关）.

三块分析:
  (1) 固定权重 v4(当前) vs v5(候选) vs 等权 在 5 个市场段的 Sharpe/DD 对照
      —— 回答"v5 在 2022 熊市段是否不崩"
  (2) 各子区间各自 grid 最优权重 —— 看最优是否围绕 v5 中心漂移(过拟合风险)
  (3) 全窗口 cap sensitivity (0.40/0.50/0.60) —— zhuang 天花板

复用 run_p1_weight_grid_search 的 load + grid + metrics 函数。
A_mom 默认用 L9-A era 曲线。

输出: data/backtest/portfolio_p1plus_robustness.md + .json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_p1_weight_grid_search import (  # noqa: E402
    DEFAULT_PATHS, TRADING_DAYS, gen_weight_grid,
    load_passive_equity, load_strategy_equity, metrics_from_returns,
)

ROOT = Path(__file__).resolve().parents[2]

# 资产顺序固定
ASSET_ORDER = ["HK_mom", "A_mom", "A_mr", "zhuang", "QQQ", "GLD"]

WEIGHTS_V4 = {"HK_mom": 0.20, "A_mom": 0.20, "A_mr": 0.10,
              "zhuang": 0.20, "QQQ": 0.15, "GLD": 0.15}
WEIGHTS_V5 = {"HK_mom": 0.25, "A_mom": 0.10, "A_mr": 0.10,
              "zhuang": 0.40, "QQQ": 0.05, "GLD": 0.10}
WEIGHTS_EQ = {k: 1/6 for k in ASSET_ORDER}

# 市场段 (对齐窗口 2020-01-03 ~ 2026-04-29 内)
SUBWINDOWS = [
    ("2020 疫情冲击+反弹", "2020-01-03", "2020-12-31"),
    ("2021 结构牛/见顶",   "2021-01-01", "2021-12-31"),
    ("2022 熊市",          "2022-01-01", "2022-12-31"),
    ("2023-24 震荡",       "2023-01-01", "2024-12-31"),
    ("2025-26 反弹",       "2025-01-01", "2026-04-29"),
    ("全窗口",             "2020-01-03", "2026-04-29"),
]


def build_returns(window_start: str, window_end: str) -> tuple[pd.DataFrame, list[str]]:
    eq_map = {}
    for name in ["HK_mom", "A_mom", "A_mr", "zhuang"]:
        eq_map[name] = load_strategy_equity(DEFAULT_PATHS[name], name)
    for tk in ["QQQ", "GLD"]:
        eq_map[tk] = load_passive_equity(tk, "2019-12-01", "2026-05-15")
    df = pd.DataFrame(eq_map)
    df = df[(df.index >= window_start) & (df.index <= window_end)].dropna()
    rets = df.pct_change().dropna()
    rets = rets[ASSET_ORDER]
    return rets, ASSET_ORDER


def fixed_weight_metrics(rets: pd.DataFrame, weights: dict) -> dict:
    w = np.array([weights[c] for c in rets.columns])
    return metrics_from_returns(rets.values @ w)


def main():
    print("=== P1+ 稳健性检验 ===\n")

    # ---- (1) 固定权重在各市场段 ----
    print("[1] 固定权重 v4 / v5 / 等权 在各市场段:\n")
    hdr = f"{'市场段':<20} {'天数':>5}  {'v4 Sharpe/DD':>18}  {'v5 Sharpe/DD':>18}  {'等权 Sharpe/DD':>18}  {'v5-v4 ΔSharpe':>13}"
    print(hdr)
    print("-" * len(hdr))
    seg_rows = []
    for label, s, e in SUBWINDOWS:
        rets, _ = build_returns(s, e)
        m4 = fixed_weight_metrics(rets, WEIGHTS_V4)
        m5 = fixed_weight_metrics(rets, WEIGHTS_V5)
        meq = fixed_weight_metrics(rets, WEIGHTS_EQ)
        d = m5["sharpe"] - m4["sharpe"]
        seg_rows.append(dict(label=label, n=len(rets), v4=m4, v5=m5, eq=meq, delta=d))
        print(f"{label:<20} {len(rets):>5}  "
              f"{m4['sharpe']:>+7.3f} / {m4['max_drawdown']*100:>+6.2f}%  "
              f"{m5['sharpe']:>+7.3f} / {m5['max_drawdown']*100:>+6.2f}%  "
              f"{meq['sharpe']:>+7.3f} / {meq['max_drawdown']*100:>+6.2f}%  "
              f"{d:>+13.3f}")

    # ---- (2) 各子区间各自 grid 最优 ----
    print("\n[2] 各市场段各自 grid 最优权重 (step=0.05, cap=0.40) — 看漂移:\n")
    W = gen_weight_grid(len(ASSET_ORDER), 0.05, 0.40)
    opt_rows = []
    hdr2 = f"{'市场段':<20} {'最优Sharpe':>10}  权重 (HK/A_mom/A_mr/zhuang/QQQ/GLD)"
    print(hdr2)
    print("-" * (len(hdr2) + 10))
    for label, s, e in SUBWINDOWS:
        rets, names = build_returns(s, e)
        R = rets.values
        port = R @ W.T
        mu = port.mean(axis=0) * TRADING_DAYS
        sigma = port.std(axis=0) * np.sqrt(TRADING_DAYS)
        sharpe = np.where(sigma > 1e-12, mu / sigma, 0.0)
        best = int(np.argmax(sharpe))
        bw = W[best]
        opt_rows.append(dict(label=label, sharpe=float(sharpe[best]),
                             weights={names[i]: float(bw[i]) for i in range(len(names))}))
        wstr = " / ".join(f"{int(round(bw[i]*100))}" for i in range(len(names)))
        print(f"{label:<20} {sharpe[best]:>+10.3f}  {wstr}")

    # ---- (3) cap sensitivity 全窗口 ----
    print("\n[3] 全窗口 cap sensitivity — zhuang 天花板:\n")
    rets_full, names = build_returns("2020-01-03", "2026-04-29")
    R = rets_full.values
    cap_rows = []
    hdr3 = f"{'cap':>6} {'最优Sharpe':>10} {'净DD%':>8}  权重 (HK/A_mom/A_mr/zhuang/QQQ/GLD)"
    print(hdr3)
    print("-" * (len(hdr3) + 10))
    for cap in [0.40, 0.50, 0.60, 0.80]:
        Wc = gen_weight_grid(len(ASSET_ORDER), 0.05, cap)
        port = R @ Wc.T
        mu = port.mean(axis=0) * TRADING_DAYS
        sigma = port.std(axis=0) * np.sqrt(TRADING_DAYS)
        sharpe = np.where(sigma > 1e-12, mu / sigma, 0.0)
        cum = np.cumprod(1 + port, axis=0)
        dd = (cum / np.maximum.accumulate(cum, axis=0) - 1).min(axis=0)
        best = int(np.argmax(sharpe))
        bw = Wc[best]
        cap_rows.append(dict(cap=cap, sharpe=float(sharpe[best]), dd=float(dd[best]),
                             zhuang=float(bw[names.index("zhuang")]),
                             weights={names[i]: float(bw[i]) for i in range(len(names))}))
        wstr = " / ".join(f"{int(round(bw[i]*100))}" for i in range(len(names)))
        print(f"{cap:>6.0%} {sharpe[best]:>+10.3f} {dd[best]*100:>+7.2f}  {wstr}")

    # ---- 写产物 ----
    out_md = ROOT / "data/backtest/portfolio_p1plus_robustness.md"
    lines = [
        "# P1+ 组合权重稳健性检验",
        "",
        "A_mom = L9-A era。资产顺序 HK_mom / A_mom / A_mr / zhuang / QQQ / GLD。",
        "",
        "## v4 (当前) vs v5 (候选) 权重",
        "",
        "- v4: HK 20 / A_mom 20 / A_mr 10 / zhuang 20 / QQQ 15 / GLD 15",
        "- v5: HK 25 / A_mom 10 / A_mr 10 / zhuang 40 / QQQ 5 / GLD 10",
        "",
        "## [1] 固定权重在各市场段",
        "",
        "| 市场段 | 天数 | v4 Sharpe | v4 DD | v5 Sharpe | v5 DD | 等权 Sharpe | v5−v4 ΔSharpe |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in seg_rows:
        lines.append(
            f"| {r['label']} | {r['n']} | {r['v4']['sharpe']:+.3f} | "
            f"{r['v4']['max_drawdown']*100:+.2f}% | {r['v5']['sharpe']:+.3f} | "
            f"{r['v5']['max_drawdown']*100:+.2f}% | {r['eq']['sharpe']:+.3f} | "
            f"{r['delta']:+.3f} |")
    lines += ["", "## [2] 各市场段各自 grid 最优权重 (cap=0.40)", "",
              "| 市场段 | 最优Sharpe | HK | A_mom | A_mr | zhuang | QQQ | GLD |",
              "|---|---|---|---|---|---|---|---|"]
    for r in opt_rows:
        w = r["weights"]
        lines.append(
            f"| {r['label']} | {r['sharpe']:+.3f} | " +
            " | ".join(f"{int(round(w[k]*100))}%" for k in ASSET_ORDER) + " |")
    lines += ["", "## [3] cap sensitivity (全窗口)", "",
              "| cap | 最优Sharpe | DD | HK | A_mom | A_mr | zhuang | QQQ | GLD |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in cap_rows:
        w = r["weights"]
        lines.append(
            f"| {r['cap']:.0%} | {r['sharpe']:+.3f} | {r['dd']*100:+.2f}% | " +
            " | ".join(f"{int(round(w[k]*100))}%" for k in ASSET_ORDER) + " |")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    out_md.with_suffix(".json").write_text(json.dumps({
        "v4": WEIGHTS_V4, "v5": WEIGHTS_V5,
        "segments": [{"label": r["label"], "n": r["n"], "v4": r["v4"],
                      "v5": r["v5"], "eq": r["eq"]} for r in seg_rows],
        "per_window_optimal": opt_rows,
        "cap_sensitivity": cap_rows,
    }, indent=2, ensure_ascii=False, default=str))
    print(f"\n[出口] {out_md}")


if __name__ == "__main__":
    main()
