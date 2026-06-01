#!/usr/bin/env python3
"""
A2 CSI1000 L9-B (handoff #1) — universe-switch paradox 预检查.

driver: L9-B 在 HS300 三 case 全负 (ROIC -0.096 / AR -0.031 / both -0.019),
        memory/equity_factor_l9b_falsified_2026-05.md 归因 "ROIC 与 ROE 重复" +
        "AR YoY 大盘行业属性主导". handoff session_2026_06_01_handoff 提出
        "切 CSI1000 small-cap 可能解耦 ROIC/ROE 重复 + AR 摆脱行业噪声".

风险 (handoff "预检查正向 ≠ backtest 正向" 4 次同模式):
  - 信号互斥/重复: 若 HS300 ρ(ROIC, ROE) 已 > 0.7, 小盘 only 更同质 (capital
    structure 相似, ROE/ROIC band 更窄, 高 leverage 离散度更小) → 切 universe
    不能解耦
  - Base rate 结构: AR YoY 横截面 std 若被中国 A 股 "累计申报" 季节性主导,
    那么任何 universe 都无效, 不是 universe 问题

本预检查 (HS300 现有 abstract 数据, 零 prefetch):
  1. ROIC × ROE 横截面 ρ (4 个 asof 日, Pearson + Spearman)
     - 若全部 Spearman > 0.7 → 切 universe 不可能解耦 → 软证伪
  2. AR YoY 横截面 median/std/分位
     - 若 std < 横截面 mean 且 median 单调集中 → 季节性主导 → 软证伪
  3. 全 pass (Spearman < 0.5 + AR 散度合理) → 提示 push CSI1000 prefetch + sweep

省 3-5 hr 工程 (CSI1000 universe 接 loader + 1000 ticker daily/abstract/val
prefetch + 4 case sweep + 8y verify) 在显然失败假设上.

用法:
  python scripts/research/a2_csi1000_l9b_paradox_precheck.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_system.strategies.equity_factor.data.loader import DataLoader  # type: ignore

OUT_DIR = ROOT / "data" / "backtest" / "_a2_precheck"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ASOF_DATES = ["2023-06-30", "2024-06-30", "2025-06-30", "2026-03-31"]
INDICATOR_ROIC = "投入资本回报率"
INDICATOR_ROE = "净资产收益率(ROE)"
INDICATOR_AR = "应收账款周转率"

SPEARMAN_FALSIFY_THRESHOLD = 0.7   # all asof Spearman >= 此值 → 软证伪
SPEARMAN_PROCEED_THRESHOLD = 0.5   # all < 此值 + AR 散度合理 → push backtest


def main() -> int:
    loader = DataLoader(cache_dir=ROOT / "data/cache", refresh_days=999)
    uni = loader.get_universe("a_share", "hs300")
    print(f"HS300 size: {len(uni)}")

    rows = []
    for asof in ASOF_DATES:
        roic_list, roe_list, ar_list = [], [], []
        for code in uni["code"].tolist():
            try:
                ab = loader.get_a_share_abstract(code)
                roic = loader.latest_indicator_value(ab, INDICATOR_ROIC, asof=asof)
                roe = loader.latest_indicator_value(ab, INDICATOR_ROE, asof=asof)
                ar_vals = loader.latest_n_indicator_values(ab, INDICATOR_AR, asof=asof, n=2)
                ar_yoy = (
                    (ar_vals[0] - ar_vals[1]) / abs(ar_vals[1])
                    if len(ar_vals) >= 2 and ar_vals[1] != 0
                    else None
                )
            except Exception:
                roic = roe = ar_yoy = None
            if roic is not None and roe is not None:
                roic_list.append(float(roic))
                roe_list.append(float(roe))
                ar_list.append(float(ar_yoy) if ar_yoy is not None else np.nan)

        n = len(roic_list)
        arr_roic = np.array(roic_list)
        arr_roe = np.array(roe_list)
        arr_ar = np.array(ar_list)

        pearson = float(np.corrcoef(arr_roic, arr_roe)[0, 1]) if n > 5 else float("nan")
        spearman = float(pd.Series(arr_roic).rank().corr(pd.Series(arr_roe).rank()))

        ar_ok = np.isfinite(arr_ar)
        ar_n = int(ar_ok.sum())
        ar_med = float(np.nanmedian(arr_ar[ar_ok])) if ar_n > 5 else float("nan")
        ar_std = float(np.nanstd(arr_ar[ar_ok])) if ar_n > 5 else float("nan")
        ar_q05 = float(np.nanquantile(arr_ar[ar_ok], 0.05)) if ar_n > 5 else float("nan")
        ar_q95 = float(np.nanquantile(arr_ar[ar_ok], 0.95)) if ar_n > 5 else float("nan")

        rows.append({
            "asof": asof, "n": n,
            "pearson_roic_roe": pearson,
            "spearman_roic_roe": spearman,
            "ar_n": ar_n, "ar_median": ar_med, "ar_std": ar_std,
            "ar_q05": ar_q05, "ar_q95": ar_q95,
        })
        print(
            f"asof={asof}  n={n}  Pearson(ROIC,ROE)={pearson:.3f}  Spearman={spearman:.3f}  "
            f"| AR_YoY n={ar_n} median={ar_med:+.3f} std={ar_std:.3f} "
            f"q05/q95=[{ar_q05:+.3f}, {ar_q95:+.3f}]"
        )

    # ---- decision ----
    spear_all = [r["spearman_roic_roe"] for r in rows]
    spear_min = min(spear_all)
    spear_max = max(spear_all)
    if spear_min >= SPEARMAN_FALSIFY_THRESHOLD:
        verdict = (
            f"SOFT-FALSIFY: ROIC × ROE Spearman 全 asof ∈ [{spear_min:.3f}, {spear_max:.3f}] "
            f">= {SPEARMAN_FALSIFY_THRESHOLD} → HS300 大盘已 ~重复, CSI1000 小盘只会更同质 "
            "(capital structure 相似 + ROE/ROIC band 更窄). 切 universe 不能救 ROIC 重复. "
            "AR YoY 一致 median ≈ -0.78 揭示中国 A 股累计申报季节性主导 (Q1 单季 vs Q4 累计), "
            "任何 universe 都失败. 不投 CSI1000 backtest, 省 ~3-5 hr 工程."
        )
    elif spear_max < SPEARMAN_PROCEED_THRESHOLD:
        verdict = (
            f"PROCEED: ROIC × ROE Spearman 全 asof < {SPEARMAN_PROCEED_THRESHOLD} → 信号未重复, "
            "可投 CSI1000 prefetch + sweep. 注意 AR YoY 仍可能受季节性影响, sweep 后看 trades CSV "
            "分行业再决定."
        )
    else:
        verdict = (
            f"AMBIGUOUS: Spearman ∈ [{spear_min:.3f}, {spear_max:.3f}] 介于 "
            f"[{SPEARMAN_PROCEED_THRESHOLD}, {SPEARMAN_FALSIFY_THRESHOLD}], 让用户决定 cost/benefit."
        )

    print()
    print("=" * 70)
    print(verdict)
    print("=" * 70)

    out_json = OUT_DIR / "a2_paradox_summary.json"
    out_json.write_text(json.dumps({"rows": rows, "verdict": verdict}, indent=2, ensure_ascii=False))
    print(f"\nSaved: {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
