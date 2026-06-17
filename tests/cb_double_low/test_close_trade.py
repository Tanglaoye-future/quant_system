"""PR11 — CB close_cb_trade + update_exit_features 集成测试 (2026-06-17).

验证 close_cb_trade 在 journal.close_trade 之上正确补齐 CB 特有 exit_features:
  - cb_exit_type (CB taxonomy)
  - pnl_yuan (CB 按张, pnl 单位是元)
  - exit_price / exit_reason_raw (冗余存储, 供 PR12 self_learning 直接读)
  - equity-flavor 字段保留 (max_dd / max_profit / hold_days_bucket / asof)
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from quant_system.db.models import Base
from quant_system.strategies.cb_double_low.journal import (
    CB_MARKET,
    CB_STRATEGY,
    Journal,
    build_cb_trade_open,
    close_cb_trade,
    list_closed_cb_trades,
    list_open_cb_holdings,
)
from quant_system.strategies.cb_double_low.journal.exit_taxonomy import (
    CB_LAYER_FORCE_REDEEM,
    CB_LAYER_REBALANCE,
    CB_LAYER_SCORE_EXIT,
    CB_LAYER_STOP_LOSS,
)


@pytest.fixture
def journal() -> Journal:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Journal(sessionmaker=sessionmaker(bind=engine, expire_on_commit=False))


def _open_cb(j: Journal, code: str = "113008") -> int:
    """开仓 helper: 7/1 入场, 净价 108, 10 张."""
    return j.open_trade(build_cb_trade_open(
        bond_code=code, bond_name="电气转债", entry_date="2026-07-01",
        entry_price=108.0, entry_size=10, dual_low_score=128.0, rank=3,
        conversion_premium_rate=20.0, scale_remain_yi=4.5, rating="AA",
    ))


def test_close_cb_trade_writes_cb_layer_and_pnl_yuan(journal: Journal):
    """8/1 score 越线出场, 净价 125 → cb_exit_type=SCORE_EXIT, pnl=170 元 (entry_size=10 × (125-108))."""
    tid = _open_cb(journal)
    close_cb_trade(journal, tid, exit_date="2026-08-01", exit_price=125.0,
                   exit_reason="score_over_180")

    closed = list_closed_cb_trades(journal)
    assert len(closed) == 1
    t = closed[0]
    assert t["exit_reason"] == "score_over_180"
    assert t["pnl"] == pytest.approx((125.0 - 108.0) * 10)
    assert t["hold_days"] == 31

    features = t["exit_features"]
    # CB-specific fields
    assert features["cb_exit_type"] == CB_LAYER_SCORE_EXIT
    assert features["pnl_yuan"] == pytest.approx(170.0)
    assert features["exit_price"] == 125.0
    assert features["exit_reason_raw"] == "score_over_180"
    # equity-flavor fields 保留 (update_exit_features 浅合并不删除)
    assert "exit_type" in features  # equity exit_type=OTHER (CB reason 不在 equity taxonomy)
    assert "hold_days_bucket" in features
    assert features["hold_days_bucket"] == "21-60"  # 31 days falls in 21-60 bucket
    assert "asof" in features


def test_close_cb_trade_stop_loss_layer(journal: Journal):
    """close 暴跌至 70 (债底击穿) → cb_exit_type=STOP_LOSS, pnl 负."""
    tid = _open_cb(journal)
    close_cb_trade(journal, tid, exit_date="2026-07-15", exit_price=70.0,
                   exit_reason="stop_loss")
    closed = list_closed_cb_trades(journal)
    t = closed[0]
    assert t["exit_features"]["cb_exit_type"] == CB_LAYER_STOP_LOSS
    assert t["pnl"] < 0
    assert t["exit_features"]["pnl_yuan"] == pytest.approx((70.0 - 108.0) * 10)


def test_close_cb_trade_force_redeem_layer(journal: Journal):
    """强赎执行 ~ 净价 100 → cb_exit_type=FORCE_REDEEM."""
    tid = _open_cb(journal)
    close_cb_trade(journal, tid, exit_date="2026-07-15", exit_price=100.0,
                   exit_reason="redeem_announced")
    t = list_closed_cb_trades(journal)[0]
    assert t["exit_features"]["cb_exit_type"] == CB_LAYER_FORCE_REDEEM


def test_close_cb_trade_rebalance_layer(journal: Journal):
    """月度 rank 漂移出场 → cb_exit_type=REBALANCE."""
    tid = _open_cb(journal)
    close_cb_trade(journal, tid, exit_date="2026-08-01", exit_price=112.0,
                   exit_reason="out_of_top_band")
    t = list_closed_cb_trades(journal)[0]
    assert t["exit_features"]["cb_exit_type"] == CB_LAYER_REBALANCE


def test_close_cb_trade_moves_from_open_to_closed(journal: Journal):
    """close 后 list_open_cb_holdings 空, list_closed_cb_trades 有一行."""
    tid = _open_cb(journal, "113008")
    assert list_open_cb_holdings(journal) == ["113008"]
    close_cb_trade(journal, tid, exit_date="2026-08-01", exit_price=125.0,
                   exit_reason="score_over_180")
    assert list_open_cb_holdings(journal) == []
    closed = list_closed_cb_trades(journal)
    assert len(closed) == 1
    assert closed[0]["symbol"] == "113008"


def test_list_closed_cb_trades_filters_by_strategy(journal: Journal):
    """list_closed_cb_trades 不应混回 equity closed (PR8 strategy filter 隔离)."""
    # CB closed
    tid_cb = _open_cb(journal, "113008")
    close_cb_trade(journal, tid_cb, exit_date="2026-08-01", exit_price=125.0,
                   exit_reason="score_over_180")
    # equity closed (强行模拟一笔已平仓 equity 行)
    from quant_system.strategies.equity_factor.journal.journal import TradeOpen
    tid_eq = journal.open_trade(TradeOpen(
        symbol="601939", market="a_share", strategy="equity_momentum",
        entry_date="2026-07-01", entry_price=10.0, entry_size=100,
        stop_loss_price=9.0,
    ))
    journal.close_trade(tid_eq, exit_date="2026-08-01", exit_price=11.0,
                        exit_reason="take_profit")

    cb_closed = list_closed_cb_trades(journal)
    assert {t["symbol"] for t in cb_closed} == {"113008"}
    # equity row 完全不混回
    assert all(t["strategy"] == CB_STRATEGY and t["market"] == CB_MARKET
               for t in cb_closed)


def test_update_exit_features_shallow_merge(journal: Journal):
    """update_exit_features 不删除既有 key (浅合并)."""
    tid = _open_cb(journal)
    journal.close_trade(tid, exit_date="2026-08-01", exit_price=125.0,
                        exit_reason="score_over_180")
    # close_trade 写了 equity-flavor exit_features
    # 现在直接调 update_exit_features patch
    journal.update_exit_features(tid, {"cb_exit_type": "SCORE_EXIT",
                                       "extra_field": "from_pr12"})
    closed = list_closed_cb_trades(journal)
    features = closed[0]["exit_features"]
    # patch 字段加入
    assert features["cb_exit_type"] == "SCORE_EXIT"
    assert features["extra_field"] == "from_pr12"
    # equity 字段保留
    assert "exit_type" in features
    assert "hold_days_bucket" in features


def test_close_cb_trade_invalid_trade_id_raises(journal: Journal):
    with pytest.raises(ValueError):
        close_cb_trade(journal, 999999, "2026-08-01", 100.0, "score_over_180")
