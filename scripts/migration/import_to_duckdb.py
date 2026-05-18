#!/usr/bin/env python3
"""
一次性把现有 CSV/parquet 价格缓存导入 data/quant.duckdb.

来源:
  1. data/cache/daily_a_share_*.parquet   (equity_factor, qfq)
  2. data/cache/daily_hk_share_*.parquet  (equity_factor)
  3. data/cache/daily_us_share_*.parquet  (equity_factor)
  4. data/prices/{code}_daily.csv         (zhuang A 股全市场, 含 turnover_rate)
  5. data/hk_prices/*.csv                 (equity_factor HK 原始)
  6. data/us_prices/*.csv                 (equity_factor US 原始)

策略:
  - 重建 daily_bars 表 (--rebuild)，避免脏数据
  - 先导 equity_factor (HS300, 无 turnover_rate)
  - 再导 zhuang (带 turnover_rate, upsert 覆盖 a_share 重合代码)
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import pandas as pd

from quant_system.data import DuckDBStore


# (parquet 文件名 → market, code)
DAILY_PARQUET_RE = re.compile(
    r"^daily_(?P<market>a_share|hk_share|us_share)_(?P<code>[^_]+?)"
    r"(?:_(?:raw|hfq))?\.parquet$"
)


def import_equity_factor_parquets(store: DuckDBStore, cache_dir: Path) -> dict:
    """导入 data/cache/daily_*.parquet (qfq only, 跳过 _raw / _hfq)."""
    stats = {"a_share": 0, "hk_share": 0, "us_share": 0, "files": 0, "rows": 0}
    files = sorted(cache_dir.glob("daily_*.parquet"))
    print(f"[ef-parquet] 扫描 {len(files)} 个文件...", flush=True)
    for i, fp in enumerate(files, 1):
        m = DAILY_PARQUET_RE.match(fp.name)
        if not m:
            continue
        # 跳过 _raw / _hfq, 只要 qfq 默认版本
        if any(s in fp.name for s in ("_raw.parquet", "_hfq.parquet")):
            continue
        market = m.group("market")
        code = m.group("code")
        try:
            df = pd.read_parquet(fp)
        except Exception as e:
            print(f"  [WARN] 读 {fp.name}: {e}", file=sys.stderr, flush=True)
            continue
        if df.empty:
            continue
        df = df.copy()
        df["code"] = code
        try:
            n = store.bulk_insert_daily(market, df, replace=False)
            stats[market] += n
            stats["rows"] += n
            stats["files"] += 1
        except Exception as e:
            print(f"  [WARN] 写 {fp.name}: {e}", file=sys.stderr, flush=True)
        if i % 100 == 0:
            print(f"  [ef-parquet] {i}/{len(files)}", flush=True)
    return stats


def import_zhuang_csvs(store: DuckDBStore, prices_dir: Path) -> dict:
    """
    导入 data/prices/{code}_daily.csv (zhuang, A 股, 含 turnover_rate).

    会 upsert 覆盖 a_share 重合代码 (zhuang 数据更全; equity_factor 没有 turnover_rate).
    """
    stats = {"files": 0, "rows": 0, "skipped": 0}
    files = sorted(prices_dir.glob("*_daily.csv"))
    print(f"[zhuang-csv] 扫描 {len(files)} 个文件...", flush=True)

    # 累积成大 batch 再批量 upsert，提速
    batch_rows: list[pd.DataFrame] = []
    BATCH_SIZE = 200

    def _flush_batch():
        if not batch_rows:
            return
        big = pd.concat(batch_rows, ignore_index=True)
        n = store.bulk_insert_daily("a_share", big, replace=True)
        stats["rows"] += n
        batch_rows.clear()

    for i, fp in enumerate(files, 1):
        code = fp.stem.split("_")[0]
        try:
            df = pd.read_csv(fp)
        except Exception as e:
            print(f"  [WARN] 读 {fp.name}: {e}", file=sys.stderr, flush=True)
            stats["skipped"] += 1
            continue
        if df.empty or "date" not in df.columns:
            stats["skipped"] += 1
            continue
        df = df.copy()
        df["code"] = code
        batch_rows.append(df)
        stats["files"] += 1

        if len(batch_rows) >= BATCH_SIZE:
            _flush_batch()
        if i % 500 == 0:
            print(f"  [zhuang-csv] {i}/{len(files)}", flush=True)

    _flush_batch()
    return stats


def import_hk_us_csvs(store: DuckDBStore, csv_dir: Path, market: str) -> dict:
    """导入 hk_prices/ 或 us_prices/ 下的原始 csv."""
    stats = {"files": 0, "rows": 0, "skipped": 0}
    if not csv_dir.exists():
        return stats
    files = sorted(csv_dir.glob("*.csv"))
    print(f"[{market}-csv] 扫描 {len(files)} 个文件 in {csv_dir}...", flush=True)

    batch_rows: list[pd.DataFrame] = []
    BATCH_SIZE = 100

    def _flush_batch():
        if not batch_rows:
            return
        big = pd.concat(batch_rows, ignore_index=True)
        n = store.bulk_insert_daily(market, big, replace=False)
        stats["rows"] += n
        batch_rows.clear()

    for i, fp in enumerate(files, 1):
        code = fp.stem  # 文件名即代码 (HKEX/US ticker)
        try:
            df = pd.read_csv(fp)
        except Exception as e:
            print(f"  [WARN] 读 {fp.name}: {e}", file=sys.stderr, flush=True)
            stats["skipped"] += 1
            continue
        if df.empty:
            stats["skipped"] += 1
            continue
        # 统一中英文列名
        cn_map = {"日期": "date", "开盘": "open", "最高": "high",
                  "最低": "low", "收盘": "close", "成交量": "volume"}
        df = df.rename(columns=cn_map)
        need = ["date", "open", "high", "low", "close", "volume"]
        if not all(c in df.columns for c in need):
            stats["skipped"] += 1
            continue
        df = df.copy()
        df["code"] = code
        batch_rows.append(df)
        stats["files"] += 1

        if len(batch_rows) >= BATCH_SIZE:
            _flush_batch()
        if i % 50 == 0:
            print(f"  [{market}-csv] {i}/{len(files)}", flush=True)

    _flush_batch()
    return stats


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--db-path", default="data/quant.duckdb")
    p.add_argument("--rebuild", action="store_true",
                   help="导入前 DROP 重建 daily_bars 表")
    p.add_argument("--skip-equity-factor", action="store_true")
    p.add_argument("--skip-zhuang", action="store_true")
    p.add_argument("--skip-hk-us", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    db_path = (root / args.db_path) if not Path(args.db_path).is_absolute() else Path(args.db_path)
    print(f"[import] db_path = {db_path}", flush=True)

    store = DuckDBStore(db_path)
    if args.rebuild:
        print("[import] DROP daily_bars 重建...", flush=True)
        con = store._connect()
        con.execute("DROP TABLE IF EXISTS daily_bars")
        store._init_schema(con)

    t0 = time.time()
    if not args.skip_equity_factor:
        s = import_equity_factor_parquets(store, root / "data" / "cache")
        print(f"[ef-parquet] done: {s}", flush=True)
    if not args.skip_hk_us:
        s_hk = import_hk_us_csvs(store, root / "data" / "hk_prices", "hk_share")
        print(f"[hk-csv] done: {s_hk}", flush=True)
        s_us = import_hk_us_csvs(store, root / "data" / "us_prices", "us_share")
        print(f"[us-csv] done: {s_us}", flush=True)
    if not args.skip_zhuang:
        s = import_zhuang_csvs(store, root / "data" / "prices")
        print(f"[zhuang-csv] done: {s}", flush=True)

    print(f"\n[import] total elapsed: {time.time()-t0:.0f}s", flush=True)
    print("\n[import] stats:")
    print(store.stats().to_string(index=False))
    store.close()


if __name__ == "__main__":
    main()
