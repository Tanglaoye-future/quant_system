#!/usr/bin/env python3
"""CB 双低 strategy 端到端 smoke — 真 universe 上跑一次 compute_target_portfolio.

PR4 单元测试用 mock fixture, 本脚本走真 akshare → loader → filter → strategy 全链路.
打印 filter funnel / 入场 N 只双低 / target_weights, 验证 algo 在真数据上不爆.

用法:
  ./venv/bin/python scripts/research/cb_target_today.py            # 默认 200 只样本
  ./venv/bin/python scripts/research/cb_target_today.py --n 0      # 全市场 (~8 min cold)
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_system.strategies.cb_double_low.data.loader import CBDataLoader  # noqa: E402
from quant_system.strategies.cb_double_low.engine.strategy import (  # noqa: E402
    CBDoubleLowConfig,
    compute_target_portfolio,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=200, help="样本债券数 (0=全市场)")
    parser.add_argument("--lookback-days", type=int, default=14)
    parser.add_argument(
        "--cache-dir", default=str(ROOT / "data" / "cache" / "cb_double_low")
    )
    args = parser.parse_args()

    loader = CBDataLoader(cache_dir=Path(args.cache_dir))
    today = date.today()

    # 1. universe
    print(f"=== Universe (asof={today}) ===")
    t0 = time.time()
    universe = loader.load_universe(asof=today)
    print(f"shape: {universe.shape}, elapsed: {time.time()-t0:.2f}s")
    print(f"exit_status: {universe['exit_status'].value_counts().to_dict()}")
    active = universe[universe["exit_status"] == "active"].copy()
    print(f"active 债数: {len(active)}")

    sample = active if args.n == 0 else active.head(args.n).copy()
    codes = sample["bond_code"].tolist()
    print(f"本次 smoke 样本: {len(codes)} 只 (n={args.n})")

    # 2. panel: 拉最近 N 天找当日 close
    start = today - timedelta(days=args.lookback_days)
    print(f"\n=== Panel cold backfill [{start} → {today}] {len(codes)} 只 ===")
    t0 = time.time()
    panel = loader.load_panel(start=start, end=today, codes=codes)
    elapsed = time.time() - t0
    print(f"shape: {panel.shape}, elapsed: {elapsed:.1f}s ({elapsed/len(codes):.2f}s/只)")
    if len(panel) == 0:
        print("⚠️ panel 全空, 退出")
        loader.close()
        return

    # 3. 选 asof = panel 最新日期 (今天可能无数据 / akshare 滞后)
    panel_max_date = panel["date"].max().date()
    panel_today = panel[panel["date"] == panel["date"].max()].copy()
    print(f"\nasof (panel 最新可用日): {panel_max_date}")
    print(f"asof 当日 panel 覆盖: {len(panel_today)}/{len(codes)} 只")
    print(f"close 分布: min={panel_today['close'].min():.2f} "
          f"max={panel_today['close'].max():.2f} "
          f"median={panel_today['close'].median():.2f}")
    print(f"conversion_premium 分布: min={panel_today['conversion_premium_rate'].min():.2f}% "
          f"max={panel_today['conversion_premium_rate'].max():.2f}% "
          f"median={panel_today['conversion_premium_rate'].median():.2f}%")

    # 4. redemption
    redemption = loader.load_redemption_events(asof=panel_max_date)
    print(f"\nredemption events: {len(redemption)} 行, "
          f"status={redemption['status'].value_counts().to_dict()}")

    # 5. compute_target_portfolio (空仓启动)
    print(f"\n=== compute_target_portfolio (cold, holdings=[]) ===")
    cfg = CBDoubleLowConfig()
    out = compute_target_portfolio(
        universe=sample,
        panel_today=panel_today,
        redemption=redemption,
        current_holdings=[],
        asof=panel_max_date,
        config=cfg,
    )
    print(f"\nfilter_funnel:")
    for k, v in out["filter_stats"].items():
        print(f"  {k:<25} {v}")

    # 6. 入场列表 + 评分明细
    merged = sample.merge(
        panel_today[["bond_code", "close", "conversion_premium_rate"]],
        on="bond_code", how="inner",
    )
    merged["dual_low_score"] = merged["close"] + merged["conversion_premium_rate"]
    name_map = dict(zip(merged["bond_code"], merged["bond_name"]))
    close_map = dict(zip(merged["bond_code"], merged["close"]))
    prem_map = dict(zip(merged["bond_code"], merged["conversion_premium_rate"]))
    score_map = dict(zip(merged["bond_code"], merged["dual_low_score"]))

    print(f"\n📊 入场 ({len(out['entered'])} 只) 按 dual_low_score 升序:")
    print(f"  {'code':<8} {'name':<12} {'close':>8} {'prem%':>8} {'score':>8}")
    for code in out["entered"]:
        print(
            f"  {code:<8} {str(name_map.get(code, '?'))[:12]:<12} "
            f"{close_map.get(code, 0):>8.2f} "
            f"{prem_map.get(code, 0):>+8.2f} "
            f"{score_map.get(code, 0):>8.2f}"
        )

    print(f"\ntarget_weights: 等权 {1/cfg.n_entry:.4f} × {len(out['target_weights'])}")
    print(f"weight sum: {sum(out['target_weights'].values()):.4f}")
    print(f"exited: {len(out['exited'])} (cold start 应 0)")

    loader.close()


if __name__ == "__main__":
    main()
