"""
近 30 个交易日的 entry signal 触发分布 (全 HS300, 不依赖因子打分).
结果写入 data/baseline_signals.txt 避免 stdout buffering.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_system.config import load_config
from quant_system.data.loader import DataLoader
from quant_system.timing.signals import TimingConfig, scan_entries


def main() -> None:
    cfg = load_config()
    loader = DataLoader(cfg.cache_dir)
    tcfg = TimingConfig()
    asof = "2026-04-27"

    out_path = Path(__file__).resolve().parents[1] / "data" / "baseline_signals.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = open(out_path, "w", encoding="utf-8")

    def log(msg: str) -> None:
        out.write(msg + "\n")
        out.flush()
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()

    universe = loader.get_universe("a_share", "hs300")
    log(f"universe: {len(universe)} 只")

    end_dt = pd.to_datetime(asof)
    start_30d = (end_dt - pd.Timedelta(days=45)).strftime("%Y-%m-%d")

    count = defaultdict(int)
    hits_per_stock: dict[str, list] = {}
    n_ok = 0
    n_short = 0
    n_fail = 0

    for i, code in enumerate(universe["code"], 1):
        if i % 50 == 0:
            log(f"  ...{i}/{len(universe)} 处理中")
        # 跳过没缓存的, 避免在线 fetch 被限流卡死
        cache_path = cfg.cache_dir / f"daily_a_share_{code}.parquet"
        if not cache_path.exists():
            n_fail += 1
            continue
        try:
            px = loader.get_daily("a_share", code, "2024-01-01", asof)
        except Exception:
            n_fail += 1
            continue
        if len(px) < tcfg.ma_long + 5:
            n_short += 1
            continue
        n_ok += 1
        hits = scan_entries(px, tcfg)
        if hits.empty:
            continue
        recent = hits[hits["date"] >= start_30d]
        if not recent.empty:
            hits_per_stock[code] = recent["date"].tolist()
        for d in recent["date"]:
            count[d] += 1

    log(f"\n处理结果: ok={n_ok}, short_history={n_short}, fail={n_fail}\n")

    log(f"近 ~30 个交易日 entry signal 触发分布 (全 universe):")
    log(f"{'日期':<12} {'触发只数'}")
    for d in sorted(count.keys()):
        log(f"  {d}    {count[d]}")

    log(f"\n累计触发 {sum(count.values())} 次, 涉及 {len(hits_per_stock)} 只股票")
    log(f"\n触发最多的 10 只股票:")
    sorted_stocks = sorted(hits_per_stock.items(), key=lambda x: -len(x[1]))[:10]
    name_map = dict(zip(universe["code"], universe["name"]))
    for code, dates in sorted_stocks:
        log(f"  {code} {name_map.get(code, '?')}  {len(dates)} 次  最近: {dates[-1]}")

    out.close()
    print(f"\nDONE -> {out_path}")


if __name__ == "__main__":
    main()
