"""L1 of docs/specs/self_learning_pipeline.md — entry_features / exit_features JSONB 契约.

仅基建 PR (L1): nullable + round-trip + 既有 daily 路径零 NULL pollution.
不验证 daily 写入 (L2-L4) / 不验证 retrospective 报表 (L5).

Backstop #5 (采集与 alpha 决策完全分离): 现有 open_trade / close_trade 路径不写
features, 保持 NULL — 既有 daily 行为零变化.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from quant_system.db import Base, JournalTrade
from quant_system.db.models import ZhuangTrade


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as s:
        yield s


def test_journal_trade_features_default_null(session: Session):
    """既有 daily 路径 open_trade 不传 features → NULL, 行为不变."""
    t = JournalTrade(
        symbol="601939", market="a_share", strategy="equity_momentum",
        entry_date=date(2026, 5, 22), entry_price=10.10, entry_size=19800,
    )
    session.add(t)
    session.commit()
    row = session.scalars(select(JournalTrade)).one()
    assert row.entry_features is None
    assert row.exit_features is None


def test_journal_trade_entry_features_roundtrip(session: Session):
    """L2 将传入这种 dict — 验 round-trip + nested struct 不丢."""
    features = {
        "rsi": 65.3,
        "vol_ratio": 1.37,
        "ma20_above_ma60": True,
        "dist_to_20d_high_pct": -0.012,
        "zscore_within_universe": 0.318,
        "sector_sw1": "银行",
        "market_gate_on": True,
        "asof": "2026-06-08",
    }
    t = JournalTrade(
        symbol="601988", market="a_share", strategy="equity_momentum",
        entry_date=date(2026, 6, 8), entry_price=6.05, entry_size=33000,
        entry_features=features,
    )
    session.add(t)
    session.commit()
    row = session.scalars(select(JournalTrade)).one()
    assert row.entry_features == features
    # 类型保真
    assert row.entry_features["rsi"] == pytest.approx(65.3)
    assert row.entry_features["ma20_above_ma60"] is True
    assert row.entry_features["sector_sw1"] == "银行"


def test_journal_trade_exit_features_roundtrip(session: Session):
    """L4 将传入 exit_features — 同款 round-trip."""
    exit_feats = {
        "exit_type": "trailing_stop",
        "hold_days_bucket": "6-20",
        "max_drawdown_during_hold_pct": -0.025,
        "max_profit_during_hold_pct": 0.088,
        "asof": "2026-06-05",
    }
    t = JournalTrade(
        symbol="601066", market="a_share", strategy="equity_momentum",
        entry_date=date(2026, 5, 26), entry_price=23.72, entry_size=8400,
        exit_date=date(2026, 6, 5), exit_price=24.54,
        exit_reason="trailing_stop: close=24.54 <= stop=24.55",
        exit_features=exit_feats,
    )
    session.add(t)
    session.commit()
    row = session.scalars(select(JournalTrade)).one()
    assert row.exit_features == exit_feats
    assert row.exit_features["exit_type"] == "trailing_stop"
    assert row.exit_features["max_drawdown_during_hold_pct"] == pytest.approx(-0.025)


def test_zhuang_trade_features_roundtrip(session: Session):
    """zhuang_trades 同款基建 — 5 维 accumulation 分量 + ATR + 市值带."""
    entry = {
        "accumulation_ma_convergence": 100.0,
        "accumulation_volume_asymmetry": 11.8,
        "accumulation_price_consolidation": 0.0,
        "accumulation_turnover_decline": 97.2,
        "accumulation_vp_divergence": 94.9,
        "phase": "A",
        "atr_at_entry": 0.15,
        "market_cap_band": "50-200",
        "market_trend_on": True,
        "asof": "2026-05-28",
    }
    t = ZhuangTrade(
        code="600103", market="a_share",
        entry_date=date(2026, 5, 28), entry_price=4.58, entry_size=28400,
        accumulation_score=60.8, phase="A",
        entry_features=entry,
    )
    session.add(t)
    session.commit()
    row = session.scalars(select(ZhuangTrade)).one()
    assert row.entry_features == entry
    assert row.exit_features is None  # exit 未发生
    assert row.entry_features["accumulation_ma_convergence"] == pytest.approx(100.0)
