#!/usr/bin/env python3
"""
zhuang L4 出场规则单变量扫描.

基线: L1-E (pos_min=0.4, score=70) — 已写入 config/zhuang.yaml.
扫描出场参数: take_profit / atr_mult / momentum_stop / max_hold / extend_profit / dist_thresh.

为了节省 IO/CPU，所有实验复用一次性加载的 universe + price cache (在 backtester 内已带 px_cache，
但每次 run() 重新加载；这里通过共享 loader + 缓存 disk CSV 实现近似复用).

用法:
  PYTHONPATH=src venv/bin/python scripts/backtest/run_l4_sweep_zhuang.py \\
      --start 2022-01-01 --end 2024-12-31 \\
      --universe-file data/cache/universe_2026-05-16.csv
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

import pandas as pd
import yaml

from quant_system.strategies.zhuang.data.loader import ZhuangDataLoader
from quant_system.strategies.zhuang.engine.backtest import ZhuangBacktester


# (tag, override_key, override_value)
ALL_L4_EXPERIMENTS: list[tuple[str, str, float | int]] = [
    ("L4A1-tp010", "take_profit_pct", 0.10),
    ("L4A2-tp020", "take_profit_pct", 0.20),
    ("L4B1-atr15", "stop_loss_atr_mult", 1.5),
    ("L4B2-atr25", "stop_loss_atr_mult", 2.5),
    ("L4C1-ms003", "momentum_stop_pct", 0.03),
    ("L4C2-ms007", "momentum_stop_pct", 0.07),
    ("L4D1-mh010", "max_hold_days", 10),
    ("L4D2-mh020", "max_hold_days", 20),
    ("L4E1-ep003", "extend_profit_pct", 0.03),
    ("L4E2-ep008", "extend_profit_pct", 0.08),
    ("L4F1-dt060", "distribution_turnover_thresh", 6.0),
    ("L4F2-dt100", "distribution_turnover_thresh", 10.0),
]


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--universe-file", required=True)
    p.add_argument("--config", default="config/zhuang.yaml")
    p.add_argument("--refresh-days", type=int, default=9999)
    p.add_argument("--summary-out", default="data/backtest/zhuang_l4_summary.md")
    p.add_argument("--skip-baseline", action="store_true",
                   help="跳过 baseline-L1E (已有结果时复用)")
    p.add_argument("--only-tags", nargs="*", default=None,
                   help="只跑指定 tag 列表 (e.g. L4A2-tp020 L4B1-atr15)")
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
        f"[{tag}] override={override} | sharpe={out['sharpe']:.3f} "
        f"ret={out['total_return']*100:+.1f}% dd={out['max_drawdown']*100:.1f}% "
        f"win={out['win_rate']*100:.1f}% pf={out['profit_factor']:.2f} "
        f"trades={out['total_trades']} elapsed={elapsed:.0f}s",
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
    print(f"[L4 sweep] universe size={len(universe)} | window={args.start}→{args.end}", flush=True)

    loader = ZhuangDataLoader(base_config, refresh_days=args.refresh_days)

    # 一次性加载 px_cache，所有实验共享（节省 4min × N 次）
    print("[L4 sweep] 预加载 px_cache（一次性）...", flush=True)
    t_load = time.time()
    px_cache: dict = {}
    for i, code in enumerate(universe, 1):
        df = loader.get_daily(code, args.start, args.end)
        if not df.empty:
            px_cache[code] = df
        if i % 500 == 0:
            print(f"  loaded {i}/{len(universe)}", flush=True)
    print(f"[L4 sweep] px_cache loaded: {len(px_cache)} 只, elapsed={time.time()-t_load:.0f}s", flush=True)

    results: list[dict] = []

    if not args.skip_baseline:
        results.append(run_one(
            "baseline-L1E", base_config, {},
            loader, args.start, args.end, universe, px_cache,
        ))

    exp_list = ALL_L4_EXPERIMENTS
    if args.only_tags:
        wanted = set(args.only_tags)
        exp_list = [e for e in ALL_L4_EXPERIMENTS if e[0] in wanted]

    for tag, key, val in exp_list:
        results.append(run_one(
            tag, base_config, {key: val},
            loader, args.start, args.end, universe, px_cache,
        ))

    # markdown summary
    out_md = root / args.summary_out
    out_md.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# zhuang L4 出场规则单变量扫描\n",
        f"窗口: {args.start} → {args.end}  universe: {len(universe)} 只\n",
        f"基线: L1-E (entry_price_position_min=0.4, accumulation_score_entry=70)\n",
        "",
        "| 标签 | 覆盖 | Sharpe | 收益 | DD | 胜率 | PF | 笔数 |",
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

    # json dump
    out_json = out_md.with_suffix(".json")
    out_json.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n[L4 sweep] summary saved to {out_md}", flush=True)
    print(f"[L4 sweep] json saved to {out_json}", flush=True)


if __name__ == "__main__":
    main()
