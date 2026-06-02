#!/usr/bin/env python3
"""
C ensemble (handoff #2) — mom3m × mom6m 横截面 ρ paradox 预检查.

driver: session_2026_06_01_handoff C backlog. 当前 baseline mom3m 权重 0.20,
        mom6m 0.0. 假设: 拆 mom3m 0.10 + mom6m 0.10 ensemble 能加 alpha.

风险 (handoff "预检查正向 ≠ backtest 正向" + a2_csi1000 paradox 教训):
  - 构造重复: mom6m 含最后 60 天涨幅 = mom3m 的窗口的超集
    → 数学上必正相关, 关键是残差 (前 60 天) 是否独立 alpha
  - L8D2 baseline 单 mom3m 已是 efficient set ([[equity_factor_l9b_falsified_2026-05]])
  - mom3m ≡ mom6m (Spearman > 0.7) → 切 ensemble 只是稀释信号

本预检查 (HS300 现有 daily 缓存, 零 prefetch):
  1. ρ(mom3m, mom6m) 横截面 Spearman + Pearson, 4 个 asof
  2. 残差独立性: ρ(mom3m, mom6m - mom3m) — 残差 vs mom3m
  3. > 0.7 → 软证伪; < 0.5 + 残差有独立 rank → push backtest; 中间 → ask user

省 1-2 hr (4y sweep 2 case + 8y verify) 若必败.

用法:
  python scripts/research/c_ensemble_mom36_paradox_precheck.py
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

OUT_DIR = ROOT / "data" / "backtest" / "_c_precheck"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ASOF_DATES = ["2023-06-30", "2024-06-30", "2025-06-30", "2026-03-31"]

# factors.py:170-178 镜像
WINDOW_3M = 60
WINDOW_6M = 120

SPEARMAN_FALSIFY = 0.7   # all asof Spearman >= → 软证伪
SPEARMAN_PROCEED = 0.5   # all < + 残差有独立 rank → push backtest


def compute_mom(loader: DataLoader, code: str, asof: str) -> tuple[float | None, float | None]:
    """复制 factors.py:170-178 的 mom 计算口径."""
    try:
        end_dt = pd.to_datetime(asof)
        start_dt = max(end_dt - pd.Timedelta(days=250), pd.Timestamp("2018-01-01"))
        px = loader.get_daily("a_share", code, start_dt.strftime("%Y-%m-%d"), asof)
    except Exception:
        return None, None
    mom3 = mom6 = None
    if len(px) >= WINDOW_3M:
        mom3 = float(px["close"].iloc[-1] / px["close"].iloc[-WINDOW_3M] - 1.0)
    if len(px) >= WINDOW_6M:
        mom6 = float(px["close"].iloc[-1] / px["close"].iloc[-WINDOW_6M] - 1.0)
    return mom3, mom6


def main() -> int:
    loader = DataLoader(cache_dir=ROOT / "data/cache", refresh_days=999)
    uni = loader.get_universe("a_share", "hs300")
    print(f"HS300 size: {len(uni)}")

    rows = []
    for asof in ASOF_DATES:
        mom3_list, mom6_list = [], []
        for code in uni["code"].tolist():
            m3, m6 = compute_mom(loader, code, asof)
            if m3 is not None and m6 is not None:
                mom3_list.append(m3)
                mom6_list.append(m6)
        n = len(mom3_list)
        arr3 = np.array(mom3_list)
        arr6 = np.array(mom6_list)
        resid = arr6 - arr3   # 残差 ≈ 前 60 交易日涨幅 (近似)

        pearson = float(np.corrcoef(arr3, arr6)[0, 1]) if n > 5 else float("nan")
        spearman = float(pd.Series(arr3).rank().corr(pd.Series(arr6).rank()))
        resid_pearson = float(np.corrcoef(arr3, resid)[0, 1]) if n > 5 else float("nan")
        resid_spearman = float(pd.Series(arr3).rank().corr(pd.Series(resid).rank()))

        rows.append({
            "asof": asof, "n": n,
            "pearson_mom3_mom6": pearson,
            "spearman_mom3_mom6": spearman,
            "pearson_mom3_resid": resid_pearson,
            "spearman_mom3_resid": resid_spearman,
            "mom3_std": float(np.std(arr3)),
            "mom6_std": float(np.std(arr6)),
            "resid_std": float(np.std(resid)),
        })
        print(
            f"asof={asof}  n={n}  "
            f"Pearson(m3,m6)={pearson:.3f}  Spearman={spearman:.3f}  "
            f"| residual ρ(m3, m6-m3): Pearson={resid_pearson:+.3f} Spearman={resid_spearman:+.3f}  "
            f"| std m3={float(np.std(arr3)):.3f} m6={float(np.std(arr6)):.3f} resid={float(np.std(resid)):.3f}"
        )

    spear_all = [r["spearman_mom3_mom6"] for r in rows]
    spear_min = min(spear_all)
    spear_max = max(spear_all)
    resid_abs = [abs(r["spearman_mom3_resid"]) for r in rows]
    resid_max = max(resid_abs)

    if spear_min >= SPEARMAN_FALSIFY:
        verdict = (
            f"SOFT-FALSIFY: Spearman(mom3m, mom6m) 全 asof ∈ [{spear_min:.3f}, {spear_max:.3f}] "
            f">= {SPEARMAN_FALSIFY} → mom3m 与 mom6m 在 HS300 rank 几乎等价, "
            "ensemble 只是稀释信号. 不投 backtest. (与 A2 ROIC × ROE 同模式)"
        )
    elif spear_max < SPEARMAN_PROCEED and resid_max < 0.5:
        verdict = (
            f"PROCEED: Spearman 全 < {SPEARMAN_PROCEED} 且残差 rank-独立 "
            f"(max |resid Spearman| = {resid_max:.3f}) → 投 4y sweep "
            "(mom3m 0.10 + mom6m 0.10 vs mom3m 0.20 baseline)."
        )
    else:
        verdict = (
            f"AMBIGUOUS: Spearman ∈ [{spear_min:.3f}, {spear_max:.3f}], "
            f"残差 max |Spearman| = {resid_max:.3f}. "
            "ensemble 信号 partial 独立, 让用户决定是否值得 1-2 hr backtest."
        )

    print()
    print("=" * 70)
    print(verdict)
    print("=" * 70)

    out_json = OUT_DIR / "c_paradox_summary.json"
    out_json.write_text(json.dumps({"rows": rows, "verdict": verdict}, indent=2, ensure_ascii=False))
    print(f"\nSaved: {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
