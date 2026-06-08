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


def _open(j, symbol="601939", entry_date="2026-05-22", price=10.0, size=100,
          market="a_share", strategy=None):
    return j.open_trade(TradeOpen(
        symbol=symbol, market=market, strategy=strategy, entry_date=entry_date,
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


def test_list_open_filters_by_market_and_strategy(journal: Journal):
    """风控隔离：HK/mean_reversion 的 run 不应看到 a_share momentum 的仓位。"""
    _open(journal, symbol="601939", market="a_share", strategy="equity_momentum")
    _open(journal, symbol="00700", market="hk_share", strategy="equity_hk_momentum")

    assert {t["symbol"] for t in journal.list_open()} == {"601939", "00700"}
    a_mom = journal.list_open(market="a_share", strategy="equity_momentum")
    assert {t["symbol"] for t in a_mom} == {"601939"}
    # HK run 只看 HK；A 股 mean_reversion run 看不到 momentum 的仓
    assert {t["symbol"] for t in journal.list_open(market="hk_share")} == {"00700"}
    assert journal.list_open(market="a_share", strategy="mean_reversion") == []


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


def test_close_trade_accepts_long_exit_reason(journal: Journal):
    """schema_fix_exit_reason: 06-05 实盘 trailing_stop reason 42 char 撞 VARCHAR(32) 上限挂掉。
    现 exit_reason 列 VARCHAR(255), 至少容 50 char 完整 reason。
    """
    tid = _open(journal, price=24.0, size=100)
    long_reason = "trailing_stop: close=24.54 <= stop=24.55"  # 实盘 42 char 原文
    journal.close_trade(tid, exit_date="2026-06-05", exit_price=24.54, exit_reason=long_reason)
    closed = journal.list_closed()
    assert len(closed) == 1
    assert closed[0]["exit_reason"] == long_reason


def test_open_trade_persists_entry_features(journal: Journal):
    """L2 of self_learning_pipeline: entry_features dict round-trip via TradeOpen."""
    entry_feats = {
        "rsi": 65.3,
        "vol_ratio": 1.37,
        "ma_short": 5.84,
        "ma_long": 5.73,
        "ma_short_above_long": True,
        "atr": 0.18,
        "close": 6.05,
        "dist_to_20d_high_pct": -0.012,
        "price_position_20d": 0.78,
        "strategy": "equity_momentum",
        "market": "a_share",
        "asof": "2026-06-08",
        "sector_sw1": None,
        "zscore_within_universe": 0.318,
    }
    tid = journal.open_trade(TradeOpen(
        symbol="601988", market="a_share", strategy="equity_momentum",
        entry_date="2026-06-08", entry_price=6.05, entry_size=33000,
        entry_score=0.318, stop_loss_price=5.87, take_profit_price=6.42,
        reason_timing="趋势 OK", entry_features=entry_feats,
    ))
    rows = journal.list_open()
    assert len(rows) == 1
    r = rows[0]
    assert r["id"] == tid
    assert r["entry_features"] == entry_feats
    assert r["entry_features"]["rsi"] == pytest.approx(65.3)
    assert r["entry_features"]["ma_short_above_long"] is True


def test_open_trade_default_entry_features_none(journal: Journal):
    """既有调用方不传 entry_features → DB NULL，行为零变化 (Backstop #5)。"""
    tid = _open(journal)
    row = journal.list_open()[0]
    assert row["id"] == tid
    assert row["entry_features"] is None
    assert row["exit_features"] is None


def test_close_trade_writes_exit_features(journal: Journal):
    """L4 of self_learning_pipeline: close_trade 内部采集 exit_features.

    调用方 (RiskMonitor) 零改动 — close_trade 自己查 snapshots 算 max DD/profit
    + 用 exit_layer_from_reason 解析 exit_type + 桶化 hold_days.
    """
    tid = _open(journal, price=10.0, size=100)  # entry_date=2026-05-22
    # 模拟持仓期间 4 个 snapshot
    journal.add_snapshot(tid, "2026-05-23", price=10.5)  # +5%
    journal.add_snapshot(tid, "2026-05-24", price=9.6)   # -4% (min)
    journal.add_snapshot(tid, "2026-05-25", price=11.2)  # +12% (max)
    journal.add_snapshot(tid, "2026-05-29", price=10.0)  # 0
    journal.close_trade(tid, exit_date="2026-05-30", exit_price=9.8,
                        exit_reason="trailing_stop: close=9.8 <= stop=9.9")
    closed = journal.list_closed()
    assert len(closed) == 1
    r = closed[0]
    assert r["hold_days"] == 8  # 2026-05-30 - 2026-05-22
    ef = r["exit_features"]
    assert ef is not None
    assert ef["exit_type"] == "STOP_TRAIL"
    assert ef["hold_days_bucket"] == "6-20"
    # max DD = min(+0.05, -0.04, +0.12, 0) = -0.04
    assert ef["max_drawdown_during_hold_pct"] == pytest.approx(-0.04)
    # max profit = max(...) = +0.12
    assert ef["max_profit_during_hold_pct"] == pytest.approx(0.12)
    assert ef["asof"] == "2026-05-30"


def test_close_trade_exit_features_no_snapshots(journal: Journal):
    """无 snapshots 时 exit_features 仍写入 (max DD/profit = None, fail-soft)."""
    tid = _open(journal, price=10.0)
    journal.close_trade(tid, exit_date="2026-05-30", exit_price=11.0,
                        exit_reason="take_profit: close=11.0 >= target=11.0")
    r = journal.list_closed()[0]
    ef = r["exit_features"]
    assert ef is not None
    assert ef["exit_type"] == "TAKE_PROFIT"
    assert ef["max_drawdown_during_hold_pct"] is None
    assert ef["max_profit_during_hold_pct"] is None


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
