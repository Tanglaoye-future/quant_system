"""CB Backtester (PR5) 单元测试.

锁定 docs/specs/convertible_bond_sleeve.md §3 + PR5 设计:
- 月/周/日再平衡日期挑选
- 月度 rebalance + 月内 force-exit (stop_loss/dual_low_too_high/redeem)
- M0 artifact 8 文件落盘
- nuance 1 daily_panel_coverage 序列
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import json
import pandas as pd
import pytest

from quant_system.strategies.cb_double_low.engine.backtest import (
    CBBacktester,
    CBBacktestResult,
    write_m0_artifact,
)
from quant_system.strategies.cb_double_low.engine.strategy import CBDoubleLowConfig
from quant_system.strategies.cb_double_low.universe.filter import (
    UniverseFilterConfig,
)


# ── rebalance dates ──────────────────────────────────────────────────


def test_rebalance_dates_monthly_picks_first_trading_day_per_month():
    loader = MagicMock()
    bt = CBBacktester(loader, CBDoubleLowConfig(), rebalance_freq="monthly")
    days = [
        date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5),
        date(2024, 2, 1), date(2024, 2, 5),
        date(2024, 3, 4),
    ]
    out = bt._compute_rebalance_dates(days)
    assert out == {date(2024, 1, 3), date(2024, 2, 1), date(2024, 3, 4)}


def test_rebalance_dates_weekly_one_per_iso_week():
    loader = MagicMock()
    bt = CBBacktester(loader, CBDoubleLowConfig(), rebalance_freq="weekly")
    days = [
        date(2024, 1, 2), date(2024, 1, 3),  # week 1
        date(2024, 1, 8), date(2024, 1, 9),  # week 2
    ]
    out = bt._compute_rebalance_dates(days)
    assert out == {date(2024, 1, 2), date(2024, 1, 8)}


def test_rebalance_dates_daily_returns_all():
    loader = MagicMock()
    bt = CBBacktester(loader, CBDoubleLowConfig(), rebalance_freq="daily")
    days = [date(2024, 1, 2), date(2024, 1, 3)]
    out = bt._compute_rebalance_dates(days)
    assert out == set(days)


def test_rebalance_freq_invalid_raises():
    loader = MagicMock()
    with pytest.raises(ValueError, match="rebalance_freq"):
        CBBacktester(loader, CBDoubleLowConfig(), rebalance_freq="quarterly")


# ── redemption proxy ─────────────────────────────────────────────────


def test_redeem_active_on_uses_last_trading_date():
    loader = MagicMock()
    bt = CBBacktester(loader, CBDoubleLowConfig())
    redemption = pd.DataFrame(
        {
            "bond_code": ["A", "B", "C"],
            "last_trading_date": pd.to_datetime(
                ["2026-01-01", "2026-06-15", "2026-12-31"]
            ),
            "maturity_date": pd.to_datetime(
                ["2027-01-01", "2027-06-15", "2027-12-31"]
            ),
        }
    )
    active = bt._redeem_active_on(redemption, date(2026, 6, 15))
    assert active == {"A", "B"}, "已过最后交易日的视为强赎生效"


# ── end-to-end backtest with mocked loader ───────────────────────────


def _make_mock_loader(start_dt, end_dt):
    """3 只债, 60 天 panel, 等价信号."""
    codes = ["100001", "100002", "100003"]
    universe = pd.DataFrame(
        {
            "bond_code": codes,
            "bond_name": codes,
            "stock_code": codes,
            "stock_name": codes,
            "listing_date": pd.to_datetime(["2020-01-01"] * 3),
            "delisting_date": [pd.NaT] * 3,
            "scale_remain": [10.0] * 3,
            "credit_rating": ["AAA"] * 3,
            "exit_status": ["active"] * 3,
        }
    )
    dates = pd.date_range(start_dt, end_dt, freq="B")
    rows = []
    for d in dates:
        for c in codes:
            rows.append(
                {
                    "date": d,
                    "bond_code": c,
                    "close": 100.0 + int(c[-1]),  # 101/102/103
                    "pure_bond_value": 90.0,
                    "conversion_value": 95.0,
                    "pure_bond_premium_rate": 10.0,
                    "conversion_premium_rate": 5.0,
                }
            )
    panel = pd.DataFrame(rows)
    redemption = pd.DataFrame(
        columns=[
            "bond_code", "bond_name", "announcement_date",
            "last_trading_date", "maturity_date",
            "redemption_price", "status",
        ]
    )
    loader = MagicMock()
    loader.load_universe.return_value = universe
    loader.load_panel.return_value = panel
    loader.load_redemption_events.return_value = redemption
    return loader


def test_backtest_end_to_end_runs_without_crash(tmp_path):
    """端到端: 3 只债 60 天 monthly rebalance, equity 序列长度匹配 trading days."""
    loader = _make_mock_loader(date(2024, 1, 1), date(2024, 3, 31))
    cfg = CBDoubleLowConfig(
        n_entry=3, n_hold_buffer=1.5, exit_dual_low_threshold=999.0,
        stop_loss_close=0.0,
        filter_config=UniverseFilterConfig(min_scale_remain_yi=0.0),
    )
    bt = CBBacktester(loader, cfg, initial_capital=1_000_000.0)
    result = bt.run("2024-01-01", "2024-03-31", verbose=False)
    assert isinstance(result, CBBacktestResult)
    assert len(result.equity_curve) > 0
    assert "n_positions" in result.daily_positions.columns
    assert "pct" in result.daily_panel_coverage.columns
    # coverage 应是 1.0 (mock 数据全 3 只都有当日 panel)
    assert result.daily_panel_coverage["pct"].min() == 1.0


def test_backtest_force_exit_on_stop_loss(tmp_path):
    """持仓 close 跌到 70 → stop_loss 出场."""
    loader = _make_mock_loader(date(2024, 1, 1), date(2024, 2, 28))
    panel = loader.load_panel.return_value.copy()
    # 让 100001 在 2024-02 之后跌穿 80
    crash_mask = (panel["bond_code"] == "100001") & (
        panel["date"] >= pd.Timestamp("2024-02-15")
    )
    panel.loc[crash_mask, "close"] = 70.0
    loader.load_panel.return_value = panel
    cfg = CBDoubleLowConfig(
        n_entry=3, exit_dual_low_threshold=999.0, stop_loss_close=85.0,
        filter_config=UniverseFilterConfig(
            min_close=0.0, min_scale_remain_yi=0.0,
        ),
    )
    bt = CBBacktester(loader, cfg)
    result = bt.run("2024-01-01", "2024-02-28", verbose=False)
    reasons = {t.exit_reason for t in result.closed_trades}
    assert "stop_loss" in reasons, "close=70 < 85 必须触发 stop_loss"


def test_backtest_force_exit_on_high_dual_low(tmp_path):
    """score 越线 → dual_low_too_high 出场."""
    loader = _make_mock_loader(date(2024, 1, 1), date(2024, 2, 28))
    panel = loader.load_panel.return_value.copy()
    crash_mask = (panel["bond_code"] == "100002") & (
        panel["date"] >= pd.Timestamp("2024-02-15")
    )
    panel.loc[crash_mask, "conversion_premium_rate"] = 100.0  # 推 score 到 200+
    loader.load_panel.return_value = panel
    cfg = CBDoubleLowConfig(
        n_entry=3, exit_dual_low_threshold=150.0, stop_loss_close=0.0,
        filter_config=UniverseFilterConfig(
            min_close=0.0, min_scale_remain_yi=0.0,
        ),
    )
    bt = CBBacktester(loader, cfg)
    result = bt.run("2024-01-01", "2024-02-28", verbose=False)
    reasons = {t.exit_reason for t in result.closed_trades}
    assert "dual_low_too_high" in reasons


# ── M0 artifact ──────────────────────────────────────────────────────


def test_m0_artifact_writes_all_required_files(tmp_path: Path):
    """M0 8 文件 + JSON parseable."""
    loader = _make_mock_loader(date(2024, 1, 1), date(2024, 2, 28))
    cfg = CBDoubleLowConfig(
        n_entry=3, exit_dual_low_threshold=999.0, stop_loss_close=0.0,
        filter_config=UniverseFilterConfig(
            min_close=0.0, min_scale_remain_yi=0.0,
        ),
    )
    bt = CBBacktester(loader, cfg)
    result = bt.run("2024-01-01", "2024-02-28", verbose=False)
    out_dir = tmp_path / "cb_double_low_a_share_2024-01-01_2024-02-28"
    metrics = write_m0_artifact(
        result, out_dir,
        strategy="cb_double_low", market="a_share",
        start="2024-01-01", end="2024-02-28", config=cfg,
    )

    required_files = [
        "metrics.json", "equity.csv", "positions.csv", "closed_trades.csv",
        "daily_panel_coverage.csv", "rebalance_funnel.csv",
        "entry_candidates.csv", "exit_events.csv", "exit_reason_summary.json",
    ]
    for fname in required_files:
        assert (out_dir / fname).exists(), f"M0 缺文件 {fname}"

    # metrics.json 关键字段
    parsed = json.loads((out_dir / "metrics.json").read_text())
    for key in [
        "strategy", "market", "start", "end",
        "initial_capital", "final_equity", "total_return",
        "cagr", "sharpe", "max_drawdown",
        "n_closed_trades", "hit_rate", "avg_pnl_pct", "config",
    ]:
        assert key in parsed, f"metrics.json 缺 key {key}"
    assert parsed["strategy"] == "cb_double_low"
    assert parsed["market"] == "a_share"


def test_m0_metrics_equity_curve_consistent(tmp_path: Path):
    """metrics.total_return 与 equity_curve 首末一致."""
    loader = _make_mock_loader(date(2024, 1, 1), date(2024, 2, 28))
    cfg = CBDoubleLowConfig(
        n_entry=3, exit_dual_low_threshold=999.0, stop_loss_close=0.0,
        filter_config=UniverseFilterConfig(
            min_close=0.0, min_scale_remain_yi=0.0,
        ),
    )
    bt = CBBacktester(loader, cfg, initial_capital=1_000_000.0)
    result = bt.run("2024-01-01", "2024-02-28", verbose=False)
    out_dir = tmp_path / "cb_double_low_a_share_2024-01-01_2024-02-28"
    metrics = write_m0_artifact(
        result, out_dir,
        strategy="cb_double_low", market="a_share",
        start="2024-01-01", end="2024-02-28", config=cfg,
    )
    eq = result.equity_curve
    expected_total = float(eq.iloc[-1]) / float(eq.iloc[0]) - 1
    assert abs(metrics["total_return"] - expected_total) < 1e-9
