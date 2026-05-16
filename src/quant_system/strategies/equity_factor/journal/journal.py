"""
交易日志 + 复盘归因.
每笔交易记录 4 个维度的入场理由 (自上而下 / 自下而上 / 催化剂 / 技术),
出场时记录原因, 计算 P&L, 持有期, 用于事后归因分析.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,                  -- a_share / hk_share
    direction TEXT NOT NULL DEFAULT 'long',
    entry_date TEXT NOT NULL,
    entry_price REAL NOT NULL,
    entry_size INTEGER NOT NULL,
    entry_score REAL,                      -- 入场时的因子总分
    reason_topdown TEXT,
    reason_bottomup TEXT,
    reason_catalyst TEXT,
    reason_timing TEXT,
    stop_loss_price REAL,
    take_profit_price REAL,
    exit_date TEXT,
    exit_price REAL,
    exit_reason TEXT,                      -- target / stop / time / discretionary
    pnl REAL,
    pnl_pct REAL,
    hold_days INTEGER,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_open ON trades(exit_date) WHERE exit_date IS NULL;

CREATE TABLE IF NOT EXISTS price_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    snapshot_date TEXT NOT NULL,
    price REAL NOT NULL,
    unrealized_pnl_pct REAL,
    risk_flag TEXT,                        -- normal / drawdown / vol_spike / breach
    note TEXT,
    FOREIGN KEY (trade_id) REFERENCES trades(id)
);

CREATE INDEX IF NOT EXISTS idx_snap_trade ON price_snapshots(trade_id);
"""


@dataclass
class TradeOpen:
    symbol: str
    market: str
    entry_date: str
    entry_price: float
    entry_size: int
    entry_score: Optional[float] = None
    reason_topdown: Optional[str] = None
    reason_bottomup: Optional[str] = None
    reason_catalyst: Optional[str] = None
    reason_timing: Optional[str] = None
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    notes: Optional[str] = None


class Journal:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def init_schema(self) -> None:
        with self._conn() as con:
            con.executescript(SCHEMA)

    # ---------- writes ----------

    def open_trade(self, t: TradeOpen) -> int:
        with self._conn() as con:
            cur = con.execute(
                """INSERT INTO trades
                   (symbol, market, direction, entry_date, entry_price, entry_size,
                    entry_score, reason_topdown, reason_bottomup, reason_catalyst,
                    reason_timing, stop_loss_price, take_profit_price, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    t.symbol, t.market, "long", t.entry_date, t.entry_price, t.entry_size,
                    t.entry_score, t.reason_topdown, t.reason_bottomup, t.reason_catalyst,
                    t.reason_timing, t.stop_loss_price, t.take_profit_price, t.notes,
                ),
            )
            return int(cur.lastrowid)

    def close_trade(
        self, trade_id: int, exit_date: str, exit_price: float, exit_reason: str
    ) -> None:
        with self._conn() as con:
            row = con.execute(
                "SELECT entry_date, entry_price, entry_size FROM trades WHERE id = ?",
                (trade_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"trade {trade_id} 不存在")

            entry_d = date.fromisoformat(row["entry_date"])
            exit_d = date.fromisoformat(exit_date)
            hold_days = (exit_d - entry_d).days
            pnl = (exit_price - row["entry_price"]) * row["entry_size"]
            pnl_pct = exit_price / row["entry_price"] - 1.0

            con.execute(
                """UPDATE trades SET exit_date=?, exit_price=?, exit_reason=?,
                                     pnl=?, pnl_pct=?, hold_days=? WHERE id=?""",
                (exit_date, exit_price, exit_reason, pnl, pnl_pct, hold_days, trade_id),
            )

    def update_stop_loss(self, trade_id: int, new_stop: float) -> None:
        with self._conn() as con:
            con.execute(
                "UPDATE trades SET stop_loss_price=? WHERE id=?",
                (new_stop, trade_id),
            )

    def add_snapshot(
        self,
        trade_id: int,
        snapshot_date: str,
        price: float,
        risk_flag: str = "normal",
        note: Optional[str] = None,
    ) -> None:
        with self._conn() as con:
            entry = con.execute(
                "SELECT entry_price FROM trades WHERE id=?", (trade_id,)
            ).fetchone()
            unrealized = price / entry["entry_price"] - 1.0
            con.execute(
                """INSERT INTO price_snapshots
                   (trade_id, snapshot_date, price, unrealized_pnl_pct, risk_flag, note)
                   VALUES (?,?,?,?,?,?)""",
                (trade_id, snapshot_date, price, unrealized, risk_flag, note),
            )

    # ---------- reads ----------

    def list_open(self) -> list[sqlite3.Row]:
        with self._conn() as con:
            return list(con.execute(
                "SELECT * FROM trades WHERE exit_date IS NULL ORDER BY entry_date"
            ))

    def list_closed(self) -> list[sqlite3.Row]:
        with self._conn() as con:
            return list(con.execute(
                "SELECT * FROM trades WHERE exit_date IS NOT NULL ORDER BY exit_date DESC"
            ))

    def attribution(self) -> dict[str, float]:
        """已平仓交易的简单归因汇总 (胜率, 平均盈亏比, 平均持有期)."""
        with self._conn() as con:
            rows = list(con.execute(
                "SELECT pnl_pct, hold_days FROM trades WHERE exit_date IS NOT NULL"
            ))
        if not rows:
            return {"trade_count": 0}

        wins = [r["pnl_pct"] for r in rows if r["pnl_pct"] > 0]
        losses = [r["pnl_pct"] for r in rows if r["pnl_pct"] <= 0]
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0

        return {
            "trade_count": len(rows),
            "win_rate": len(wins) / len(rows),
            "avg_win_pct": avg_win,
            "avg_loss_pct": avg_loss,
            "win_loss_ratio": abs(avg_win / avg_loss) if avg_loss else float("inf"),
            "avg_hold_days": sum(r["hold_days"] for r in rows) / len(rows),
        }
