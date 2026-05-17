"""
预热 zhuang 子策略数据：universe + 全 A 股 daily cache.

数据源：BaoStock。单线程顺序拉，3307 只 × 6 年日线约 1 小时。

进度实时写 data/prefetch_progress.txt，失败列表 data/prefetch_failed.txt。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import yaml

from quant_system.strategies.zhuang.data.loader import ZhuangDataLoader


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    with open(root / "config" / "zhuang.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    loader = ZhuangDataLoader(config, refresh_days=9999)

    progress_path = root / "data" / "prefetch_progress.txt"
    failed_path = root / "data" / "prefetch_failed.txt"
    progress_path.parent.mkdir(parents=True, exist_ok=True)

    asof = time.strftime("%Y-%m-%d")
    progress_path.write_text(
        f"[zhuang] start at {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"step 1/2: fetching universe (asof={asof})...\n",
        encoding="utf-8",
    )

    universe = loader.get_universe(asof)
    print(f"[zhuang] universe size = {len(universe)}", flush=True)

    daily_dir = Path(loader.daily_dir)
    existing = {c for c in universe if (daily_dir / f"{c}_daily.csv").exists()}
    todo = [c for c in universe if c not in existing]

    progress_path.write_text(
        f"[zhuang] start at {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"universe size: {len(universe)}\n"
        f"already cached: {len(existing)}\n"
        f"todo: {len(todo)}\n",
        encoding="utf-8",
    )

    failed = []
    t0 = time.time()
    loader._login()
    for i, code in enumerate(todo, 1):
        try:
            df = loader.get_daily(code, "2020-01-01", asof)
            if df is None or df.empty:
                failed.append(code)
        except Exception as e:
            failed.append(code)
            print(f"[WARN] {code}: {e}", file=sys.stderr, flush=True)

        if i % 50 == 0 or i == len(todo):
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(todo) - i) / rate if rate > 0 else 0
            progress_path.write_text(
                f"[zhuang] {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"universe size: {len(universe)}\n"
                f"todo: {len(todo)}\n"
                f"done: {i}/{len(todo)}\n"
                f"failed: {len(failed)}\n"
                f"elapsed: {elapsed:.0f}s rate: {rate:.2f}/s eta: {eta:.0f}s\n",
                encoding="utf-8",
            )

    loader._logout()

    if failed:
        failed_path.write_text("\n".join(failed), encoding="utf-8")
        print(f"[zhuang] {len(failed)} stocks failed, see {failed_path}", flush=True)

    print(f"[zhuang] done. total elapsed={time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
