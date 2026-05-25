#!/usr/bin/env python3
"""
zhuang L4 最优组合 6 年验证 (2020-2026).

跑 3 个实验:
  - baseline-L1E (对照)
  - L4-combo3 (mh=10 + tp=0.10 + atr=1.5 + dt=6.0)
  - L4-combo4 (combo3 + mom_stop=0.03)

6 年窗口 ~1500 交易日 (vs 3y 726)，约 2x 时间 = 每实验 ~38min。
共约 2h 完成。

用法:
  PYTHONUNBUFFERED=1 PYTHONPATH=src venv/bin/python -u \\
      scripts/backtest/run_l4_verify_6y.py
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import pandas as pd
import yaml

from quant_system.strategies.zhuang.data.loader import ZhuangDataLoader
from quant_system.strategies.zhuang.engine.backtest import ZhuangBacktester


START = "2020-01-01"
END = "2026-05-04"
UNIVERSE_FILE = "data/cache/universe_2026-05-16.csv"
CONFIG_PATH = "config/zhuang.yaml"
SUMMARY_OUT = "data/backtest/zhuang_l4_verify_6y_summary.md"

EXPERIMENTS: list[tuple[str, dict]] = [
    ("verify6y-baseline-L1E", {}),
    ("verify6y-L4-combo3", {
        "max_hold_days": 10,
        "take_profit_pct": 0.10,
        "stop_loss_atr_mult": 1.5,
        "distribution_turnover_thresh": 6.0,
    }),
    ("verify6y-L4-combo4", {
        "max_hold_days": 10,
        "take_profit_pct": 0.10,
        "stop_loss_atr_mult": 1.5,
        "distribution_turnover_thresh": 6.0,
        "momentum_stop_pct": 0.03,
    }),
]


def run_one(tag, base_config, override, loader, universe, px_cache):
    cfg = copy.deepcopy(base_config)
    cfg.setdefault("strategy", {}).update(override)
    bt = cfg.setdefault("backtest", {})
    out_base = Path(bt.get("output_dir", "./data/backtest"))
    bt["output_dir"] = str(out_base / f"_l4_{tag}")

    engine = ZhuangBacktester(cfg, loader)
    t0 = time.time()
    metrics = engine.run(start=START, end=END, universe=universe,
                         verbose=False, px_cache=px_cache)
    elapsed = time.time() - t0

    out = {
        "tag": tag,
        "override": override,
        "sharpe": float(metrics.get("sharpe_ratio", 0.0)),
        "total_return": float(metrics.get("total_return", 0.0)),
        "max_drawdown": float(metrics.get("max_drawdown", 0.0)),
        "win_rate": float(metrics.get("win_rate", 0.0)),
        "profit_factor": float(metrics.get("profit_factor", 0.0)),
        "total_trades": int(metrics.get("total_trades", 0)),
        "elapsed_s": round(elapsed, 1),
    }
    print(
        f"[{tag}] sharpe={out['sharpe']:.3f} ret={out['total_return']*100:+.1f}% "
        f"dd={out['max_drawdown']*100:.1f}% win={out['win_rate']*100:.1f}% "
        f"pf={out['profit_factor']:.2f} trades={out['total_trades']} "
        f"elapsed={elapsed:.0f}s | override={override}",
        flush=True,
    )
    return out


def main():
    root = Path(__file__).resolve().parents[2]
    with open(root / CONFIG_PATH, "r", encoding="utf-8") as f:
        base_config = yaml.safe_load(f)

    df_u = pd.read_csv(root / UNIVERSE_FILE, dtype={"code": str})
    universe = df_u["code"].str.zfill(6).tolist()
    print(f"[verify 6y] universe={len(universe)} window={START}→{END}", flush=True)

    loader = ZhuangDataLoader(base_config, refresh_days=9999)
    print("[verify 6y] 预加载 px_cache...", flush=True)
    t_load = time.time()
    px_cache = {}
    for i, code in enumerate(universe, 1):
        df = loader.get_daily(code, START, END)
        if not df.empty:
            px_cache[code] = df
        if i % 500 == 0:
            print(f"  loaded {i}/{len(universe)}", flush=True)
    print(f"[verify 6y] px_cache: {len(px_cache)} 只, elapsed={time.time()-t_load:.0f}s", flush=True)

    results = []
    for tag, override in EXPERIMENTS:
        results.append(run_one(tag, base_config, override, loader, universe, px_cache))

    out_md = root / SUMMARY_OUT
    out_md.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# zhuang L4 最优组合 6 年验证 (2020-2026)",
        "",
        f"窗口: {START} → {END}  universe: {len(universe)} 只",
        "",
        "对照: L1-E baseline；候选: combo3 / combo4",
        "",
        "| 标签 | 改动 | Sharpe | 收益 | DD | 胜率 | PF | 笔数 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        ov = ", ".join(f"{k}={v}" for k, v in r["override"].items()) or "—"
        lines.append(
            f"| {r['tag']} | {ov} | {r['sharpe']:.3f} | "
            f"{r['total_return']*100:+.1f}% | {r['max_drawdown']*100:.1f}% | "
            f"{r['win_rate']*100:.1f}% | {r['profit_factor']:.2f} | {r['total_trades']} |"
        )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    out_md.with_suffix(".json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\n[verify 6y] summary → {out_md}", flush=True)


if __name__ == "__main__":
    main()
