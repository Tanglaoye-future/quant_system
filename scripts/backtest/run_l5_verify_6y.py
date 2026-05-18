#!/usr/bin/env python3
"""
zhuang L5 最优 (tiered-aggressive) 6 年验证 (2020-2026).

baseline-combo4 + L5B 对照，6y 窗口确认非过拟合.
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


START, END = "2020-01-01", "2026-05-04"
UNIVERSE_FILE = "data/cache/universe_2026-05-16.csv"

EXPERIMENTS = [
    ("verify6y-L5-baseline-combo4", {}),
    ("verify6y-L5B-tiered-aggressive", {
        "position_size_mode": "tiered",
        "tiered_score_thresholds": [75.0, 80.0],
        "tiered_position_pcts": [0.03, 0.05, 0.08],
    }),
]


def run_one(tag, base_config, override, loader, universe, px_cache):
    cfg = copy.deepcopy(base_config)
    cfg.setdefault("strategy", {}).update(override)
    bt = cfg.setdefault("backtest", {})
    out_base = Path(bt.get("output_dir", "./data/backtest"))
    bt["output_dir"] = str(out_base / f"_l5_{tag}")

    engine = ZhuangBacktester(cfg, loader)
    t0 = time.time()
    m = engine.run(start=START, end=END, universe=universe,
                   verbose=False, px_cache=px_cache)
    elapsed = time.time() - t0
    out = {
        "tag": tag, "override": override,
        "sharpe": float(m.get("sharpe_ratio", 0.0)),
        "total_return": float(m.get("total_return", 0.0)),
        "max_drawdown": float(m.get("max_drawdown", 0.0)),
        "win_rate": float(m.get("win_rate", 0.0)),
        "profit_factor": float(m.get("profit_factor", 0.0)),
        "total_trades": int(m.get("total_trades", 0)),
        "elapsed_s": round(elapsed, 1),
    }
    print(
        f"[{tag}] sharpe={out['sharpe']:.3f} ret={out['total_return']*100:+.1f}% "
        f"dd={out['max_drawdown']*100:.1f}% win={out['win_rate']*100:.1f}% "
        f"pf={out['profit_factor']:.2f} trades={out['total_trades']} elapsed={elapsed:.0f}s",
        flush=True,
    )
    return out


def main():
    root = Path(__file__).resolve().parents[2]
    with open(root / "config/zhuang.yaml") as f:
        base_config = yaml.safe_load(f)
    df_u = pd.read_csv(root / UNIVERSE_FILE, dtype={"code": str})
    universe = df_u["code"].str.zfill(6).tolist()
    print(f"[verify L5 6y] universe={len(universe)} window={START}→{END}", flush=True)

    loader = ZhuangDataLoader(base_config, refresh_days=9999)
    print("[verify L5 6y] 预加载 px_cache...", flush=True)
    t_load = time.time()
    px_cache = {}
    for i, code in enumerate(universe, 1):
        df = loader.get_daily(code, START, END)
        if not df.empty:
            px_cache[code] = df
        if i % 500 == 0:
            print(f"  loaded {i}/{len(universe)}", flush=True)
    print(f"  px_cache: {len(px_cache)} 只, elapsed={time.time()-t_load:.0f}s", flush=True)

    results = []
    for tag, override in EXPERIMENTS:
        results.append(run_one(tag, base_config, override, loader, universe, px_cache))

    out_md = root / "data/backtest/zhuang_l5_verify_6y_summary.md"
    lines = [
        "# zhuang L5 仓位 sizing 6 年验证",
        "",
        f"窗口: {START} → {END}",
        "",
        "| 标签 | Sharpe | 收益 | DD | 胜率 | PF | 笔数 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['tag']} | {r['sharpe']:.3f} | {r['total_return']*100:+.1f}% | "
            f"{r['max_drawdown']*100:.1f}% | {r['win_rate']*100:.1f}% | "
            f"{r['profit_factor']:.2f} | {r['total_trades']} |"
        )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    out_md.with_suffix(".json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\n[verify L5 6y] summary → {out_md}", flush=True)


if __name__ == "__main__":
    main()
