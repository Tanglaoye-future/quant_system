#!/usr/bin/env python3
"""CB mini-backfill 验证 CBDataLoader 实战 (PR3 收尾).

目标:
1. 验证 akshare → CBDataLoader schema 映射在真数据上 work (mock 看不出列名/dtype 漂移)
2. 跑 10 只 active 债的 [2024-01-01, 2026-06-13] panel 拉取, 计时, 线性外推全市场 backfill
3. 第二次相同切片调用必须 < 1s (DuckDB cache hit), 与 mock 测试 test_load_panel_caches_to_duckdb 同义验证

用法:
  ./venv/bin/python scripts/research/cb_backfill.py
  ./venv/bin/python scripts/research/cb_backfill.py --n 20    # 改样本数
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_system.strategies.cb_double_low.data.loader import CBDataLoader  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=10, help="样本债券数")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-06-13")
    parser.add_argument(
        "--cache-dir",
        default=str(ROOT / "data" / "cache" / "cb_double_low"),
    )
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir)
    loader = CBDataLoader(cache_dir=cache_dir)

    # ── 1. universe ────────────────────────────────────────────────────
    print(f"=== Universe (asof=today, full 1022 expected) ===")
    t0 = time.time()
    universe = loader.load_universe(asof=date.today())
    t_uni = time.time() - t0
    print(f"shape: {universe.shape}, elapsed: {t_uni:.2f}s")
    print(f"exit_status 分布: {universe['exit_status'].value_counts().to_dict()}")
    print(f"listing_date 范围: {universe['listing_date'].min()} ~ {universe['listing_date'].max()}")
    active = universe[universe["exit_status"] == "active"].copy()
    print(f"active 债数: {len(active)}")

    # ── 2. mini panel backfill ─────────────────────────────────────────
    sample_codes = active["bond_code"].head(args.n).tolist()
    print(f"\n=== Panel backfill {args.n} 只 [{args.start}, {args.end}] (cold) ===")
    print(f"codes: {sample_codes[:5]}... (showing first 5)")
    start_dt = date.fromisoformat(args.start)
    end_dt = date.fromisoformat(args.end)
    t0 = time.time()
    panel = loader.load_panel(start=start_dt, end=end_dt, codes=sample_codes)
    t_cold = time.time() - t0
    print(f"shape: {panel.shape}, elapsed: {t_cold:.2f}s ({t_cold/args.n:.2f}s/只)")
    if len(panel) > 0:
        per_code = panel.groupby("bond_code").size()
        print(f"行数/code 分布: min={per_code.min()} max={per_code.max()} median={int(per_code.median())}")
        print(f"列 sample (1 row): {panel.iloc[0].to_dict()}")
    else:
        print("⚠️ panel 为空")

    # ── 3. cache hit 验证 ───────────────────────────────────────────────
    print(f"\n=== Panel re-fetch 同切片 (hot, expect << cold) ===")
    t0 = time.time()
    panel2 = loader.load_panel(start=start_dt, end=end_dt, codes=sample_codes)
    t_hot = time.time() - t0
    print(f"shape: {panel2.shape}, elapsed: {t_hot:.3f}s")
    speedup = t_cold / max(t_hot, 1e-6)
    print(f"speedup (cold/hot): {speedup:.1f}x")
    if t_hot > 1.0:
        print("⚠️ hot 路径 > 1s, DuckDB cache 未生效")
    else:
        print("✅ cache hit OK")

    # ── 4. redemption events ──────────────────────────────────────────
    print(f"\n=== Redemption events (asof=today) ===")
    t0 = time.time()
    redeem = loader.load_redemption_events(asof=date.today())
    t_rd = time.time() - t0
    print(f"shape: {redeem.shape}, elapsed: {t_rd:.2f}s")
    if len(redeem) > 0:
        print(f"status 分布: {redeem['status'].value_counts().to_dict()}")

    # ── 5. spot ─────────────────────────────────────────────────────────
    print(f"\n=== Spot (实时 today) ===")
    t0 = time.time()
    spot = loader.get_spot_today()
    t_sp = time.time() - t0
    print(f"shape: {spot.shape}, elapsed: {t_sp:.2f}s")

    # ── 6. 全市场 backfill 外推 ────────────────────────────────────────
    print(f"\n=== 全市场 backfill 外推 ===")
    full_n = len(universe)
    proj_secs = (t_cold / args.n) * full_n
    print(f"实测 {args.n} 只 cold: {t_cold:.1f}s = {t_cold/args.n:.2f}s/只")
    print(f"线性外推 {full_n} 只: {proj_secs:.0f}s = {proj_secs/60:.1f} min")
    spec_est = 8.5  # min, spec 估算
    delta_pct = (proj_secs / 60 - spec_est) / spec_est * 100
    print(f"spec 估算 {spec_est} min, 偏离 {delta_pct:+.1f}%")

    loader.close()


if __name__ == "__main__":
    main()
