#!/usr/bin/env python3
"""
zhuang L4 出场规则组合实验.

单变量扫描发现 6 个"收紧"方向全部正向。这里叠加 top winner 找最优组合：
  combo1: mh=10 + tp=0.10                              (前 2 强)
  combo2: + atr=1.5                                    (前 3 强)
  combo3: + dt=6.0                                     (前 4 强)
  combo4: + ms=0.03                                    (前 5 强)
  combo5: + ep=0.08                                    (前 6 强)

最优组合再跑 2020-2026 6 年验证。

用法:
  PYTHONUNBUFFERED=1 PYTHONPATH=src .venv/bin/python -u \\
      scripts/backtest/run_l4_combo_zhuang.py \\
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


# (tag, override_dict) — 按 winner 强度逐层叠加
COMBOS: list[tuple[str, dict]] = [
    ("L4-combo1", {"max_hold_days": 10, "take_profit_pct": 0.10}),
    ("L4-combo2", {"max_hold_days": 10, "take_profit_pct": 0.10,
                   "stop_loss_atr_mult": 1.5}),
    ("L4-combo3", {"max_hold_days": 10, "take_profit_pct": 0.10,
                   "stop_loss_atr_mult": 1.5,
                   "distribution_turnover_thresh": 6.0}),
    ("L4-combo4", {"max_hold_days": 10, "take_profit_pct": 0.10,
                   "stop_loss_atr_mult": 1.5,
                   "distribution_turnover_thresh": 6.0,
                   "momentum_stop_pct": 0.03}),
    ("L4-combo5", {"max_hold_days": 10, "take_profit_pct": 0.10,
                   "stop_loss_atr_mult": 1.5,
                   "distribution_turnover_thresh": 6.0,
                   "momentum_stop_pct": 0.03,
                   "extend_profit_pct": 0.08}),
]


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--universe-file", required=True)
    p.add_argument("--config", default="config/zhuang.yaml")
    p.add_argument("--refresh-days", type=int, default=9999)
    p.add_argument("--summary-out", default="data/backtest/zhuang_l4_combo_summary.md")
    return p.parse_args()


def run_one(tag: str, base_config: dict, override: dict, loader: ZhuangDataLoader,
            start: str, end: str, universe: list[str], px_cache: dict) -> dict:
    cfg = copy.deepcopy(base_config)
    cfg.setdefault("strategy", {}).update(override)
    bt = cfg.setdefault("backtest", {})
    out_base = Path(bt.get("output_dir", "./data/backtest"))
    bt["output_dir"] = str(out_base / f"_l4_{tag}")

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
        f"elapsed={elapsed:.0f}s | override={override}",
        flush=True,
    )
    return out


def main():
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    with open(root / args.config, "r", encoding="utf-8") as f:
        base_config = yaml.safe_load(f)

    uf = root / args.universe_file
    df_u = pd.read_csv(uf, dtype={"code": str})
    universe = df_u["code"].str.zfill(6).tolist()
    print(f"[L4 combo] universe size={len(universe)} | window={args.start}→{args.end}", flush=True)

    loader = ZhuangDataLoader(base_config, refresh_days=args.refresh_days)

    print("[L4 combo] 预加载 px_cache...", flush=True)
    t_load = time.time()
    px_cache: dict = {}
    for i, code in enumerate(universe, 1):
        df = loader.get_daily(code, args.start, args.end)
        if not df.empty:
            px_cache[code] = df
        if i % 500 == 0:
            print(f"  loaded {i}/{len(universe)}", flush=True)
    print(f"[L4 combo] px_cache loaded: {len(px_cache)} 只, elapsed={time.time()-t_load:.0f}s", flush=True)

    results: list[dict] = []
    for tag, override in COMBOS:
        results.append(run_one(
            tag, base_config, override,
            loader, args.start, args.end, universe, px_cache,
        ))

    # markdown summary
    out_md = root / args.summary_out
    out_md.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# zhuang L4 出场规则组合实验",
        "",
        f"窗口: {args.start} → {args.end}  universe: {len(universe)} 只",
        "",
        "基线: L1-E (entry_price_position_min=0.4, accumulation_score_entry=70) → Sharpe 1.429",
        "",
        "| 标签 | 改动 | Sharpe | 收益 | DD | 胜率 | PF | 笔数 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        ov = ", ".join(f"{k}={v}" for k, v in r["override"].items())
        lines.append(
            f"| {r['tag']} | {ov} | {r['sharpe']:.3f} | "
            f"{r['total_return']*100:+.1f}% | {r['max_drawdown']*100:.1f}% | "
            f"{r['win_rate']*100:.1f}% | {r['profit_factor']:.2f} | {r['total_trades']} |"
        )
    out_md.write_text("\n".join(lines), encoding="utf-8")

    out_json = out_md.with_suffix(".json")
    out_json.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n[L4 combo] summary → {out_md}", flush=True)


if __name__ == "__main__":
    main()
