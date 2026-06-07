"""options_positions UPSERT + BCS aggregator 契约测试 — PR3 of docs/specs/position_v2_harness.md。

覆盖 spec §4.7 全部 7 case + BCS 聚合数学。
内存 SQLite (DB upsert) + 纯函数 (aggregator)。
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from quant_system.db import Base, OptionsPosition
from quant_system.db.ingest import upsert_options_position
from quant_system.strategies.options.engine.monitor import (
    aggregate_bull_call_spreads,
    compute_breach_alerts,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as s:
        yield s


def _upsert(session: Session, **overrides):
    defaults = dict(
        asof=date(2026, 6, 7),
        underlying="QQQ",
        spread_type="BCS",
        long_strike=480.0,
        short_strike=490.0,
        expiry=date(2026, 9, 19),
        contracts=2,
        debit_paid=4.50,
        max_profit=1100.0,
        max_loss=900.0,
        days_to_exp=104,
        current_value=5.20,
        pnl_pct=0.1556,
        breach_alerts=[],
    )
    defaults.update(overrides)
    return upsert_options_position(session, **defaults)


# ── UPSERT 契约 ──────────────────────────────────────────────────────

def test_upsert_new_spread(session: Session):
    _upsert(session)
    session.commit()
    rows = session.scalars(select(OptionsPosition)).all()
    assert len(rows) == 1
    r = rows[0]
    assert r.underlying == "QQQ"
    assert r.long_strike == 480.0 and r.short_strike == 490.0
    assert r.contracts == 2
    assert r.debit_paid == pytest.approx(4.50)
    assert r.pnl_pct == pytest.approx(0.1556)


def test_upsert_idempotent_same_strikes(session: Session):
    """同 5-tuple 第二次 UPSERT 覆盖不堆"""
    _upsert(session, current_value=5.20, pnl_pct=0.1556)
    session.commit()
    _upsert(session, current_value=5.50, pnl_pct=0.2222)
    session.commit()
    rows = session.scalars(select(OptionsPosition)).all()
    assert len(rows) == 1
    assert rows[0].current_value == pytest.approx(5.50)
    assert rows[0].pnl_pct == pytest.approx(0.2222)


def test_upsert_different_strikes_coexist(session: Session):
    """不同 strikes pair 并存"""
    _upsert(session, long_strike=480.0, short_strike=490.0)
    _upsert(session, long_strike=500.0, short_strike=510.0, debit_paid=4.0, max_profit=600, max_loss=400)
    session.commit()
    rows = session.scalars(select(OptionsPosition)).all()
    assert len(rows) == 2


# ── breach_alerts 阈值 ───────────────────────────────────────────────

def test_breach_alerts_dte_under_7():
    alerts = compute_breach_alerts(days_to_exp=5, pnl_pct=0.10)
    assert "DTE<7" in alerts
    assert "loss>50%" not in alerts


def test_breach_alerts_loss_50pct():
    alerts = compute_breach_alerts(days_to_exp=30, pnl_pct=-0.55)
    assert "loss>50%" in alerts
    assert "DTE<7" not in alerts


def test_breach_alerts_both_triggers():
    alerts = compute_breach_alerts(days_to_exp=3, pnl_pct=-0.60)
    assert set(alerts) == {"DTE<7", "loss>50%"}


def test_breach_alerts_none_when_healthy():
    assert compute_breach_alerts(days_to_exp=60, pnl_pct=0.20) == []


def test_breach_alerts_pnl_none_safe():
    """current_value 未拉到（pnl_pct=None）→ 不触 loss alert"""
    alerts = compute_breach_alerts(days_to_exp=30, pnl_pct=None)
    assert alerts == []


# ── BCS 聚合数学 ─────────────────────────────────────────────────────

def test_aggregate_basic_pair():
    """480/490 各 2 张 → 1 spread"""
    positions = [
        {"strike": 480.0, "right": "C", "position": 2, "avg_cost": 950.0, "expiry": "20260919"},
        {"strike": 490.0, "right": "C", "position": -2, "avg_cost": 500.0, "expiry": "20260919"},
    ]
    spreads = aggregate_bull_call_spreads(positions, asof=date(2026, 6, 7))
    assert len(spreads) == 1
    sp = spreads[0]
    assert sp["long_strike"] == 480.0
    assert sp["short_strike"] == 490.0
    assert sp["contracts"] == 2
    # debit_paid = (long_avg - short_avg) / 100 = (950 - 500) / 100 = 4.50 (per share)
    assert sp["debit_paid"] == pytest.approx(4.50)
    # max_profit = (490 - 480 - 4.5) × 100 = 550 per contract
    assert sp["max_profit"] == pytest.approx(550.0)
    # max_loss = 4.5 × 100 = 450 per contract
    assert sp["max_loss"] == pytest.approx(450.0)
    assert sp["expiry"] == "2026-09-19"
    assert sp["current_value"] is None  # 无 quote_lookup
    assert sp["pnl_pct"] is None


def test_aggregate_empty_legs():
    """无持仓 → 空 list"""
    assert aggregate_bull_call_spreads([], asof=date(2026, 6, 7)) == []


def test_aggregate_skips_put_legs():
    """Put leg 被忽略（只聚合 Call BCS）"""
    positions = [
        {"strike": 480.0, "right": "P", "position": 2, "avg_cost": 100.0, "expiry": "20260919"},
        {"strike": 490.0, "right": "P", "position": -2, "avg_cost": 50.0, "expiry": "20260919"},
    ]
    spreads = aggregate_bull_call_spreads(positions, asof=date(2026, 6, 7))
    assert spreads == []


def test_aggregate_skips_unmatched_legs():
    """同 expiry 只多头无空头 → 跳过"""
    positions = [
        {"strike": 480.0, "right": "C", "position": 2, "avg_cost": 950.0, "expiry": "20260919"},
    ]
    spreads = aggregate_bull_call_spreads(positions, asof=date(2026, 6, 7))
    assert spreads == []


def test_aggregate_multi_expiry():
    """两 expiry 各自配对 → 2 spreads"""
    positions = [
        {"strike": 480.0, "right": "C", "position": 1, "avg_cost": 950.0, "expiry": "20260919"},
        {"strike": 490.0, "right": "C", "position": -1, "avg_cost": 500.0, "expiry": "20260919"},
        {"strike": 500.0, "right": "C", "position": 1, "avg_cost": 800.0, "expiry": "20261219"},
        {"strike": 510.0, "right": "C", "position": -1, "avg_cost": 450.0, "expiry": "20261219"},
    ]
    spreads = aggregate_bull_call_spreads(positions, asof=date(2026, 6, 7))
    assert len(spreads) == 2
    by_exp = {s["expiry"]: s for s in spreads}
    assert "2026-09-19" in by_exp and "2026-12-19" in by_exp


def test_aggregate_with_quote_lookup():
    """提供 quote_lookup → current_value + pnl_pct 算出"""
    positions = [
        {"strike": 480.0, "right": "C", "position": 2, "avg_cost": 950.0, "expiry": "20260919"},
        {"strike": 490.0, "right": "C", "position": -2, "avg_cost": 500.0, "expiry": "20260919"},
    ]
    def quote_lookup(ls, ss, exp_str):
        # 模拟 spread mid = 5.20（高于 debit 4.50）
        return 5.20
    spreads = aggregate_bull_call_spreads(
        positions, asof=date(2026, 6, 7), spread_quote_lookup=quote_lookup
    )
    assert len(spreads) == 1
    sp = spreads[0]
    assert sp["current_value"] == pytest.approx(5.20)
    # pnl_pct = (5.20 - 4.50) / 4.50 ≈ 0.1556
    assert sp["pnl_pct"] == pytest.approx(0.1556, abs=1e-3)


def test_aggregate_attaches_breach_alerts():
    """short DTE + 大亏 → breach_alerts 命中"""
    positions = [
        {"strike": 480.0, "right": "C", "position": 1, "avg_cost": 950.0, "expiry": "20260612"},  # 5 天后
        {"strike": 490.0, "right": "C", "position": -1, "avg_cost": 500.0, "expiry": "20260612"},
    ]
    def quote_lookup(*_): return 1.50  # 巨亏：(1.5-4.5)/4.5 ≈ -0.67
    spreads = aggregate_bull_call_spreads(
        positions, asof=date(2026, 6, 7), spread_quote_lookup=quote_lookup
    )
    assert len(spreads) == 1
    assert "DTE<7" in spreads[0]["breach_alerts"]
    assert "loss>50%" in spreads[0]["breach_alerts"]


def test_aggregate_skips_non_bcs_structure():
    """short_strike <= long_strike → 不算 BCS，跳过"""
    positions = [
        {"strike": 490.0, "right": "C", "position": 2, "avg_cost": 500.0, "expiry": "20260919"},
        {"strike": 480.0, "right": "C", "position": -2, "avg_cost": 950.0, "expiry": "20260919"},
    ]
    spreads = aggregate_bull_call_spreads(positions, asof=date(2026, 6, 7))
    assert spreads == []
