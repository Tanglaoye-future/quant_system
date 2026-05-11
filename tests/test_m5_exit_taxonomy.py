"""M5: exit_layer_from_reason 与 timing exit 字符串前缀一致."""
from quant_system.timing.exit_taxonomy import (
    LAYER_FORCED_CLOSE,
    LAYER_OVERBOUGHT,
    LAYER_REGIME,
    LAYER_STOP_TRAIL,
    LAYER_STOP_TREND,
    LAYER_TAKE_PROFIT,
    LAYER_TAKE_PROFIT_PARTIAL,
    LAYER_TIME_STOP,
    exit_layer_from_reason,
)


def test_trailing_and_break_ma():
    assert exit_layer_from_reason("trailing_stop: close=1 <= stop=2") == LAYER_STOP_TRAIL
    assert exit_layer_from_reason("break_ma60: close=1 < MA60=2") == LAYER_STOP_TREND


def test_take_profit_overbought_time():
    assert exit_layer_from_reason("take_profit: close=10 >= target=9") == LAYER_TAKE_PROFIT
    assert exit_layer_from_reason("overbought: RSI=80.0 >= 75") == LAYER_OVERBOUGHT
    assert exit_layer_from_reason("time_stop: 持有 61 天 >= 60") == LAYER_TIME_STOP


def test_take_profit_partial():
    assert exit_layer_from_reason("take_profit_partial: close=10 >= target=9 (出场50%)") == LAYER_TAKE_PROFIT_PARTIAL
    # take_profit（全量）不能误判为 partial
    assert exit_layer_from_reason("take_profit: close=10 >= target=9") == LAYER_TAKE_PROFIT


def test_regime_and_forced():
    assert exit_layer_from_reason("m5_regime_exit: index below MA") == LAYER_REGIME
    assert exit_layer_from_reason("backtest_end_close") == LAYER_FORCED_CLOSE


def test_hold_empty():
    assert exit_layer_from_reason("持有") == ""
    assert exit_layer_from_reason("") == ""
