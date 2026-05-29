"""registry DB-first 发现（_runs_to_cells）单测 —— 内存 SQLite。

验证 strategy_runs → cells 字典的归因与计数（含 zhuang/options 的 signals_count=0 特例）。
"""

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from quant_system.db import Base, Position, Signal, StrategyRun
from quant_system.report.registry import resolver


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as s:
        yield s


def _cells(session):
    runs = session.scalars(
        select(StrategyRun).order_by(StrategyRun.run_date, StrategyRun.id)
    ).all()
    return resolver._runs_to_cells(runs)


def test_quant_cell_counts_signals_and_positions(session: Session):
    run = StrategyRun(
        run_date=date(2026, 5, 29), strategy_name="equity_momentum",
        strategy_kind="bottomup_timing", market="a_share",
        market_gate=True, metrics={},
    )
    run.signals.append(Signal(code="600519", score=8.0, payload={}))
    run.positions.append(Position(code="601939", action="HOLD", payload={}))
    session.add(run)
    session.commit()

    cells = _cells(session)
    cell = cells[("equity_momentum", "a_share")]
    assert cell["date"] == "2026-05-29"
    assert cell["signals_count"] == 1
    assert cell["positions_count"] == 1
    assert cell["market_gate"] is True


def test_options_keyed_by_kind_signals_zero(session: Session):
    run = StrategyRun(
        run_date=date(2026, 5, 29), strategy_name="QQQ",
        strategy_kind="bull_call_spread", market="us_qqq",
        metrics={"ivr": 36.2, "signal_grade": "B", "qqq_price": 717.5,
                 "iv_mode": "MID_IV", "reason": "no-ibkr"},
    )
    session.add(run)
    session.commit()

    cells = _cells(session)
    # options 按 kind 归到 registry 名，signals/positions 计数为 0（JSON 无这些数组）
    cell = cells[("options_bull_call_spread", "us_qqq")]
    assert cell["signals_count"] == 0 and cell["positions_count"] == 0
    assert cell["ivr"] == 36.2 and cell["signal_grade"] == "B"


def test_zhuang_signals_zero_candidates_from_metrics(session: Session):
    run = StrategyRun(
        run_date=date(2026, 5, 29), strategy_name="zhuang",
        strategy_kind="zhuang", market="a_share",
        metrics={"universe_size": 4862, "candidates_count": 97},
    )
    run.signals.append(Signal(code="600655", score=57.0, payload={}))  # 候选, 非买入信号
    session.add(run)
    session.commit()

    cells = _cells(session)
    cell = cells[("zhuang", "a_share")]
    assert cell["signals_count"] == 0  # 候选不计入 signals_count
    assert cell["candidates_count"] == 97


def test_latest_run_per_market_kind_wins(session: Session):
    for d, code in [(date(2026, 5, 20), "OLD"), (date(2026, 5, 29), "NEW")]:
        r = StrategyRun(run_date=d, strategy_name="equity_momentum",
                        strategy_kind="bottomup_timing", market="a_share", metrics={})
        r.positions.append(Position(code=code, action="HOLD", payload={}))
        session.add(r)
    session.commit()

    cells = _cells(session)
    assert cells[("equity_momentum", "a_share")]["date"] == "2026-05-29"
