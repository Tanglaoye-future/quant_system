"""Journal（Postgres 后端）单测 —— 内存 SQLite 注入 sessionmaker，不依赖 docker。

迁 Postgres 后保持旧 API：list_open/list_closed 返回 dict（entry_date 为字符串）。
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from quant_system.db.models import Base
from quant_system.strategies.equity_factor.journal.journal import Journal, TradeOpen


@pytest.fixture
def journal() -> Journal:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    j = Journal(sessionmaker=sessionmaker(bind=engine, expire_on_commit=False))
    return j


def _open(j, symbol="601939", entry_date="2026-05-22", price=10.0, size=100):
    return j.open_trade(TradeOpen(
        symbol=symbol, market="a_share", entry_date=entry_date,
        entry_price=price, entry_size=size, entry_score=8.0,
        stop_loss_price=price * 0.9, reason_timing="突破",
    ))


def test_open_and_list_open_returns_string_dates(journal: Journal):
    tid = _open(journal)
    assert isinstance(tid, int)
    opens = journal.list_open()
    assert len(opens) == 1
    row = opens[0]
    assert row["symbol"] == "601939"
    assert row["entry_date"] == "2026-05-22"
    assert isinstance(row["entry_date"], str)  # 消费者 datetime.fromisoformat 依赖字符串
    assert row["stop_loss_price"] == pytest.approx(9.0)


def test_close_trade_computes_pnl_and_moves_to_closed(journal: Journal):
    tid = _open(journal, price=10.0, size=100)
    journal.close_trade(tid, exit_date="2026-05-30", exit_price=11.0, exit_reason="target")
    assert journal.list_open() == []
    closed = journal.list_closed()
    assert len(closed) == 1
    r = closed[0]
    assert r["pnl"] == pytest.approx((11.0 - 10.0) * 100)
    assert r["pnl_pct"] == pytest.approx(0.1)
    assert r["hold_days"] == 8
    assert r["exit_reason"] == "target"


def test_update_stop_loss(journal: Journal):
    tid = _open(journal, price=10.0)
    journal.update_stop_loss(tid, 9.5)
    assert journal.list_open()[0]["stop_loss_price"] == pytest.approx(9.5)


def test_add_snapshot_idempotent_per_day(journal: Journal):
    from sqlalchemy import func, select

    from quant_system.db.models import JournalSnapshot

    tid = _open(journal, price=10.0)
    journal.add_snapshot(tid, "2026-05-23", price=10.5, risk_flag="normal")
    journal.add_snapshot(tid, "2026-05-23", price=10.8, risk_flag="drawdown")  # 同日重跑

    with journal._sm() as s:
        rows = s.scalars(
            select(JournalSnapshot).where(JournalSnapshot.trade_id == tid)
        ).all()
    assert len(rows) == 1                      # 当天只一行，不堆重复
    assert rows[0].price == pytest.approx(10.8)  # 被后一次更新
    assert rows[0].risk_flag == "drawdown"
    # 不影响 trade 读取
    assert journal.list_open()[0]["id"] == tid


def test_attribution_summary(journal: Journal):
    assert journal.attribution() == {"trade_count": 0}
    a = _open(journal, symbol="A", price=10.0, size=100)
    b = _open(journal, symbol="B", price=20.0, size=100)
    journal.close_trade(a, "2026-05-25", 11.0, "target")   # +10%
    journal.close_trade(b, "2026-05-25", 18.0, "stop")     # -10%
    attr = journal.attribution()
    assert attr["trade_count"] == 2
    assert attr["win_rate"] == pytest.approx(0.5)
    assert attr["avg_win_pct"] == pytest.approx(0.1)
    assert attr["avg_loss_pct"] == pytest.approx(-0.1)
