"""zhuang 庄股策略交易 ledger（Postgres 后端）。

与 equity_factor 的 Journal 同构，但作用于独立的 zhuang_trades / zhuang_snapshots —
zhuang 出场逻辑（ATR/动量早止/10% 止盈/派发）与 equity 不同，故 ledger 完全隔离，
不会被 equity 的 RiskMonitor 用错误规则评估。

公开 API 与 equity Journal 对齐：list_open/list_closed 返回 dict（日期转字符串）。
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterator, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_system.db.models import Base, ZhuangSnapshot, ZhuangTrade
from quant_system.db.session import get_engine, get_sessionmaker


@dataclass
class TradeOpen:
    code: str
    entry_date: str
    entry_price: float
    entry_size: int
    market: str = "a_share"
    accumulation_score: Optional[float] = None
    phase: str = "A"
    atr_at_entry: Optional[float] = None
    entry_reason: Optional[str] = None
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    notes: Optional[str] = None
    # L3 of self_learning_pipeline: snapshot 入场时已算好的 5 维 accumulation 分量
    # + 附属 context. 默认 None — 既有 daily 路径不传时 DB NULL, 行为零变化 (Backstop #5)
    entry_features: Optional[dict] = None


def _to_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _zhuang_exit_layer(reason: str) -> str:
    """L4 of self_learning_pipeline: zhuang exit reason → 子类枚举。

    zhuang signals/exit.py 现有 reason 前缀: trailing_stop / momentum_stop /
    time_stop / take_profit / distribution. 与 equity exit_layer_from_reason
    同款 prefix-match 思路 — 不引入新分类逻辑 (Backstop #5)。
    """
    r = (reason or "").strip().lower()
    if r.startswith("trailing_stop"):
        return "STOP_TRAIL"
    if r.startswith("momentum_stop"):
        return "MOMENTUM_STOP"
    if r.startswith("time_stop"):
        return "TIME_STOP"
    if r.startswith("take_profit"):
        return "TAKE_PROFIT"
    if r.startswith("distribution"):
        return "DISTRIBUTION"
    if r in ("持有", "hold", ""):
        return ""
    return "OTHER"


def _trade_row(t: ZhuangTrade) -> dict[str, Any]:
    return {
        "id": t.id,
        "code": t.code,
        "market": t.market,
        "direction": t.direction,
        "entry_date": str(t.entry_date) if t.entry_date else None,
        "entry_price": t.entry_price,
        "entry_size": t.entry_size,
        "accumulation_score": t.accumulation_score,
        "phase": t.phase,
        "atr_at_entry": t.atr_at_entry,
        "entry_reason": t.entry_reason,
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
    }


class ZhuangJournal:
    def __init__(self, db_path: Any = None, *, sessionmaker=None):
        # db_path 仅为兼容旧式签名；sessionmaker 供单测注入内存库。
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
        """确保 zhuang 表存在（生产由 Alembic 建好，此处幂等兜底/供测试）。"""
        maker = self._sm or get_sessionmaker()
        engine = maker.kw.get("bind") or get_engine()
        Base.metadata.create_all(
            engine,
            tables=[ZhuangTrade.__table__, ZhuangSnapshot.__table__],
            checkfirst=True,
        )

    # ---------- writes ----------

    def open_trade(self, t: TradeOpen) -> int:
        with self._scope() as s:
            trade = ZhuangTrade(
                code=t.code,
                market=t.market,
                direction="long",
                entry_date=_to_date(t.entry_date),
                entry_price=t.entry_price,
                entry_size=t.entry_size,
                accumulation_score=t.accumulation_score,
                phase=t.phase,
                atr_at_entry=t.atr_at_entry,
                entry_reason=t.entry_reason,
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
            trade = s.get(ZhuangTrade, trade_id)
            if trade is None:
                raise ValueError(f"zhuang trade {trade_id} 不存在")
            exit_d = _to_date(exit_date)
            trade.exit_date = exit_d
            trade.exit_price = exit_price
            trade.exit_reason = exit_reason
            trade.pnl = (exit_price - trade.entry_price) * trade.entry_size
            trade.pnl_pct = exit_price / trade.entry_price - 1.0
            trade.hold_days = (exit_d - trade.entry_date).days
            # L4 of self_learning_pipeline: 内部采集 exit_features (fail-soft)
            try:
                snaps = s.scalars(
                    select(ZhuangSnapshot).where(ZhuangSnapshot.trade_id == trade_id)
                ).all()
                pnls = [sn.unrealized_pnl_pct for sn in snaps if sn.unrealized_pnl_pct is not None]
                max_dd = min(pnls) if pnls else None
                max_profit = max(pnls) if pnls else None
                hd = trade.hold_days or 0
                bucket = "0-5" if hd <= 5 else "6-20" if hd <= 20 else "21-60" if hd <= 60 else "60+"
                trade.exit_features = {
                    "exit_type": _zhuang_exit_layer(exit_reason),
                    "hold_days_bucket": bucket,
                    "max_drawdown_during_hold_pct": max_dd,
                    "max_profit_during_hold_pct": max_profit,
                    "asof": str(exit_d) if exit_d else None,
                }
            except Exception:
                pass  # fail-soft: close_trade 主行为不受影响

    def update_stop_loss(self, trade_id: int, new_stop: float) -> None:
        with self._scope() as s:
            trade = s.get(ZhuangTrade, trade_id)
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
            trade = s.get(ZhuangTrade, trade_id)
            unrealized = price / trade.entry_price - 1.0 if trade else None
            existing = s.scalars(
                select(ZhuangSnapshot).where(
                    ZhuangSnapshot.trade_id == trade_id,
                    ZhuangSnapshot.snapshot_date == snap_date,
                )
            ).first()
            if existing is not None:
                existing.price = price
                existing.unrealized_pnl_pct = unrealized
                existing.risk_flag = risk_flag
                existing.note = note
            else:
                s.add(ZhuangSnapshot(
                    trade_id=trade_id,
                    snapshot_date=snap_date,
                    price=price,
                    unrealized_pnl_pct=unrealized,
                    risk_flag=risk_flag,
                    note=note,
                ))

    # ---------- reads ----------

    def list_open(self) -> list[dict[str, Any]]:
        with self._scope() as s:
            rows = s.scalars(
                select(ZhuangTrade)
                .where(ZhuangTrade.exit_date.is_(None))
                .order_by(ZhuangTrade.entry_date)
            ).all()
            return [_trade_row(t) for t in rows]

    def list_closed(self) -> list[dict[str, Any]]:
        with self._scope() as s:
            rows = s.scalars(
                select(ZhuangTrade)
                .where(ZhuangTrade.exit_date.is_not(None))
                .order_by(ZhuangTrade.exit_date.desc())
            ).all()
            return [_trade_row(t) for t in rows]
