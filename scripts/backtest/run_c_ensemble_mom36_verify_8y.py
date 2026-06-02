#!/usr/bin/env python3
"""
C ensemble 8y verify — 4y winner = C-split (mom3m 0.10 + mom6m 0.10)
Sharpe 0.890 vs C-base 0.808 (Δ +0.082).

按 [[feedback_user_collab_style]] #3 "双窗口同向才落 yaml":
8y (2018-01-01 → 2026-05-04) 跑 C-base + C-split 两 case, Δ Sharpe 同向 (winner)
才落 yaml.

复用 run_c_ensemble_mom36_sweep.py 的 run_one. 仅改 START + EXPERIMENTS 子集.

用法:
  python scripts/backtest/run_c_ensemble_mom36_verify_8y.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "backtest"))

# 复用同模块的 run_one
import run_c_ensemble_mom36_sweep as sweep  # type: ignore

from quant_system.config import load_config

# Override 全局窗口为 8y
sweep.START = "2018-01-01"
sweep.END = "2026-05-04"

EXPERIMENTS_8Y = [
    ("C-base-8y", {}),
    ("C-split-8y", {"momentum_3m": 0.10, "momentum_6m": 0.10}),
]


def main():
    print(f"=== C ensemble 8y verify ({len(EXPERIMENTS_8Y)} cases) ===")
    print(f"  window: {sweep.START} → {sweep.END}")
    base_cfg = load_config()
    base_raw = base_cfg.raw
    results = []
    for tag, w_ov in EXPERIMENTS_8Y:
        try:
            results.append(sweep.run_one(tag, w_ov, base_raw, sweep.MARKET))
        except Exception as e:
            print(f"[{tag}] ERROR: {e}", file=sys.stderr, flush=True)
            import traceback; traceback.print_exc()

    out_json = ROOT / "data/backtest/equity_factor_c_ensemble_8y_verify.json"
    out_json.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\n[C 8y verify] → {out_json}", flush=True)


if __name__ == "__main__":
    main()
