#!/usr/bin/env python3
"""
zhuang_system L1/L2/L3 experiment runner.

读取 base config.yaml，应用 CLI 参数 override 后跑回测，输出关键指标。
不动 prod config；每个实验单独 output_dir。

用法:
  python scripts/run_experiment.py --tag L1A-pos066 \
      --start 2022-01-01 --end 2024-12-31 \
      --universe-file data/cache/universe_2026-05-10.csv \
      --strategy entry_price_position_min=0.66
"""
import argparse
import json
import sys
from pathlib import Path


import pandas as pd
import yaml

from quant_system.strategies.zhuang.data.loader import ZhuangDataLoader
from quant_system.strategies.zhuang.engine.backtest import ZhuangBacktester


def parse_overrides(items):
    """parse 'k=v' list into dict; values cast to float/int when possible."""
    out = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"override 必须是 k=v: {item}")
        k, v = item.split("=", 1)
        try:
            v_cast = float(v) if "." in v else int(v)
        except ValueError:
            v_cast = v
        out[k.strip()] = v_cast
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tag", required=True, help="实验标签 (output_dir suffix)")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--universe-file", required=True)
    p.add_argument("--config", default="config/zhuang.yaml")
    p.add_argument("--refresh-days", type=int, default=9999)
    p.add_argument("--strategy", nargs="*", default=[],
                   help="override strategy.* params, e.g. entry_price_position_min=0.66")
    p.add_argument("--accumulation-weights", nargs="*", default=[],
                   help="override accumulation_weights.* params")
    args = p.parse_args()

    root = Path(__file__).resolve().parents[2]
    with open(root / args.config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    strat_over = parse_overrides(args.strategy)
    aw_over = parse_overrides(args.accumulation_weights)

    config.setdefault("strategy", {}).update(strat_over)
    if aw_over:
        config.setdefault("accumulation_weights", {}).update(aw_over)

    # 让实验结果与 baseline 分离
    bt = config.setdefault("backtest", {})
    out_base = Path(bt.get("output_dir", "./data/backtest"))
    bt["output_dir"] = str(out_base / f"_exp_{args.tag}")

    uf = root / args.universe_file
    df_u = pd.read_csv(uf, dtype={"code": str})
    universe = df_u["code"].str.zfill(6).tolist()

    print(f"[exp:{args.tag}] strategy overrides: {strat_over}", flush=True)
    if aw_over:
        print(f"[exp:{args.tag}] acc_weights overrides: {aw_over}", flush=True)
    print(f"[exp:{args.tag}] universe size: {len(universe)}", flush=True)

    loader = ZhuangDataLoader(config, refresh_days=args.refresh_days)
    bt_engine = ZhuangBacktester(config, loader)

    metrics = bt_engine.run(start=args.start, end=args.end,
                            universe=universe, verbose=True)

    summary = {
        "tag": args.tag,
        "start": args.start, "end": args.end,
        "universe_size": len(universe),
        "overrides": {"strategy": strat_over, "accumulation_weights": aw_over},
        "metrics": {k: (float(v) if hasattr(v, "item") else v)
                    for k, v in metrics.items()},
    }
    out_dir = Path(bt["output_dir"]) / f"zhuang_a_share_{args.start}_{args.end}"
    (out_dir / "experiment_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str)
    )
    print(f"\n[exp:{args.tag}] summary saved to {out_dir}/experiment_summary.json")


if __name__ == "__main__":
    main()
