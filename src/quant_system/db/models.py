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
    strategy: Mapped[Optional[str]] = mapped_column(String(64), index=True)
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


class PortfolioHistory(Base):
    """组合层每日 equity / 持仓汇总历史 —— max_drawdown peak DD 计算的数据源。

    每个 (asof, strategy_name, market) 一行，daily 收尾 UPSERT。
    [[docs/specs/position_v2_harness.md]] §2 (PR1) — PR2 在此基础上算 peak DD。
    """

    __tablename__ = "portfolio_history"
    __table_args__ = (
        UniqueConstraint(
            "asof", "strategy_name", "market", name="uq_portfolio_history_asof_strategy_market"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asof: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    market: Mapped[str] = mapped_column(String(32), nullable=False)

    n_positions: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_basis: Mapped[float] = mapped_column(Float, nullable=False)
    market_value: Mapped[float] = mapped_column(Float, nullable=False)
    unrealized_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    unrealized_pnl_pct: Mapped[float] = mapped_column(Float, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AlertsSent(Base):
    """盘中实时告警去重表 —— PR5 of [[docs/specs/position_v2_harness.md]] §6。

    一个 (asof_date, strategy_name, symbol, alert_type) 一行；同 N 分钟 cron 跑
    多次只发一次（按 dedup unique index）；跨日重置（同事件第二天再发一次）。

    用户授权 2026-06-07：Telegram 通道 / 15 min 频率 / 4 阈值。
    """

    __tablename__ = "alerts_sent"
    __table_args__ = (
        # 按当日去重：同 strategy/symbol/alert_type 在 asof_date 只发一次
        UniqueConstraint(
            "asof_date", "strategy_name", "symbol", "alert_type",
            name="uq_alerts_sent_dedup",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # asof_ts: 实际触发时间（精确秒）；asof_date: 用于去重的 date 投影（避免 PG 函数索引）
    asof_ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    asof_date: Mapped[date] = mapped_column(Date, nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[Optional[str]] = mapped_column(String(32))  # 个股 alert 有，组合层 None
    alert_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # 推送内容（含价 / dist_to_stop_pct / message body 全 JSONB）；便于事后回放
    payload: Mapped[dict[str, Any]] = mapped_column(JSONColumn, nullable=False, default=dict)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)  # "telegram" / "macos" / ...
    delivered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OptionsPosition(Base):
    """options BCS spread 持仓快照 —— stock 持仓 schema 对不上，独立表。

    每个 (asof, underlying, long_strike, short_strike, expiry) 一行；
    daily_options.py 收尾从 IBKR 拉到 spread 后 UPSERT；breach_alerts JSONB
    放 ["DTE<7", "loss>50%", ...]。[[docs/specs/position_v2_harness.md]] §4 (PR3)。
    """

    __tablename__ = "options_positions"
    __table_args__ = (
        UniqueConstraint(
            "asof", "underlying", "long_strike", "short_strike", "expiry",
            name="uq_options_positions_asof_underlying_strikes_expiry",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asof: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    underlying: Mapped[str] = mapped_column(String(16), nullable=False)
    spread_type: Mapped[str] = mapped_column(String(16), nullable=False)

    long_strike: Mapped[float] = mapped_column(Float, nullable=False)
    short_strike: Mapped[float] = mapped_column(Float, nullable=False)
    expiry: Mapped[date] = mapped_column(Date, nullable=False)
    contracts: Mapped[int] = mapped_column(Integer, nullable=False)

    debit_paid: Mapped[float] = mapped_column(Float, nullable=False)
    max_profit: Mapped[float] = mapped_column(Float, nullable=False)
    max_loss: Mapped[float] = mapped_column(Float, nullable=False)
    current_value: Mapped[Optional[float]] = mapped_column(Float)
    days_to_exp: Mapped[int] = mapped_column(Integer, nullable=False)
    pnl_pct: Mapped[Optional[float]] = mapped_column(Float)

    # 触发的告警列表（DTE<7 / loss>50% / ...）；空 list 与 None 都允许
    breach_alerts: Mapped[Optional[list[str]]] = mapped_column(JSONColumn)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
