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
    strategy: Optional[str] = None
    entry_score: Optional[float] = None
    reason_topdown: Optional[str] = None
    reason_bottomup: Optional[str] = None
    reason_catalyst: Optional[str] = None
    reason_timing: Optional[str] = None
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    notes: Optional[str] = None
    # L2 of self_learning_pipeline: snapshot 入场时已算好的结构化特征
    # 默认 None — 既有 daily 路径不传时 DB NULL, 行为零变化 (Backstop #5)
    entry_features: Optional[dict] = None


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
        "strategy": t.strategy,
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
        "entry_features": t.entry_features,
        "exit_features": t.exit_features,
        "pending_exit_date": str(t.pending_exit_date) if t.pending_exit_date else None,
        "pending_exit_reason": t.pending_exit_reason,
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
                strategy=t.strategy,
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
                entry_features=t.entry_features,
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
            # L4 of self_learning_pipeline: 内部采集 exit_features (fail-soft)
            # 调用方零改动 — Journal own snapshots 表, 自家算 max DD/profit 最自然
            try:
                from quant_system.strategies.equity_factor.timing.exit_taxonomy import exit_layer_from_reason
                snaps = s.scalars(
                    select(JournalSnapshot).where(JournalSnapshot.trade_id == trade_id)
                ).all()
                pnls = [sn.unrealized_pnl_pct for sn in snaps if sn.unrealized_pnl_pct is not None]
                max_dd = min(pnls) if pnls else None
                max_profit = max(pnls) if pnls else None
                hd = trade.hold_days or 0
                bucket = "0-5" if hd <= 5 else "6-20" if hd <= 20 else "21-60" if hd <= 60 else "60+"
                trade.exit_features = {
                    "exit_type": exit_layer_from_reason(exit_reason),
                    "hold_days_bucket": bucket,
                    "max_drawdown_during_hold_pct": max_dd,
                    "max_profit_during_hold_pct": max_profit,
                    "asof": str(exit_d) if exit_d else None,
                }
            except Exception:
                pass  # fail-soft: close_trade 主行为不受影响
            # T+1 pending exit: execution 完成, 清 pending 状态
            trade.pending_exit_date = None
            trade.pending_exit_reason = None

    def update_exit_features(
        self, trade_id: int, patch: dict[str, Any],
    ) -> None:
        """合并 patch 进 exit_features JSONB (浅合并, 不删除既有 key).

        PR11 (2026-06-17) — CB sleeve close_cb_trade 用本 API 在 close_trade 写完
        equity-flavor exit_features 后, 补 CB 特有字段 (cb_exit_type / pnl_yuan / ...).
        equity 调用方一般不需要 (close_trade 已写 equity 字段); 仅在 self_learning
        backfill 等场景调用.
        """
        with self._scope() as s:
            trade = s.get(JournalTrade, trade_id)
            if trade is None:
                raise ValueError(f"trade {trade_id} 不存在")
            features = dict(trade.exit_features or {})
            features.update(patch)
            trade.exit_features = features

    def mark_pending_exit(
        self, trade_id: int, pending_date: str, reason: str,
    ) -> None:
        """T+1 退出锁: 标记待执行退出 (D 日标 pending, D+1 日 open 执行)."""
        with self._scope() as s:
            trade = s.get(JournalTrade, trade_id)
            if trade is None:
                raise ValueError(f"trade {trade_id} 不存在")
            trade.pending_exit_date = _to_date(pending_date)
            trade.pending_exit_reason = reason

    def list_pending_exits(
        self, market: Optional[str] = None, strategy: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """返回所有已标 pending 但未 close 的 trades (按 pending_exit_date 旧→新)."""
        with self._scope() as s:
            stmt = select(JournalTrade).where(
                JournalTrade.exit_date.is_(None),
                JournalTrade.pending_exit_date.is_not(None),
            )
            if market is not None:
                stmt = stmt.where(JournalTrade.market == market)
            if strategy is not None:
                stmt = stmt.where(JournalTrade.strategy == strategy)
            rows = s.scalars(
                stmt.order_by(JournalTrade.pending_exit_date)
            ).all()
            return [_trade_row(t) for t in rows]

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
        # 同 (trade_id, snapshot_date) 幂等 upsert：当天重跑 daily 只更新不堆重复行。
        snap_date = _to_date(snapshot_date)
        with self._scope() as s:
            trade = s.get(JournalTrade, trade_id)
            unrealized = price / trade.entry_price - 1.0 if trade else None
            existing = s.scalars(
                select(JournalSnapshot).where(
                    JournalSnapshot.trade_id == trade_id,
                    JournalSnapshot.snapshot_date == snap_date,
                )
            ).first()
            if existing is not None:
                existing.price = price
                existing.unrealized_pnl_pct = unrealized
                existing.risk_flag = risk_flag
                existing.note = note
            else:
                s.add(JournalSnapshot(
                    trade_id=trade_id,
                    snapshot_date=snap_date,
                    price=price,
                    unrealized_pnl_pct=unrealized,
                    risk_flag=risk_flag,
                    note=note,
                ))

    # ---------- reads ----------

    def list_open(
        self, market: Optional[str] = None, strategy: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """未平仓交易。可选 market / strategy 过滤 —— 避免一个 run 的风控
        评估到别的市场/策略的仓位（含误自动平仓）。"""
        with self._scope() as s:
            stmt = select(JournalTrade).where(JournalTrade.exit_date.is_(None))
            if market is not None:
                stmt = stmt.where(JournalTrade.market == market)
            if strategy is not None:
                stmt = stmt.where(JournalTrade.strategy == strategy)
            rows = s.scalars(stmt.order_by(JournalTrade.entry_date)).all()
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
