"""
预热 HS300 daily cache. 单线程顺序拉, 量级约 1 小时内（视网络）.

实时把进度写到 data/prefetch_progress.txt, 供前端查看.
失败的股票记录到 data/prefetch_failed.txt, 后续可重试.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_system.config import load_config
from quant_system.data.loader import DataLoader


def main() -> None:
    cfg = load_config()
    hsi = cfg.get("data", "hang_seng_indexes", default=None) or {}
    loader = DataLoader(
        cfg.cache_dir,
        refresh_days=999,
        price_adjust=cfg.get("data", "price_adjust", default="qfq"),
        hang_seng_indexes=hsi,
    )

    progress_path = Path(__file__).resolve().parents[1] / "data" / "prefetch_progress.txt"
    failed_path = Path(__file__).resolve().parents[1] / "data" / "prefetch_failed.txt"
    progress_path.parent.mkdir(parents=True, exist_ok=True)

    universe = loader.get_universe("a_share", "hs300")
    all_codes = universe["code"].tolist()

    existing = {c for c in all_codes if loader.daily_cache_path("a_share", c).exists()}
    todo = [c for c in all_codes if c not in existing]

    progress_path.write_text(
        f"start at {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"universe size: {len(all_codes)}\n"
        f"price_adjust: {repr(loader.price_adjust)}\n"
        f"already cached: {len(existing)}\n"
        f"todo: {len(todo)}\n",
        encoding="utf-8",
    )

    failed = []
    t0 = time.time()
    for i, code in enumerate(todo, 1):
        try:
            loader.get_daily("a_share", code, "2024-01-01", "2030-01-01")
        except Exception as e:
            failed.append((code, type(e).__name__))

        if i % 50 == 0:
            elapsed = time.time() - t0
            rate = i / elapsed
            eta_sec = (len(todo) - i) / rate if rate > 0 else 0
            with open(progress_path, "a", encoding="utf-8") as f:
                f.write(
                    f"  [{i:>5}/{len(todo)}] {code}  "
                    f"elapsed {elapsed/60:.1f}m  rate {rate:.2f}/s  "
                    f"ETA {eta_sec/60:.0f}m  失败 {len(failed)}\n"
                )

    elapsed = time.time() - t0
    with open(progress_path, "a", encoding="utf-8") as f:
        f.write(
            f"\nDONE at {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"total {len(todo)} 只, 用时 {elapsed/60:.1f}m, 失败 {len(failed)}\n"
        )

    if failed:
        failed_path.write_text(
            "\n".join(f"{c}\t{e}" for c, e in failed), encoding="utf-8"
        )

    print(f"DONE: {len(todo)} fetched, {len(failed)} failed, {elapsed/60:.1f}m")


if __name__ == "__main__":
    main()
