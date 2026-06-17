"""CB 双低 sleeve portfolio_history UPSERT 测试 (PR8, 2026-06-16).

复用统一表 portfolio_history (含 strategy_name + market UNIQUE), 与 equity_factor 同表族.
验证:
  - CB sleeve UPSERT 用 strategy_name='cb_double_low' / market='cb_a' 命名空间
  - 同日重跑幂等 (advisory daily 日内多次重跑不堆历史)
  - advisory_only 期空持仓 (n=0/cost=0/mv=0) 也成行, 保证 PR9+ 接通后净值曲线连续
  - 与 equity_factor 行隔离 (按 (asof, strategy_name, market) UNIQUE)
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from quant_system.db import Base, PortfolioHistory
from quant_system.db.ingest import upsert_portfolio_history
from quant_system.strategies.cb_double_low.journal import CB_MARKET, CB_STRATEGY


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as s:
        yield s


def _upsert_cb_empty(session: Session, asof: date = date(2026, 6, 17)) -> PortfolioHistory:
    """advisory_only 期默认调用: 空持仓行."""
    return upsert_portfolio_history(
        session,
        asof=asof,
        strategy_name=CB_STRATEGY,
        market=CB_MARKET,
        n_positions=0,
        cost_basis=0.0,
        market_value=0.0,
        unrealized_pnl=0.0,
        unrealized_pnl_pct=0.0,
    )


def test_cb_empty_sleeve_upserts_row(session: Session):
    _upsert_cb_empty(session)
    session.commit()
    rows = session.scalars(select(PortfolioHistory)).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.strategy_name == "cb_double_low"
    assert row.market == "cb_a"
    assert row.n_positions == 0
    assert row.cost_basis == pytest.approx(0.0)
    assert row.market_value == pytest.approx(0.0)
    assert row.unrealized_pnl == pytest.approx(0.0)
    assert row.unrealized_pnl_pct == pytest.approx(0.0)


def test_cb_upsert_idempotent_same_asof(session: Session):
    """同日 advisory daily 重跑 (用户日内手跑两次) 不应堆历史."""
    _upsert_cb_empty(session)
    session.commit()
    # 第二次跑, 比方说 PR9 月初 rebalance 后填实数
    upsert_portfolio_history(
        session,
        asof=date(2026, 6, 17),
        strategy_name=CB_STRATEGY,
        market=CB_MARKET,
        n_positions=20,
        cost_basis=50_000.0,
        market_value=51_200.0,
        unrealized_pnl=1_200.0,
        unrealized_pnl_pct=0.024,
    )
    session.commit()
    rows = session.scalars(select(PortfolioHistory)).all()
    assert len(rows) == 1
    assert rows[0].n_positions == 20
    assert rows[0].market_value == pytest.approx(51_200.0)
    assert rows[0].unrealized_pnl_pct == pytest.approx(0.024)


def test_cb_and_equity_factor_coexist_same_asof(session: Session):
    """同日 CB sleeve 和 equity_factor sleeve 是 (asof, strategy_name, market) 不同行."""
    _upsert_cb_empty(session, asof=date(2026, 6, 17))
    upsert_portfolio_history(
        session,
        asof=date(2026, 6, 17),
        strategy_name="equity_momentum",
        market="a_share",
        n_positions=4,
        cost_basis=797_000.0,
        market_value=799_400.0,
        unrealized_pnl=2_400.0,
        unrealized_pnl_pct=0.003,
    )
    session.commit()
    rows = session.scalars(
        select(PortfolioHistory).order_by(PortfolioHistory.strategy_name)
    ).all()
    assert len(rows) == 2
    names = {r.strategy_name for r in rows}
    assert names == {"cb_double_low", "equity_momentum"}
    cb = next(r for r in rows if r.strategy_name == "cb_double_low")
    eq = next(r for r in rows if r.strategy_name == "equity_momentum")
    assert cb.market == "cb_a"
    assert eq.market == "a_share"
    assert cb.n_positions == 0 and eq.n_positions == 4


def test_cb_curve_across_multiple_days(session: Session):
    """模拟 advisory 期 3 天连续 daily, 形成 (空) 净值曲线 baseline."""
    for d in [date(2026, 6, 15), date(2026, 6, 16), date(2026, 6, 17)]:
        _upsert_cb_empty(session, asof=d)
    session.commit()
    rows = session.scalars(
        select(PortfolioHistory)
        .where(PortfolioHistory.strategy_name == CB_STRATEGY)
        .order_by(PortfolioHistory.asof)
    ).all()
    assert len(rows) == 3
    assert [r.asof for r in rows] == [
        date(2026, 6, 15), date(2026, 6, 16), date(2026, 6, 17),
    ]
    # 空持仓 baseline → 所有日 MV/PnL 都是 0.0 (PR9 后才有真值)
    assert all(r.market_value == pytest.approx(0.0) for r in rows)
