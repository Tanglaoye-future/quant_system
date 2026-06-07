"""portfolio_history UPSERT 契约测试 — PR1 of docs/specs/position_v2_harness.md。

PR1 只验证基建（建表 + UPSERT 幂等 + 多策略/多日并存），不验证 peak DD（PR2）。
内存 SQLite，沿用 tests/db/test_ingest.py 的 fixture 风格。
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from quant_system.db import Base, PortfolioHistory
from quant_system.db.ingest import upsert_portfolio_history


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as s:
        yield s


def _upsert(session: Session, **overrides):
    """约定默认值方便 case 覆盖差异字段。"""
    defaults = dict(
        asof=date(2026, 6, 7),
        strategy_name="equity_factor",
        market="a_share",
        n_positions=4,
        cost_basis=797_000.0,
        market_value=799_400.0,
        unrealized_pnl=2_400.0,
        unrealized_pnl_pct=0.003,
    )
    defaults.update(overrides)
    return upsert_portfolio_history(session, **defaults)


def test_upsert_inserts_new_row(session: Session):
    _upsert(session)
    session.commit()
    rows = session.scalars(select(PortfolioHistory)).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.asof == date(2026, 6, 7)
    assert row.strategy_name == "equity_factor"
    assert row.market == "a_share"
    assert row.n_positions == 4
    assert row.cost_basis == pytest.approx(797_000.0)
    assert row.market_value == pytest.approx(799_400.0)
    assert row.unrealized_pnl == pytest.approx(2_400.0)
    assert row.unrealized_pnl_pct == pytest.approx(0.003)


def test_upsert_idempotent_same_asof(session: Session):
    """同 (asof, strategy_name, market) 二次写入应覆盖而非堆积。"""
    _upsert(session, market_value=799_400.0, unrealized_pnl_pct=0.003)
    session.commit()
    _upsert(session, market_value=805_100.0, unrealized_pnl_pct=0.010)
    session.commit()
    rows = session.scalars(select(PortfolioHistory)).all()
    assert len(rows) == 1
    assert rows[0].market_value == pytest.approx(805_100.0)
    assert rows[0].unrealized_pnl_pct == pytest.approx(0.010)


def test_upsert_different_strategies_coexist(session: Session):
    """equity_factor + zhuang 同日同 market 应并存（unique 三元组）。"""
    _upsert(session, strategy_name="equity_factor", market_value=799_400.0)
    _upsert(session, strategy_name="zhuang", market_value=0.0, n_positions=0,
            cost_basis=0.0, unrealized_pnl=0.0, unrealized_pnl_pct=0.0)
    session.commit()
    rows = session.scalars(select(PortfolioHistory)).all()
    assert len(rows) == 2
    by_name = {r.strategy_name: r for r in rows}
    assert by_name["equity_factor"].market_value == pytest.approx(799_400.0)
    assert by_name["zhuang"].n_positions == 0


def test_upsert_different_markets_coexist(session: Session):
    """同 strategy_name 跨市场（a_share / hk）并存。"""
    _upsert(session, strategy_name="equity_factor", market="a_share")
    _upsert(session, strategy_name="equity_factor", market="hk",
            n_positions=2, cost_basis=100_000.0, market_value=102_000.0,
            unrealized_pnl=2_000.0, unrealized_pnl_pct=0.02)
    session.commit()
    rows = session.scalars(select(PortfolioHistory)).all()
    assert len(rows) == 2
    markets = {r.market for r in rows}
    assert markets == {"a_share", "hk"}


def test_upsert_different_dates_accumulate(session: Session):
    """60 天序列 → 60 行；为 PR2 peak DD 计算提供数据。"""
    for i in range(60):
        d = date.fromordinal(date(2026, 4, 1).toordinal() + i)
        _upsert(session, asof=d, market_value=800_000.0 + i * 100.0)
    session.commit()
    rows = session.scalars(
        select(PortfolioHistory).order_by(PortfolioHistory.asof)
    ).all()
    assert len(rows) == 60
    assert rows[0].asof == date(2026, 4, 1)
    assert (rows[-1].asof.toordinal() - rows[0].asof.toordinal()) == 59
    assert rows[-1].market_value == pytest.approx(800_000.0 + 59 * 100.0)


def test_upsert_zero_positions_allowed(session: Session):
    """空仓也要落一行（PR2 peak DD 序列要连续，缺日会算错 peak）。"""
    _upsert(session, n_positions=0, cost_basis=0.0, market_value=0.0,
            unrealized_pnl=0.0, unrealized_pnl_pct=0.0)
    session.commit()
    rows = session.scalars(select(PortfolioHistory)).all()
    assert len(rows) == 1
    assert rows[0].n_positions == 0
    assert rows[0].market_value == 0.0


def test_upsert_returns_persisted_row(session: Session):
    """返回值应为入库行（PR2 写完直接拿来算 dd 不需要再查）。"""
    row = _upsert(session)
    session.commit()
    assert row.id is not None
    assert row.n_positions == 4
