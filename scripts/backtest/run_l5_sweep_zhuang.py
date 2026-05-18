#!/usr/bin/env python3
"""
zhuang L5 仓位 sizing 实验.

基线: L4-combo4 (config.yaml 现行), 全部 single_position_pct_max=0.05 等权.
对照: 3 个 score 加权方案.

L5A-tiered_conservative: [75,80] -> [4%, 5%, 6%]   保守(范围窄)
L5B-tiered_aggressive  : [75,80] -> [3%, 5%, 8%]   激进(高分加倍)
L5C-linear             : score 70-85 → 4-6%         平滑

预测 hypothesis: score 区分能进一步提升 Sharpe 但增量小（L4 已榨干 entry filter alpha）.

用法:
  PYTHONUNBUFFERED=1 PYTHONPATH=src .venv/bin/python -u \\
      scripts/backtest/run_l5_sweep_zhuang.py \\
      --start 2022-01-01 --end 2024-12-31 \\
      --universe-file data/cache/universe_2026-05-16.csv
"""
from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path

import pandas as pd
import yaml

from quant_system.strategies.zhuang.data.loader import ZhuangDataLoader
from quant_system.strategies.zhuang.engine.backtest import ZhuangBacktester


EXPERIMENTS: list[tuple[str, dict]] = [
    ("L5-baseline-combo4", {}),  # 当前 config.yaml = combo4 + fixed sizing
    ("L5A-tiered-conservative", {
        "position_size_mode": "tiered",
        "tiered_score_thresholds": [75.0, 80.0],
        "tiered_position_pcts": [0.04, 0.05, 0.06],
    }),
    ("L5B-tiered-aggressive", {
        "position_size_mode": "tiered",
        "tiered_score_thresholds": [75.0, 80.0],
        "tiered_position_pcts": [0.03, 0.05, 0.08],
    }),
    ("L5C-linear", {
        "position_size_mode": "linear",
        "linear_score_min": 70.0,
        "linear_score_max": 85.0,
        "linear_position_min": 0.04,
        "linear_position_max": 0.06,
    }),
    ("L5D-linear-wider", {
        "position_size_mode": "linear",
        "linear_score_min": 70.0,
        "linear_score_max": 90.0,
        "linear_position_min": 0.03,
        "linear_position_max": 0.08,
    }),
]


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--universe-file", required=True)
    p.add_argument("--config", default="config/zhuang.yaml")
    p.add_argument("--refresh-days", type=int, default=9999)
    p.add_argument("--summary-out", default="data/backtest/zhuang_l5_summary.md")
    return p.parse_args()


def run_one(tag, base_config, override, loader, universe, px_cache, start, end):
    cfg = copy.deepcopy(base_config)
    cfg.setdefault("strategy", {}).update(override)
    bt = cfg.setdefault("backtest", {})
    out_base = Path(bt.get("output_dir", "./data/backtest"))
    bt["output_dir"] = str(out_base / f"_l5_{tag}")

    engine = ZhuangBacktester(cfg, loader)
    t0 = time.time()
    metrics = engine.run(start=start, end=end, universe=universe,
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
        f"elapsed={elapsed:.0f}s | {override}",
        flush=True,
    )
    return out


def main():
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    with open(root / args.config, "r", encoding="utf-8") as f:
        base_config = yaml.safe_load(f)

    df_u = pd.read_csv(root / args.universe_file, dtype={"code": str})
    universe = df_u["code"].str.zfill(6).tolist()
    print(f"[L5 sweep] universe={len(universe)} window={args.start}→{args.end}", flush=True)

    loader = ZhuangDataLoader(base_config, refresh_days=args.refresh_days)
    print("[L5 sweep] 预加载 px_cache...", flush=True)
    t_load = time.time()
    px_cache = {}
    for i, code in enumerate(universe, 1):
        df = loader.get_daily(code, args.start, args.end)
        if not df.empty:
            px_cache[code] = df
        if i % 500 == 0:
            print(f"  loaded {i}/{len(universe)}", flush=True)
    print(f"[L5 sweep] px_cache: {len(px_cache)} 只, elapsed={time.time()-t_load:.0f}s", flush=True)

    results = []
    for tag, override in EXPERIMENTS:
        results.append(run_one(tag, base_config, override, loader, universe,
                              px_cache, args.start, args.end))

    out_md = root / args.summary_out
    out_md.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# zhuang L5 仓位 sizing 实验",
        "",
        f"窗口: {args.start} → {args.end}  universe: {len(universe)} 只",
        "",
        "基线: L4-combo4 (config.yaml 现行) + fixed sizing 5%",
        "",
        "| 标签 | mode | Sharpe | 收益 | DD | 胜率 | PF | 笔数 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        mode = r["override"].get("position_size_mode", "fixed")
        lines.append(
            f"| {r['tag']} | {mode} | {r['sharpe']:.3f} | "
            f"{r['total_return']*100:+.1f}% | {r['max_drawdown']*100:.1f}% | "
            f"{r['win_rate']*100:.1f}% | {r['profit_factor']:.2f} | {r['total_trades']} |"
        )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    out_md.with_suffix(".json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\n[L5 sweep] summary → {out_md}", flush=True)


if __name__ == "__main__":
    main()
