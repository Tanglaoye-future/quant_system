"""交易日志 + 复盘归因（Postgres 后端，三层解耦：统一进运营真相源）.

每笔交易记录 4 个维度的入场理由 (自上而下 / 自下而上 / 催化剂 / 技术),
出场时记录原因, 计算 P&L, 持有期, 用于事后归因分析.

存储自 SQLite 迁到 Postgres 的 journal_trades / journal_snapshots（见 quant_system.db.models）。
公开 API 与旧版保持一致：list_open/list_closed 返回 dict（日期转字符串），消费者无需改动。
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterator, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_system.db.models import Base, JournalSnapshot, JournalTrade
from quant_system.db.session import get_engine, get_sessionmaker


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


def _to_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _trade_row(t: JournalTrade) -> dict[str, Any]:
    """ORM → 与旧 sqlite3.Row 同款 dict（日期转字符串，保持消费者兼容）。"""
    return {
        "id": t.id,
        "symbol": t.symbol,
        "market": t.market,
        "direction": t.direction,
        "entry_date": str(t.entry_date) if t.entry_date else None,
        "entry_price": t.entry_price,
        "entry_size": t.entry_size,
        "entry_score": t.entry_score,
        "reason_topdown": t.reason_topdown,
        "reason_bottomup": t.reason_bottomup,
        "reason_catalyst": t.reason_catalyst,
        "reason_timing": t.reason_timing,
        "stop_loss_price": t.stop_loss_price,
        "take_profit_price": t.take_profit_price,
        "exit_date": str(t.exit_date) if t.exit_date else None,
        "exit_price": t.exit_price,
        "exit_reason": t.exit_reason,
        "pnl": t.pnl,
        "pnl_pct": t.pnl_pct,
        "hold_days": t.hold_days,
        "notes": t.notes,
    }


class Journal:
    def __init__(self, db_path: Any = None, *, sessionmaker=None):
        # db_path 仅为兼容旧签名（迁 Postgres 后忽略）；sessionmaker 供单测注入内存库。
        self._sm = sessionmaker

    @contextmanager
    def _scope(self) -> Iterator[Session]:
        maker = self._sm or get_sessionmaker()
        session = maker()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def init_schema(self) -> None:
        """确保 journal 表存在（生产由 Alembic 建好，此处幂等兜底/供测试）。"""
        maker = self._sm or get_sessionmaker()
        engine = maker.kw.get("bind") or get_engine()
        Base.metadata.create_all(
            engine,
            tables=[JournalTrade.__table__, JournalSnapshot.__table__],
            checkfirst=True,
        )

    # ---------- writes ----------

    def open_trade(self, t: TradeOpen) -> int:
        with self._scope() as s:
            trade = JournalTrade(
                symbol=t.symbol,
                market=t.market,
                direction="long",
                entry_date=_to_date(t.entry_date),
                entry_price=t.entry_price,
                entry_size=t.entry_size,
                entry_score=t.entry_score,
                reason_topdown=t.reason_topdown,
                reason_bottomup=t.reason_bottomup,
                reason_catalyst=t.reason_catalyst,
                reason_timing=t.reason_timing,
                stop_loss_price=t.stop_loss_price,
                take_profit_price=t.take_profit_price,
                notes=t.notes,
            )
            s.add(trade)
            s.flush()
            return int(trade.id)

    def close_trade(
        self, trade_id: int, exit_date: str, exit_price: float, exit_reason: str
    ) -> None:
        with self._scope() as s:
            trade = s.get(JournalTrade, trade_id)
            if trade is None:
                raise ValueError(f"trade {trade_id} 不存在")
            exit_d = _to_date(exit_date)
            trade.exit_date = exit_d
            trade.exit_price = exit_price
            trade.exit_reason = exit_reason
            trade.pnl = (exit_price - trade.entry_price) * trade.entry_size
            trade.pnl_pct = exit_price / trade.entry_price - 1.0
            trade.hold_days = (exit_d - trade.entry_date).days

    def update_stop_loss(self, trade_id: int, new_stop: float) -> None:
        with self._scope() as s:
            trade = s.get(JournalTrade, trade_id)
            if trade is not None:
                trade.stop_loss_price = new_stop

    def add_snapshot(
        self,
        trade_id: int,
        snapshot_date: str,
        price: float,
        risk_flag: str = "normal",
        note: Optional[str] = None,
    ) -> None:
        with self._scope() as s:
            trade = s.get(JournalTrade, trade_id)
            unrealized = price / trade.entry_price - 1.0 if trade else None
            s.add(JournalSnapshot(
                trade_id=trade_id,
                snapshot_date=_to_date(snapshot_date),
                price=price,
                unrealized_pnl_pct=unrealized,
                risk_flag=risk_flag,
                note=note,
            ))

    # ---------- reads ----------

    def list_open(self) -> list[dict[str, Any]]:
        with self._scope() as s:
            rows = s.scalars(
                select(JournalTrade)
                .where(JournalTrade.exit_date.is_(None))
                .order_by(JournalTrade.entry_date)
            ).all()
            return [_trade_row(t) for t in rows]

    def list_closed(self) -> list[dict[str, Any]]:
        with self._scope() as s:
            rows = s.scalars(
                select(JournalTrade)
                .where(JournalTrade.exit_date.is_not(None))
                .order_by(JournalTrade.exit_date.desc())
            ).all()
            return [_trade_row(t) for t in rows]

    def attribution(self) -> dict[str, float]:
        """已平仓交易的简单归因汇总 (胜率, 平均盈亏比, 平均持有期)."""
        with self._scope() as s:
            rows = s.scalars(
                select(JournalTrade).where(JournalTrade.exit_date.is_not(None))
            ).all()
            data = [(t.pnl_pct, t.hold_days) for t in rows]
        if not data:
            return {"trade_count": 0}

        wins = [p for p, _ in data if p > 0]
        losses = [p for p, _ in data if p <= 0]
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0

        return {
            "trade_count": len(data),
            "win_rate": len(wins) / len(data),
            "avg_win_pct": avg_win,
            "avg_loss_pct": avg_loss,
            "win_loss_ratio": abs(avg_win / avg_loss) if avg_loss else float("inf"),
            "avg_hold_days": sum(h for _, h in data) / len(data),
        }
