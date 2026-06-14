"""
zhuang 出场参数 sweep — A 方向优化.
测试 momentum_stop / dead_money / max_hold_days / stop_loss_atr_mult 组合.
复用 px_cache 避免重复加载 2597 只股票.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from quant_system.strategies.zhuang.data.loader import ZhuangDataLoader
from quant_system.strategies.zhuang.engine.backtest import ZhuangBacktester


def load_config() -> dict:
    cfg_path = Path(__file__).resolve().parent.parent.parent / "config" / "zhuang.yaml"
    with open(cfg_path) as f:
        return yaml.safe_load(f)


def main():
    base_cfg = load_config()
    start = "2018-01-01"
    end = "2026-06-09"

    # ── 一次性加载 universe + px_cache ──────────────────────────────────
    print("=" * 60)
    print("  一次性预加载 universe + 全部行情 (供 6 变体复用)")
    print("=" * 60)
    loader = ZhuangDataLoader(base_cfg, refresh_days=999, market="a_share")
    print(f"[init] 获取 universe (asof={start})...")
    universe = loader.get_universe(start)
    print(f"[init] universe size = {len(universe)}")

    px_cache: dict[str, pd.DataFrame] = {}
    for i, code in enumerate(universe, 1):
        df = loader.get_daily(code, start, end)
        if not df.empty:
            px_cache[code] = df
        if i % 500 == 0:
            print(f"  [init] loaded {i}/{len(universe)}")
    print(f"[init] px_cache ready: {len(px_cache)} stocks")

    # ── 变体定义 ────────────────────────────────────────────────────────
    variants = [
        {
            "name": "baseline (当前配置, dead_money OFF)",
            "strat_overrides": {"dead_money_days": 999},
        },
        {
            "name": "A1: momentum_stop 10%→5%",
            "strat_overrides": {
                "momentum_stop_pct": 0.05,
                "dead_money_days": 999,
            },
        },
        {
            "name": "A2: momentum_stop 5% + dead_money(5d,2%)",
            "strat_overrides": {
                "momentum_stop_pct": 0.05,
                "dead_money_days": 5,
                "dead_money_pct": 0.02,
            },
        },
        {
            "name": "A3: A2 + max_hold_days 10→7",
            "strat_overrides": {
                "momentum_stop_pct": 0.05,
                "dead_money_days": 5,
                "dead_money_pct": 0.02,
                "max_hold_days": 7,
            },
        },
        {
            "name": "A4: A3 + stop_loss_atr_mult 1.5→2.0",
            "strat_overrides": {
                "momentum_stop_pct": 0.05,
                "dead_money_days": 5,
                "dead_money_pct": 0.02,
                "max_hold_days": 7,
                "stop_loss_atr_mult": 2.0,
            },
        },
        {
            "name": "A5: A4 + max_stop_loss_pct 6%→8%",
            "strat_overrides": {
                "momentum_stop_pct": 0.05,
                "dead_money_days": 5,
                "dead_money_pct": 0.02,
                "max_hold_days": 7,
                "stop_loss_atr_mult": 2.0,
                "max_stop_loss_pct": 0.08,
            },
        },
    ]

    results = []
    for v in variants:
        cfg = copy.deepcopy(base_cfg)
        for k, val in v["strat_overrides"].items():
            cfg["strategy"][k] = val

        print(f"\n{'='*60}")
        print(f"  {v['name']}")
        print(f"{'='*60}")
        # 复用当前 loader + px_cache
        bt = ZhuangBacktester(cfg, loader)
        metrics = bt.run(
            start=start, end=end, universe=universe,
            verbose=True, px_cache=px_cache,
        )
        print(f"  Sharpe={metrics['sharpe_ratio']:.4f}  tot={metrics['total_return']*100:+.2f}%  "
              f"DD={metrics['max_drawdown']*100:.2f}%  wr={metrics['win_rate']*100:.1f}%  "
              f"n={metrics['total_trades']}")
        results.append({"name": v["name"], "metrics": metrics})

    # ── Summary ─────────────────────────────────────────────────────────
    print("\n" + "=" * 90)
    print("  EXIT SWEEP SUMMARY — A 方向优化")
    print("=" * 90)
    fmt = "{:<55s} {:>7s} {:>8s} {:>8s} {:>7s} {:>5s} {:>8s}"
    print(fmt.format("variant", "Sharpe", "TotRet%", "AnnRet%", "DD%", "WR%", "N"))
    print("-" * 90)
    for r in results:
        m = r["metrics"]
        name = r["name"][:55]
        print(fmt.format(
            name,
            f"{m['sharpe_ratio']:.4f}",
            f"{m['total_return']*100:+.2f}%",
            f"{m['annualized_return']*100:+.2f}%",
            f"{m['max_drawdown']*100:.2f}%",
            f"{m['win_rate']*100:.1f}%",
            f"{m['total_trades']}",
        ))

    # ── Save ────────────────────────────────────────────────────────────
    out = Path(__file__).resolve().parent.parent.parent / "data" / "backtest" / "zhuang_exit_sweep_A.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Convert numpy types for JSON
    clean_results = []
    for r in results:
        cm = {}
        for k, v in r["metrics"].items():
            if hasattr(v, "item"):
                cm[k] = v.item()
            else:
                cm[k] = v
        clean_results.append({"name": r["name"], "metrics": cm})
    with open(out, "w") as f:
        json.dump(clean_results, f, indent=2)
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
