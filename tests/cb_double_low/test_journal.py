"""CB 双低 sleeve journal facade 测试 (PR8, 2026-06-16).

复用 journal_trades 表 (strategy='cb_double_low', market='cb_a'), 不新建表.
验证:
  - CB 语义 helper (build_cb_entry_features / build_cb_trade_open) 正确填充字段
  - 通过 Journal 写 CB 行 → list_open(market=cb_a, strategy=cb_double_low) 拿到
  - RiskMonitor strategy filter 隔离: equity_factor run 拿不到 CB 仓 (避免串台用错出场规则)
  - entry_features JSONB 保留 CB 特有指标 (供 self_learning_pipeline PR12 回放)
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
    build_cb_entry_features,
    build_cb_trade_open,
)


@pytest.fixture
def journal() -> Journal:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Journal(sessionmaker=sessionmaker(bind=engine, expire_on_commit=False))


def test_build_entry_features_full_fields():
    f = build_cb_entry_features(
        rank=3,
        dual_low_score=128.42,
        close=108.50,
        conversion_premium_rate=19.92,
        scale_remain_yi=4.5,
        rating="AA",
        years_to_maturity=3.2,
        pure_bond_premium_rate=12.5,
        last_trading_date="2027-08-15",
    )
    assert f["rank_at_entry"] == 3
    assert f["dual_low_score"] == pytest.approx(128.42)
    assert f["close_at_entry"] == pytest.approx(108.50)
    assert f["conversion_premium_rate"] == pytest.approx(19.92)
    assert f["scale_remain_yi"] == pytest.approx(4.5)
    assert f["rating"] == "AA"
    assert f["years_to_maturity"] == pytest.approx(3.2)
    assert f["pure_bond_premium_rate"] == pytest.approx(12.5)
    assert f["last_trading_date"] == "2027-08-15"


def test_build_entry_features_optionals_none():
    """scale/rating/maturity/premium 可缺失 (PR3 部分债数据缺), entry_features 保留 None."""
    f = build_cb_entry_features(
        rank=1,
        dual_low_score=125.0,
        close=105.0,
        conversion_premium_rate=20.0,
    )
    assert f["scale_remain_yi"] is None
    assert f["rating"] is None
    assert f["years_to_maturity"] is None
    assert f["pure_bond_premium_rate"] is None
    assert f["last_trading_date"] is None


def test_build_trade_open_maps_cb_semantics():
    t = build_cb_trade_open(
        bond_code="113008",
        bond_name="电气转债",
        entry_date="2026-07-01",
        entry_price=108.50,
        entry_size=10,  # 10 张 = 1000 元面值
        dual_low_score=128.42,
        rank=3,
        conversion_premium_rate=19.92,
        stop_loss_close=85.0,
        scale_remain_yi=4.5,
        rating="AA",
    )
    assert t.symbol == "113008"
    assert t.market == CB_MARKET == "cb_a"
    assert t.strategy == CB_STRATEGY == "cb_double_low"
    assert t.entry_date == "2026-07-01"
    assert t.entry_price == pytest.approx(108.50)
    assert t.entry_size == 10
    # entry_score 与 dual_low_score 对齐 (与 equity 的 entry_score 字段语义平行)
    assert t.entry_score == pytest.approx(128.42)
    assert t.stop_loss_price == pytest.approx(85.0)
    # CB 出场不是固定 TP, 必须留 None
    assert t.take_profit_price is None
    # reason_bottomup 携带 CB 核心入场理由
    assert "dual_low_score=128.42" in t.reason_bottomup
    assert "rank=3" in t.reason_bottomup
    assert t.reason_timing == "monthly_rebalance"
    assert t.notes == "电气转债"
    # entry_features 完整透传
    assert t.entry_features["rank_at_entry"] == 3
    assert t.entry_features["scale_remain_yi"] == pytest.approx(4.5)
    assert t.entry_features["rating"] == "AA"


def test_open_cb_trade_then_list_open(journal: Journal):
    t = build_cb_trade_open(
        bond_code="113008",
        bond_name="电气转债",
        entry_date="2026-07-01",
        entry_price=108.50,
        entry_size=10,
        dual_low_score=128.42,
        rank=3,
        conversion_premium_rate=19.92,
    )
    tid = journal.open_trade(t)
    assert isinstance(tid, int)

    opens = journal.list_open(market=CB_MARKET, strategy=CB_STRATEGY)
    assert len(opens) == 1
    row = opens[0]
    assert row["symbol"] == "113008"
    assert row["market"] == "cb_a"
    assert row["strategy"] == "cb_double_low"
    assert row["entry_date"] == "2026-07-01"
    assert row["entry_price"] == pytest.approx(108.50)
    assert row["entry_size"] == 10
    assert row["stop_loss_price"] == pytest.approx(85.0)
    assert row["take_profit_price"] is None
    # entry_features JSONB roundtrip
    assert row["entry_features"]["dual_low_score"] == pytest.approx(128.42)
    assert row["entry_features"]["rank_at_entry"] == 3


def test_strategy_filter_isolates_cb_from_equity(journal: Journal):
    """北极星支柱 3 风控隔离: equity_factor RiskMonitor 不应看到 CB sleeve 持仓.

    journal_trades 是共享表, 通过 (market, strategy) filter 切片.
    RiskMonitor 用 a_share 出场规则 (break_ma60 / stop_loss) 评估 cb_a 仓位 = 灾难.
    """
    from quant_system.strategies.equity_factor.journal.journal import TradeOpen
    # CB 仓
    journal.open_trade(build_cb_trade_open(
        bond_code="113008", bond_name="电气转债", entry_date="2026-07-01",
        entry_price=108.5, entry_size=10, dual_low_score=128.42, rank=3,
        conversion_premium_rate=19.92,
    ))
    # equity_factor 仓
    journal.open_trade(TradeOpen(
        symbol="601939", market="a_share", strategy="equity_momentum",
        entry_date="2026-07-01", entry_price=10.0, entry_size=100,
        entry_score=8.0, stop_loss_price=9.0, reason_timing="突破",
    ))

    all_open = journal.list_open()
    assert {t["symbol"] for t in all_open} == {"113008", "601939"}

    # equity_factor RiskMonitor run 视角: 只看自己的仓
    eq_run = journal.list_open(market="a_share", strategy="equity_momentum")
    assert {t["symbol"] for t in eq_run} == {"601939"}

    # CB run 视角 (PR9+ 用): 只看自己的仓
    cb_run = journal.list_open(market=CB_MARKET, strategy=CB_STRATEGY)
    assert {t["symbol"] for t in cb_run} == {"113008"}

    # 反例: 错配 (market, strategy) 应空
    assert journal.list_open(market="a_share", strategy=CB_STRATEGY) == []
    assert journal.list_open(market=CB_MARKET, strategy="equity_momentum") == []


def test_close_cb_trade_computes_pnl(journal: Journal):
    """CB 闭合: pnl 按 (exit - entry) * size 计算 (CB 按张, 净价报价)."""
    t = build_cb_trade_open(
        bond_code="113008", bond_name="电气转债", entry_date="2026-07-01",
        entry_price=108.5, entry_size=10, dual_low_score=128.42, rank=3,
        conversion_premium_rate=19.92,
    )
    tid = journal.open_trade(t)
    # 假设 1 个月后 score 涨破 180 触发出场, exit_price=125
    journal.close_trade(tid, exit_date="2026-08-01", exit_price=125.0,
                        exit_reason="score_over_180")
    assert journal.list_open(market=CB_MARKET, strategy=CB_STRATEGY) == []
    closed = journal.list_closed()
    assert len(closed) == 1
    c = closed[0]
    assert c["symbol"] == "113008"
    assert c["exit_reason"] == "score_over_180"
    assert c["pnl"] == pytest.approx((125.0 - 108.5) * 10)
    assert c["pnl_pct"] == pytest.approx(125.0 / 108.5 - 1.0)
    assert c["hold_days"] == 31
