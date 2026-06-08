"""ZhuangJournal（Postgres 后端）单测 —— 内存 SQLite 注入 sessionmaker，不依赖 docker。

zhuang ledger 与 equity 的 journal_trades 完全隔离；本测试验证 open/close/snapshot/list_open
与 equity Journal 同构的行为契约。
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from quant_system.db.models import Base, ZhuangSnapshot, ZhuangTrade
from quant_system.strategies.zhuang.journal.journal import TradeOpen, ZhuangJournal


@pytest.fixture
def journal() -> ZhuangJournal:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return ZhuangJournal(sessionmaker=sessionmaker(bind=engine, expire_on_commit=False))


def _open(j, code="300580", entry_date="2026-05-26", price=20.0, size=500):
    return j.open_trade(TradeOpen(
        code=code, market="a_share", entry_date=entry_date,
        entry_price=price, entry_size=size, accumulation_score=78.0, phase="A",
        atr_at_entry=0.6, entry_reason="accumulation_score=78.0 >= 70",
        stop_loss_price=price * 0.94, take_profit_price=price * 1.10,
    ))


def test_open_and_list_open_returns_string_dates(journal: ZhuangJournal):
    tid = _open(journal)
    assert isinstance(tid, int)
    opens = journal.list_open()
    assert len(opens) == 1
    row = opens[0]
    assert row["code"] == "300580"
    assert row["entry_date"] == "2026-05-26"
    assert isinstance(row["entry_date"], str)
    assert row["accumulation_score"] == pytest.approx(78.0)
    assert row["atr_at_entry"] == pytest.approx(0.6)
    assert row["stop_loss_price"] == pytest.approx(20.0 * 0.94)


def test_isolated_from_equity_journal_trades(journal: ZhuangJournal):
    """zhuang 仓位只落 zhuang_trades，绝不进 equity 的 journal_trades。"""
    from quant_system.db.models import JournalTrade

    _open(journal)
    with journal._sm() as s:
        assert s.scalars(select(ZhuangTrade)).all()          # zhuang_trades 有
        assert s.scalars(select(JournalTrade)).all() == []   # journal_trades 空


def test_close_trade_computes_pnl_and_moves_to_closed(journal: ZhuangJournal):
    tid = _open(journal, price=20.0, size=500)
    journal.close_trade(tid, exit_date="2026-06-02", exit_price=22.0, exit_reason="take_profit")
    assert journal.list_open() == []
    closed = journal.list_closed()
    assert len(closed) == 1
    r = closed[0]
    assert r["pnl"] == pytest.approx((22.0 - 20.0) * 500)
    assert r["pnl_pct"] == pytest.approx(0.1)
    assert r["hold_days"] == 7
    assert r["exit_reason"] == "take_profit"


def test_add_snapshot_idempotent_per_day(journal: ZhuangJournal):
    tid = _open(journal, price=20.0)
    journal.add_snapshot(tid, "2026-05-27", price=19.6, risk_flag="normal")
    journal.add_snapshot(tid, "2026-05-27", price=19.2, risk_flag="exit")  # 同日重跑

    with journal._sm() as s:
        rows = s.scalars(
            select(ZhuangSnapshot).where(ZhuangSnapshot.trade_id == tid)
        ).all()
    assert len(rows) == 1                         # 当天只一行
    assert rows[0].price == pytest.approx(19.2)   # 被后一次覆盖
    assert rows[0].risk_flag == "exit"
    assert rows[0].unrealized_pnl_pct == pytest.approx(19.2 / 20.0 - 1.0)


def test_update_stop_loss(journal: ZhuangJournal):
    tid = _open(journal, price=20.0)
    journal.update_stop_loss(tid, 19.5)
    assert journal.list_open()[0]["stop_loss_price"] == pytest.approx(19.5)


def test_open_trade_persists_entry_features(journal: ZhuangJournal):
    """L3 of self_learning_pipeline: entry_features dict round-trip via TradeOpen."""
    entry_feats = {
        "accumulation_ma_convergence": 100.0,
        "accumulation_volume_asymmetry": 11.8,
        "accumulation_price_consolidation": 0.0,
        "accumulation_turnover_decline": 97.2,
        "accumulation_vp_divergence": 94.9,
        "accumulation_total": 60.8,
        "phase": "A",
        "atr_at_entry": 0.18,
        "entry_price": 4.58,
        "position_pct": 0.05,
        "market": "a_share",
        "market_trend_on": True,
        "asof": "2026-05-28",
        "market_cap_band": None,
        "industry_sw1": None,
    }
    tid = journal.open_trade(TradeOpen(
        code="600103", market="a_share", entry_date="2026-05-28",
        entry_price=4.58, entry_size=28400, accumulation_score=60.8, phase="A",
        atr_at_entry=0.18, entry_reason="accumulation_score=60.8 >= 45",
        stop_loss_price=4.42, take_profit_price=5.04,
        entry_features=entry_feats,
    ))
    rows = journal.list_open()
    assert len(rows) == 1
    r = rows[0]
    assert r["id"] == tid
    assert r["entry_features"] == entry_feats
    assert r["entry_features"]["accumulation_ma_convergence"] == pytest.approx(100.0)
    assert r["entry_features"]["market_trend_on"] is True


def test_open_trade_default_entry_features_none(journal: ZhuangJournal):
    """既有调用方不传 entry_features → DB NULL，行为零变化 (Backstop #5)。"""
    tid = _open(journal)
    row = journal.list_open()[0]
    assert row["id"] == tid
    assert row["entry_features"] is None
    assert row["exit_features"] is None
