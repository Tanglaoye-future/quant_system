"""SQLAlchemy ORM 模型 — 三层解耦的共享契约。

设计原则：
- 规范化核心表 (strategy_runs / signals / positions) + JSONB 装策略特有字段，
  避免为 options(ivr/grade) 与 zhuang(因子分项) 堆一堆 nullable 列。
- journal_trades / journal_snapshots 从原 SQLite 平移，字段一一对应。
- 一次 daily 跑批 = 一行 strategy_run，其下挂 signals / positions。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Postgres 用 JSONB，其它方言(单测用的内存 SQLite)退化为通用 JSON —
# 让 repo 层不依赖 docker 也能单测，生产仍是 JSONB。
JSONColumn = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class StrategyRun(Base):
    """一次子策略的 daily 跑批结果（替代 report/data/*.json 顶层对象）。"""

    __tablename__ = "strategy_runs"
    __table_args__ = (
        UniqueConstraint("run_date", "strategy_name", "market", name="uq_run_date_strategy_market"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    strategy_name: Mapped[Optional[str]] = mapped_column(String(64))
    strategy_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    market: Mapped[str] = mapped_column(String(32), nullable=False)

    market_gate: Mapped[Optional[bool]] = mapped_column(Boolean)
    market_gate_msg: Mapped[Optional[str]] = mapped_column(Text)

    # 策略特有标量全进这里：ivr / signal_grade / qqq_price / universe_size /
    # candidates_count / benchmark_close / benchmark_ma60 / reason ...
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONColumn, nullable=False, default=dict)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    signals: Mapped[list["Signal"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    positions: Mapped[list["Position"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class Signal(Base):
    """买入/候选信号。zhuang 候选也落这里：score=total，因子分项进 payload。"""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("strategy_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(128))
    action: Mapped[Optional[str]] = mapped_column(String(32))
    score: Mapped[Optional[float]] = mapped_column(Float)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONColumn, nullable=False, default=dict)

    run: Mapped["StrategyRun"] = relationship(back_populates="signals")


class Position(Base):
    """当前持仓快照（每次跑批重算）。"""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("strategy_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(128))
    entry_date: Mapped[Optional[date]] = mapped_column(Date)
    hold_days: Mapped[Optional[int]] = mapped_column(Integer)
    pnl_pct: Mapped[Optional[float]] = mapped_column(Float)
    action: Mapped[Optional[str]] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONColumn, nullable=False, default=dict)

    run: Mapped["StrategyRun"] = relationship(back_populates="positions")


class JournalTrade(Base):
    """交易流水 — 从 equity_factor SQLite 'trades' 表平移。"""

    __tablename__ = "journal_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    market: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False, default="long")

    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    entry_size: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_score: Mapped[Optional[float]] = mapped_column(Float)

    reason_topdown: Mapped[Optional[str]] = mapped_column(Text)
    reason_bottomup: Mapped[Optional[str]] = mapped_column(Text)
    reason_catalyst: Mapped[Optional[str]] = mapped_column(Text)
    reason_timing: Mapped[Optional[str]] = mapped_column(Text)

    stop_loss_price: Mapped[Optional[float]] = mapped_column(Float)
    take_profit_price: Mapped[Optional[float]] = mapped_column(Float)

    exit_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    exit_price: Mapped[Optional[float]] = mapped_column(Float)
    exit_reason: Mapped[Optional[str]] = mapped_column(String(32))
    pnl: Mapped[Optional[float]] = mapped_column(Float)
    pnl_pct: Mapped[Optional[float]] = mapped_column(Float)
    hold_days: Mapped[Optional[int]] = mapped_column(Integer)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    snapshots: Mapped[list["JournalSnapshot"]] = relationship(
        back_populates="trade", cascade="all, delete-orphan"
    )


class JournalSnapshot(Base):
    """持仓盯市快照 — 从 SQLite 'price_snapshots' 表平移。"""

    __tablename__ = "journal_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(
        ForeignKey("journal_trades.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    unrealized_pnl_pct: Mapped[Optional[float]] = mapped_column(Float)
    risk_flag: Mapped[Optional[str]] = mapped_column(String(16), default="normal")
    note: Mapped[Optional[str]] = mapped_column(Text)

    trade: Mapped["JournalTrade"] = relationship(back_populates="snapshots")


class ZhuangTrade(Base):
    """zhuang 庄股策略交易流水 — 与 equity 的 journal_trades 完全隔离。

    zhuang 出场逻辑（ATR/动量早止/10% 止盈/派发）与 equity 不同，故独立 ledger，
    避免 equity 的 RiskMonitor 用错误的出场规则评估 zhuang 仓位。
    """

    __tablename__ = "zhuang_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    market: Mapped[str] = mapped_column(String(32), nullable=False, default="a_share")
    direction: Mapped[str] = mapped_column(String(8), nullable=False, default="long")

    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    entry_size: Mapped[int] = mapped_column(Integer, nullable=False)

    accumulation_score: Mapped[Optional[float]] = mapped_column(Float)
    phase: Mapped[str] = mapped_column(String(4), nullable=False, default="A")
    atr_at_entry: Mapped[Optional[float]] = mapped_column(Float)
    entry_reason: Mapped[Optional[str]] = mapped_column(Text)

    stop_loss_price: Mapped[Optional[float]] = mapped_column(Float)
    take_profit_price: Mapped[Optional[float]] = mapped_column(Float)

    exit_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    exit_price: Mapped[Optional[float]] = mapped_column(Float)
    exit_reason: Mapped[Optional[str]] = mapped_column(String(64))
    pnl: Mapped[Optional[float]] = mapped_column(Float)
    pnl_pct: Mapped[Optional[float]] = mapped_column(Float)
    hold_days: Mapped[Optional[int]] = mapped_column(Integer)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    snapshots: Mapped[list["ZhuangSnapshot"]] = relationship(
        back_populates="trade", cascade="all, delete-orphan"
    )


class ZhuangSnapshot(Base):
    """zhuang 持仓盯市快照。"""

    __tablename__ = "zhuang_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(
        ForeignKey("zhuang_trades.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    unrealized_pnl_pct: Mapped[Optional[float]] = mapped_column(Float)
    risk_flag: Mapped[Optional[str]] = mapped_column(String(16), default="normal")
    note: Mapped[Optional[str]] = mapped_column(Text)

    trade: Mapped["ZhuangTrade"] = relationship(back_populates="snapshots")
