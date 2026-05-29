#!/usr/bin/env python
"""一次性迁移：SQLite data/journal.db → Postgres journal_trades / journal_snapshots.

三层解耦收尾：把交易台账从独立 SQLite 并入统一 Postgres 真相源。
snapshot 的 trade_id 会重映射到 Postgres 新生成的 id（SQLite id 与 PG 不保证一致）。

用法:
  python scripts/migration/migrate_journal_to_pg.py            # PG journal 非空则中止
  python scripts/migration/migrate_journal_to_pg.py --force    # 先清空 PG journal 再迁
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from sqlalchemy import delete, func, select

from quant_system.config import load_config
from quant_system.db.models import JournalSnapshot, JournalTrade
from quant_system.db.session import session_scope


def _to_date(v):
    if v is None or v == "":
        return None
    return date.fromisoformat(str(v)[:10])


def _to_dt(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="先清空 PG journal 表再迁")
    args = ap.parse_args()

    sqlite_path = load_config().journal_db_path
    if not Path(sqlite_path).exists():
        print(f"[migrate] SQLite {sqlite_path} 不存在，无数据可迁，跳过")
        return 0

    con = sqlite3.connect(sqlite_path)
    con.row_factory = sqlite3.Row
    trades = list(con.execute("SELECT * FROM trades ORDER BY id"))
    snaps = list(con.execute("SELECT * FROM price_snapshots ORDER BY id"))
    con.close()
    print(f"[migrate] SQLite 源：trades={len(trades)} snapshots={len(snaps)}")

    with session_scope() as s:
        existing = s.scalar(select(func.count()).select_from(JournalTrade))
        if existing and not args.force:
            print(f"[migrate] ⚠ PG journal_trades 已有 {existing} 行；加 --force 清空重迁，否则中止")
            return 1
        if args.force and existing:
            s.execute(delete(JournalSnapshot))
            s.execute(delete(JournalTrade))
            s.flush()
            print(f"[migrate] --force：已清空 PG journal（{existing} trades）")

        id_map: dict[int, int] = {}
        for r in trades:
            t = JournalTrade(
                symbol=r["symbol"], market=r["market"], direction=r["direction"] or "long",
                entry_date=_to_date(r["entry_date"]), entry_price=r["entry_price"],
                entry_size=r["entry_size"], entry_score=r["entry_score"],
                reason_topdown=r["reason_topdown"], reason_bottomup=r["reason_bottomup"],
                reason_catalyst=r["reason_catalyst"], reason_timing=r["reason_timing"],
                stop_loss_price=r["stop_loss_price"], take_profit_price=r["take_profit_price"],
                exit_date=_to_date(r["exit_date"]), exit_price=r["exit_price"],
                exit_reason=r["exit_reason"], pnl=r["pnl"], pnl_pct=r["pnl_pct"],
                hold_days=r["hold_days"], notes=r["notes"],
            )
            dt = _to_dt(r["created_at"])
            if dt is not None:
                t.created_at = dt
            s.add(t)
            s.flush()
            id_map[r["id"]] = t.id

        for r in snaps:
            new_tid = id_map.get(r["trade_id"])
            if new_tid is None:
                print(f"[migrate] ⚠ snapshot id={r['id']} 的 trade_id={r['trade_id']} 无映射，跳过")
                continue
            s.add(JournalSnapshot(
                trade_id=new_tid, snapshot_date=_to_date(r["snapshot_date"]),
                price=r["price"], unrealized_pnl_pct=r["unrealized_pnl_pct"],
                risk_flag=r["risk_flag"], note=r["note"],
            ))

    with session_scope() as s:
        nt = s.scalar(select(func.count()).select_from(JournalTrade))
        ns = s.scalar(select(func.count()).select_from(JournalSnapshot))
    print(f"[migrate] ✅ PG journal 现有：trades={nt} snapshots={ns}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
