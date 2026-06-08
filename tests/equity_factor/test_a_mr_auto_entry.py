"""M1 of A_mr auto-entry 闭环 — 验证 mean_reversion 不再被 daily_equity block.

Backstop #1: 不动 MeanReversionStrategy.screen() 的 alpha 逻辑;
Backstop #5: list_open(market=, strategy=) 隔离 sleeve, A_mr / A_mom 不互挤 slot.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from quant_system.db.models import Base
from quant_system.strategies.equity_factor.journal.journal import Journal, TradeOpen


@pytest.fixture
def journal() -> Journal:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Journal(sessionmaker=sessionmaker(bind=engine, expire_on_commit=False))


def _open(journal, symbol, strategy, market="a_share", price=10.0, size=100, entry_date="2026-05-22"):
    return journal.open_trade(TradeOpen(
        symbol=symbol, market=market, strategy=strategy, entry_date=entry_date,
        entry_price=price, entry_size=size, stop_loss_price=price * 0.95,
        reason_timing="test",
    ))


def test_list_open_strategy_filter_isolates_sleeves(journal: Journal):
    """A_mr daily 跑时只看到 A_mr 持仓, 不挤 A_mom slot."""
    # 模拟 v5 实盘当前: A_mom 4 仓 + zhuang 不在这, A_mr 0 仓
    _open(journal, "601939", "equity_momentum")
    _open(journal, "600919", "equity_momentum")
    _open(journal, "601838", "equity_momentum")
    _open(journal, "601066", "equity_momentum")

    # A_mr daily 跑时应该看到自己 0 仓 (不被 A_mom 4 仓挤占 slot)
    a_mr_open = journal.list_open(market="a_share", strategy="mean_reversion")
    assert len(a_mr_open) == 0

    # A_mom 跑时看到自己 4 仓
    a_mom_open = journal.list_open(market="a_share", strategy="equity_momentum")
    assert len(a_mom_open) == 4

    # HK_mom 跑时看到 0 仓 (market filter 生效)
    hk_open = journal.list_open(market="hk_share", strategy="equity_hk_momentum")
    assert len(hk_open) == 0


def test_a_mr_can_open_alongside_a_mom_same_symbol(journal: Journal):
    """跨 sleeve 不强制隔离 symbol — A_mr 可以 open 601939 即使 A_mom 已持有.

    v5 设计是分账户; PM 决策 doubledown vs hedge. 工程层默认允许.
    """
    a_mom_tid = _open(journal, "601939", "equity_momentum", price=10.0, size=1000)
    a_mr_tid = _open(journal, "601939", "mean_reversion", price=10.0, size=500)
    assert a_mom_tid != a_mr_tid
    # 各自 sleeve 都有 601939 一仓
    assert {t["symbol"] for t in journal.list_open(strategy="equity_momentum")} == {"601939"}
    assert {t["symbol"] for t in journal.list_open(strategy="mean_reversion")} == {"601939"}


def test_a_mr_open_codes_set_excludes_a_mom_holdings(journal: Journal):
    """daily_equity 自动开仓段 open_codes_set 现在 strategy-scoped.

    模拟实盘当前: A_mom 5 仓 (近满). 如果 list_open 不 filter, A_mr 会被 A_mom 5 仓
    挤到 max_positions=6 只剩 1 slot. 修复后 A_mr 独立计 0/6.
    """
    # 模拟 A_mom 持仓接近上限
    for code in ["601939", "600919", "601838", "601988", "000063"]:
        _open(journal, code, "equity_momentum")

    # 模拟 daily_equity --strategy mean_reversion 跑 — 应只看自己 (0 仓)
    a_mr_codes = {
        t["symbol"]
        for t in journal.list_open(market="a_share", strategy="mean_reversion")
    }
    max_positions = 6
    a_mr_available = max_positions - len(a_mr_codes)
    assert a_mr_available == 6, "A_mr 独立 slot 池, 不被 A_mom 5 仓挤占"

    # 同时 A_mom 跑时仍看自己 5 仓
    a_mom_codes = {
        t["symbol"]
        for t in journal.list_open(market="a_share", strategy="equity_momentum")
    }
    a_mom_available = max_positions - len(a_mom_codes)
    assert a_mom_available == 1, "A_mom 自己仍 5/6"


def test_close_trade_strategy_isolated(journal: Journal):
    """退出某 sleeve 的某 symbol 不影响另一 sleeve 同 symbol (跨账户隔离)."""
    a_mom_tid = _open(journal, "601939", "equity_momentum", price=10.0, size=1000)
    a_mr_tid = _open(journal, "601939", "mean_reversion", price=10.0, size=500)
    journal.close_trade(a_mom_tid, "2026-05-30", 11.0, "take_profit")
    # A_mr 仓位仍 open
    a_mr_open = journal.list_open(strategy="mean_reversion")
    assert len(a_mr_open) == 1
    assert a_mr_open[0]["id"] == a_mr_tid
    # A_mom 仓位已关
    assert journal.list_open(strategy="equity_momentum") == []
