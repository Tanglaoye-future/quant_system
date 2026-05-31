"""monthly_kpi_report 单测 — 内存 SQLite 注入 sessionmaker, 不依赖 PG."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "reporting"))

from quant_system.db.models import Base
from quant_system.strategies.equity_factor.journal.journal import Journal, TradeOpen
from quant_system.strategies.zhuang.journal.journal import (
    ZhuangJournal,
    TradeOpen as ZhuangTradeOpen,
)

from monthly_kpi_report import (
    V5_WEIGHTS,
    aggregate_equity,
    aggregate_zhuang,
    evaluate_alerts,
    month_window,
    render_markdown,
    run_report,
    SleeveStats,
)


@pytest.fixture
def journals():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sm = sessionmaker(bind=engine, expire_on_commit=False)
    return Journal(sessionmaker=sm), ZhuangJournal(sessionmaker=sm)


def test_month_window_parses_correctly():
    s, e = month_window("2026-06")
    assert s == date(2026, 6, 1)
    assert e == date(2026, 6, 30)
    s2, e2 = month_window("2026-02")  # 非闰年
    assert e2 == date(2026, 2, 28)


def test_empty_journal_returns_zero_stats(journals):
    eq, zh = journals
    sleeves = aggregate_equity(eq, date(2026, 6, 1), date(2026, 6, 30))
    assert set(sleeves) == {"HK", "A_mom", "A_mr"}
    for s in sleeves.values():
        assert s.n_closed == 0
        assert s.win_rate is None
    zs = aggregate_zhuang(zh, date(2026, 6, 1), date(2026, 6, 30))
    assert zs.n_closed == 0


def test_aggregate_classifies_hk_and_a_share(journals):
    eq, _ = journals
    # HK winner
    tid = eq.open_trade(TradeOpen(symbol="00700", market="hk_share",
                                  strategy="equity_hk_momentum",
                                  entry_date="2026-06-05",
                                  entry_price=100.0, entry_size=100,
                                  entry_score=8.0, stop_loss_price=90.0))
    eq.close_trade(tid, exit_date="2026-06-15", exit_price=110.0,
                   exit_reason="target")
    # A_mom loser
    tid = eq.open_trade(TradeOpen(symbol="601939", market="a_share",
                                  strategy="equity_momentum",
                                  entry_date="2026-06-10",
                                  entry_price=10.0, entry_size=1000,
                                  entry_score=7.0, stop_loss_price=9.0))
    eq.close_trade(tid, exit_date="2026-06-20", exit_price=9.5,
                   exit_reason="stop_loss")
    # A_mr — 当月外, 不应被聚合
    tid = eq.open_trade(TradeOpen(symbol="600000", market="a_share",
                                  strategy="mean_reversion",
                                  entry_date="2026-05-01",
                                  entry_price=10.0, entry_size=100,
                                  entry_score=5.0, stop_loss_price=9.0))
    eq.close_trade(tid, exit_date="2026-05-10", exit_price=10.5,
                   exit_reason="target")

    sleeves = aggregate_equity(eq, date(2026, 6, 1), date(2026, 6, 30))
    assert sleeves["HK"].n_closed == 1
    assert sleeves["HK"].n_winner == 1
    assert sleeves["HK"].win_rate == 1.0
    assert sleeves["HK"].sum_pnl == pytest.approx(1000.0)
    assert sleeves["A_mom"].n_closed == 1
    assert sleeves["A_mom"].n_winner == 0
    assert sleeves["A_mr"].n_closed == 0  # 5 月份的不算


def test_aggregate_zhuang_pnl_pct_mean(journals):
    _, zh = journals
    for code, ep, xp in [("600575", 4.0, 4.4), ("000601", 3.0, 3.3)]:
        tid = zh.open_trade(ZhuangTradeOpen(code=code, entry_date="2026-06-05",
                                            entry_price=ep, entry_size=1000,
                                            accumulation_score=75.0,
                                            stop_loss_price=ep * 0.95))
        zh.close_trade(tid, exit_date="2026-06-15", exit_price=xp,
                       exit_reason="take_profit")
    zs = aggregate_zhuang(zh, date(2026, 6, 1), date(2026, 6, 30))
    assert zs.n_closed == 2
    assert zs.n_winner == 2
    assert zs.mean_pnl_pct == pytest.approx((0.10 + 0.10) / 2)


def test_alerts_trigger_on_low_win_rate_and_negative_portfolio_return():
    sleeves = {
        "HK": SleeveStats(name="HK", weight=0.25, n_closed=6, n_winner=1,
                          sum_pnl=-5000.0, mean_pnl_pct=-0.05),
        "A_mom": SleeveStats(name="A_mom", weight=0.10, n_closed=2, n_winner=0,
                             sum_pnl=-200.0, mean_pnl_pct=-0.02),
    }
    alerts = evaluate_alerts(sleeves, portfolio_ret=-0.03, zhuang_aum=10_000_000)
    # HK 低 win rate (1/6 = 16.7% < 30%, n=6>=5) → 触发
    assert any("HK win rate" in a for a in alerts)
    # A_mom n=2 < 5 → 不触发
    assert not any("A_mom win rate" in a for a in alerts)
    # 组合 -3% < -2% → 触发
    assert any("组合月收益" in a for a in alerts)
    # zhuang 10M < 30M → 不触发
    assert not any("zhuang AUM" in a for a in alerts)


def test_alerts_trigger_zhuang_aum_overflow():
    sleeves = {}
    alerts = evaluate_alerts(sleeves, portfolio_ret=0.01, zhuang_aum=50_000_000)
    assert any("zhuang AUM" in a for a in alerts)


def test_render_markdown_contains_required_sections(journals):
    eq, zh = journals
    sleeves = aggregate_equity(eq, date(2026, 6, 1), date(2026, 6, 30))
    sleeves["zhuang"] = aggregate_zhuang(zh, date(2026, 6, 1), date(2026, 6, 30))
    md = render_markdown("2026-06", sleeves, aum_cny=1_000_000.0,
                         portfolio_ret=0.0, alerts=[])
    assert "v5 实盘月度 KPI 报告 — 2026-06" in md
    assert "## 各 sleeve closed trades 摘要" in md
    assert "| HK |" in md and "| A_mom |" in md and "| A_mr |" in md and "| zhuang |" in md
    assert "## 组合层 KPI" in md
    assert "无触发告警" in md  # 空 alerts


def test_run_report_end_to_end_empty_journal(journals):
    eq, zh = journals
    md = run_report("2026-06", aum_cny=1_000_000.0,
                    equity_journal=eq, zhuang_journal=zh)
    assert "v5 实盘月度 KPI 报告" in md
    # 组合月收益 0 — 不触发告警
    assert "无触发告警" in md


def test_run_report_buy_and_hold_returns_included(journals):
    eq, zh = journals
    # QQQ +2% × weight 5% = +0.10% 组合贡献
    md = run_report("2026-06", aum_cny=1_000_000.0,
                    equity_journal=eq, zhuang_journal=zh,
                    qqq_ret=0.02, gld_ret=0.01)
    # 组合月收益 = 0 + 0.02*0.05 + 0.01*0.10 = 0.002 = 0.20%
    assert "+0.20%" in md


def test_v5_weights_sum_to_one():
    assert sum(V5_WEIGHTS.values()) == pytest.approx(1.0)
