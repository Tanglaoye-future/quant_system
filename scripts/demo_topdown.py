"""
端到端验证 topdown 模块.
首次跑会拉 ~10 个行业的历史日线 (用 only_cached_hist=False), 每只 2-3 秒.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_system.config import load_config
from quant_system.topdown.macro import SectorEngine, assess_macro


def main() -> None:
    cfg = load_config()
    asof = "2026-04-27"

    print("=" * 78)
    print("宏观快照")
    print("=" * 78)
    snap = assess_macro(cfg.cache_dir)
    print(f"  CPI 12M 累计同比: {snap.cpi_yoy}  ({snap.cpi_direction}, asof {snap.asof_cpi})")
    print(f"  PPI 当月同比:    {snap.ppi_yoy}  ({snap.ppi_direction}, asof {snap.asof_ppi})")
    print(f"  >> 经济周期判定: {snap.regime}")

    print()
    print("=" * 78)
    print("行业排名 (top 10, 按 60 日动量+当日+内部健康度综合)")
    print("=" * 78)
    eng = SectorEngine(cfg.cache_dir)
    print("  扫 496 个板块... (首次拉前 10 个的历史日线, 约 30 秒)", flush=True)

    # 第一轮: 不拉历史 (only_cached=True), 仅看当日数据 + 已 cache 的
    initial = eng.rank(asof, top_n=20, only_cached_hist=True)
    print(f"  仅当日 + cache: 取前 20 进入第二轮拉历史:")
    pre_top = [r.sector for r in initial[:10]]
    print(f"    {pre_top}")

    # 第二轮: 给前 10 拉历史日线
    for sector in pre_top:
        eng._sector_hist(sector, asof)
    final = eng.rank(asof, top_n=10, only_cached_hist=True)

    print()
    print(f"  {'排名':<4} {'板块':<14} {'当日%':>6} {'60日%':>7} {'健康':>5} {'综合分':>7}")
    for i, r in enumerate(final, 1):
        print(f"  {i:<4} {r.sector:<14} {r.pct_chg_today:>6.2f} "
              f"{r.pct_chg_60d:>7.2f} {r.health*100:>5.0f} {r.score:>7.2f}")

    print()
    print("=" * 78)
    print("候选池 (top 3 行业的成分股, 仅展示数量)")
    print("=" * 78)
    pool = eng.candidate_pool(asof, top_n_sectors=3, only_cached_hist=True)
    total = 0
    for sector, codes in pool.items():
        print(f"  {sector:<14}  {len(codes):>4} 只")
        if codes[:3]:
            print(f"    样本: {', '.join(f'{c}({n})' for c, n in codes[:3])}")
        total += len(codes)
    print(f"\n  合计候选: {total} 只")


if __name__ == "__main__":
    main()
