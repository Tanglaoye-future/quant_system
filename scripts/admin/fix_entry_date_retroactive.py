#!/usr/bin/env python3
"""Retroactive fix: 把 journal_trades 里 entry_date 与 entry_price 实际 K 线日
错位的行修回 (06-08 实盘 bug — 周一跑 daily 时 baostock 当日 K 线未入库,
entry_date 写 args.asof='2026-06-08' 但 entry_price 是上周五 06-05 close).

详 docs/specs/fix_hold_days_entry_bar_date.md.

用法:
    venv/bin/python scripts/admin/fix_entry_date_retroactive.py --dry-run
    venv/bin/python scripts/admin/fix_entry_date_retroactive.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date


# 已知错位的 trade — 06-08 daily 跑时入场, 实际 K 线是 06-05
KNOWN_OFFSETS: list[dict] = [
    {"trade_id": 5, "symbol": "601988", "old_entry": "2026-06-08", "new_entry": "2026-06-05"},
    {"trade_id": 6, "symbol": "000063", "old_entry": "2026-06-08", "new_entry": "2026-06-05"},
]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Retro fix entry_date 错位")
    p.add_argument("--dry-run", action="store_true", help="只打印不修")
    p.add_argument("--apply", action="store_true", help="真改 DB")
    args = p.parse_args(argv)

    if not args.dry_run and not args.apply:
        print("必须指定 --dry-run 或 --apply", file=sys.stderr)
        return 2

    os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://quant:quant@localhost:5432/quant")
    from sqlalchemy import create_engine, text

    eng = create_engine(os.environ["DATABASE_URL"])
    with eng.begin() as c:
        for entry in KNOWN_OFFSETS:
            row = c.execute(
                text("SELECT id, symbol, entry_date FROM journal_trades WHERE id = :tid"),
                {"tid": entry["trade_id"]},
            ).mappings().one_or_none()
            if row is None:
                print(f"  trade #{entry['trade_id']} 不存在, 跳过")
                continue
            db_symbol = row["symbol"]
            db_entry_date = str(row["entry_date"])
            if db_symbol != entry["symbol"]:
                print(f"  ⚠ trade #{entry['trade_id']} symbol={db_symbol} != 预期 {entry['symbol']}, 跳过")
                continue
            if db_entry_date != entry["old_entry"]:
                print(f"  ⚠ trade #{entry['trade_id']} entry_date={db_entry_date} != 预期 {entry['old_entry']}, 已被修过? 跳过")
                continue
            print(
                f"  trade #{entry['trade_id']} {db_symbol}: "
                f"entry_date {db_entry_date} → {entry['new_entry']}"
            )
            if args.apply:
                c.execute(
                    text("UPDATE journal_trades SET entry_date = :new_date WHERE id = :tid"),
                    {"new_date": date.fromisoformat(entry["new_entry"]), "tid": entry["trade_id"]},
                )
        if args.apply:
            print("✓ apply 完成")
        else:
            print("(dry-run; 加 --apply 真改)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
