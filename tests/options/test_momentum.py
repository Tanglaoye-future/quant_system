"""
动量信号单元测试（用合成数据，不依赖网络）.
"""
import numpy as np
import pandas as pd
import pytest

from quant_system.strategies.options.signals.momentum import MomentumSignal, _compute_rsi


class TestRSI:
    def _make_series(self, values) -> pd.Series:
        return pd.Series(values, dtype=float)

    def test_rsi_range(self):
        rng = np.random.default_rng(42)
        prices = 100 + rng.normal(0, 1, 200).cumsum()
        rsi = _compute_rsi(pd.Series(prices), 14)
        valid = rsi.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_rsi_rising_market(self):
        """持续上涨市场 RSI 应接近 100."""
        prices = pd.Series(np.linspace(100, 150, 50))
        rsi = _compute_rsi(prices, 14)
        assert rsi.dropna().iloc[-1] > 70

    def test_rsi_falling_market(self):
        """持续下跌市场 RSI 应接近 0."""
        prices = pd.Series(np.linspace(150, 100, 50))
        rsi = _compute_rsi(prices, 14)
        assert rsi.dropna().iloc[-1] < 30


class TestMomentumSignal:
    def _make_bullish_signal(self) -> MomentumSignal:
        return MomentumSignal(
            date="2026-05-09", price=490.0, ma200=450.0,
            rsi=62.0, momentum_3m=0.08,
            above_ma200=True, rsi_in_range=True, momentum_positive=True,
            bullish=True,
        )

    def test_bullish_all_conditions(self):
        sig = self._make_bullish_signal()
        assert sig.bullish is True
        assert sig.above_ma200 is True
        assert sig.rsi_in_range is True
        assert sig.momentum_positive is True

    def test_bearish_below_ma(self):
        sig = MomentumSignal(
            date="2026-05-09", price=440.0, ma200=450.0,
            rsi=58.0, momentum_3m=0.03,
            above_ma200=False, rsi_in_range=True, momentum_positive=True,
            bullish=False,
        )
        assert sig.bullish is False
        assert sig.above_ma200 is False

    def test_rsi_overbought(self):
        sig = MomentumSignal(
            date="2026-05-09", price=490.0, ma200=450.0,
            rsi=82.0, momentum_3m=0.10,
            above_ma200=True, rsi_in_range=False, momentum_positive=True,
            bullish=False,
        )
        assert sig.bullish is False
        assert sig.rsi_in_range is False

    def test_negative_momentum(self):
        sig = MomentumSignal(
            date="2026-05-09", price=490.0, ma200=450.0,
            rsi=55.0, momentum_3m=-0.05,
            above_ma200=True, rsi_in_range=True, momentum_positive=False,
            bullish=False,
        )
        assert sig.bullish is False
        assert sig.momentum_positive is False


class TestSizePosition:
    def test_basic_sizing(self):
        from quant_system.strategies.options.signals.selector import size_position
        result = size_position(
            net_debit_per_contract=4.50,
            account_net_liq=13700.0,
            risk_pct=0.03,
        )
        # 3% × $13700 = $411 budget; 1张成本 = $450 > $411 → 仍给 1 张（min_contracts=1）
        assert result["contracts"] >= 1
        assert result["total_risk"] <= 13700.0 * 0.10  # 不超过10%

    def test_cheap_spread_multi_contracts(self):
        from quant_system.strategies.options.signals.selector import size_position
        result = size_position(
            net_debit_per_contract=1.50,   # 便宜价差 → 可买多张
            account_net_liq=50000.0,
            risk_pct=0.03,
        )
        # budget = $1500, cost/张 = $150 → 10 张，但 max_contracts=5
        assert result["contracts"] == 5

    def test_zero_debit(self):
        from quant_system.strategies.options.signals.selector import size_position
        result = size_position(net_debit_per_contract=0.0, account_net_liq=13700.0)
        assert result["contracts"] == 0
