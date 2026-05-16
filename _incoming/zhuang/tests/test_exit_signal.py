"""
Unit tests for exit signal module.
"""
import numpy as np
import pandas as pd
import pytest

from zhuang_system.signals.exit import check_exit_signal


def _make_position_df(n: int, entry_price: float = 10.0, drift: float = 0.0) -> pd.DataFrame:
    """构造从入场日起的日线 DataFrame."""
    close = np.full(n, entry_price) + np.arange(n) * drift
    high = close + 0.2
    low = close - 0.2
    volume = np.full(n, 1_000_000.0)
    turnover = np.full(n, 0.03)
    return pd.DataFrame({
        "date": pd.date_range("2022-06-01", periods=n, freq="B").strftime("%Y-%m-%d"),
        "open": close - 0.05, "high": high, "low": low, "close": close,
        "volume": volume, "turnover_rate": turnover,
    })


class TestExitSignal:
    def test_hold_signal(self):
        df = _make_position_df(3, entry_price=10.0, drift=0.01)
        sig = check_exit_signal(
            code="000001", df_since_entry=df,
            entry_price=10.0, entry_date="2022-06-01",
            atr_at_entry=0.3,
            stop_loss_atr_mult=3.0, take_profit_pct=0.15,
            max_hold_days=5,
        )
        assert sig.action == "HOLD"

    def test_stop_loss(self):
        # 第2日价格跌破止损
        df = _make_position_df(2, entry_price=10.0, drift=-1.0)
        sig = check_exit_signal(
            code="000001", df_since_entry=df,
            entry_price=10.0, entry_date="2022-06-01",
            atr_at_entry=0.3,
            stop_loss_atr_mult=3.0, take_profit_pct=0.15,
            max_hold_days=5,
        )
        assert sig.action == "EXIT"
        assert "stop_loss" in sig.reason

    def test_take_profit(self):
        # 第2日价格达到止盈（drift=2.0 → close[1]=12.0 >= 11.5）
        df = _make_position_df(2, entry_price=10.0, drift=2.0)
        sig = check_exit_signal(
            code="000002", df_since_entry=df,
            entry_price=10.0, entry_date="2022-06-01",
            atr_at_entry=0.3,
            stop_loss_atr_mult=3.0, take_profit_pct=0.15,
            max_hold_days=5,
        )
        assert sig.action == "EXIT"
        assert "take_profit" in sig.reason

    def test_time_stop(self):
        # 持有 5 天触发时间止损
        df = _make_position_df(6, entry_price=10.0, drift=0.001)
        sig = check_exit_signal(
            code="000003", df_since_entry=df,
            entry_price=10.0, entry_date="2022-06-01",
            atr_at_entry=0.3,
            stop_loss_atr_mult=3.0, take_profit_pct=0.15,
            max_hold_days=5,
        )
        assert sig.action == "EXIT"
        assert "time_stop" in sig.reason

    def test_distribution_signal(self):
        # 持仓 3 天，第 3 天高换手 + 未创新高 → 派发信号
        close = np.array([10.0, 10.2, 10.1])
        df = pd.DataFrame({
            "date": ["2022-06-01", "2022-06-02", "2022-06-03"],
            "open": close - 0.05, "high": close + 0.2, "low": close - 0.2,
            "close": close, "volume": [1e6, 1e6, 1e6],
            "turnover_rate": [0.03, 0.03, 0.10],  # 第 3 天高换手
        })
        sig = check_exit_signal(
            code="000004", df_since_entry=df,
            entry_price=10.0, entry_date="2022-06-01",
            atr_at_entry=0.3,
            stop_loss_atr_mult=3.0, take_profit_pct=0.15,
            max_hold_days=5,
            distribution_turnover_thresh=0.08,
        )
        assert sig.action == "EXIT"
        assert "distribution" in sig.reason

    def test_empty_df(self):
        df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        sig = check_exit_signal(
            code="000005", df_since_entry=df,
            entry_price=10.0, entry_date="2022-06-01",
            atr_at_entry=0.3,
        )
        assert sig.action == "HOLD"
