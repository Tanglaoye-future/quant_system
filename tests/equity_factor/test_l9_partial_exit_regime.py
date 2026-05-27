"""L9-A: partial_exit regime filter — TP 命中时按基准 vs MA 决定是否 partial.

行为表（partial_exit_enabled=True, partial_exit_done=False, TP 命中）：

| partial_exit_regime_filter | regime_above_ma | 期望 reason 前缀 |
|---|---|---|
| False  | * (任意)        | take_profit_partial  (默认 / 兼容 L8D2)        |
| True   | True (牛市)     | take_profit          (跳过 partial，全平吃趋势)|
| True   | False (熊/震荡) | take_profit_partial  (保留 partial 锁利)       |
| True   | None (无样本)    | take_profit_partial  (保守退化到 partial)      |

partial_exit_done=True 时无论 regime 都不触发 partial（约束维持）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant_system.strategies.equity_factor.timing.signals import (
    TimingConfig,
    enrich,
    exit_signal_from_enriched,
)


def _tp_hit_df(entry_price: float = 100.0, atr_target_mult: float = 3.0) -> tuple[pd.DataFrame, TimingConfig]:
    """构造一个 TP 命中的 enriched df：close = entry + atr * atr_target_mult，避开 break_ma / overbought / time_stop."""
    n = 90
    dr = pd.date_range("2024-01-01", periods=n, freq="D")
    base = np.linspace(95.0, 99.0, n - 1).tolist()  # close 稳步上行，低于 entry → 让 MA60 处于 entry 附近偏低
    close = np.array(base + [entry_price + atr_target_mult * 1.0 + 0.5])  # 最后一根直接拉到 TP 之上
    df = pd.DataFrame(
        {
            "date": dr.strftime("%Y-%m-%d"),
            "open": close,
            "high": close + 0.1,
            "low": close - 0.1,
            "close": close,
            "volume": [1_000_000] * n,
        }
    )
    cfg = TimingConfig(
        atr_period=14,
        atr_stop_mult=1.5,
        atr_target_mult=atr_target_mult,
        max_hold_days=60,
        partial_exit_enabled=True,
        partial_exit_pct=0.5,
        partial_exit_trail_mult=1.5,
    )
    enriched = enrich(df, cfg)
    # 把最后一根 atr 强制 = 1.0，让 close >= entry + 3*1 = 103；构造的 close = 103.5 ✅
    enriched.loc[enriched.index[-1], "atr"] = 1.0
    # rsi 强制 50（避开 overbought）；ma_long 强制 entry - 1（避开 break_ma）
    enriched.loc[enriched.index[-1], "rsi"] = 50.0
    enriched.loc[enriched.index[-1], "ma_long"] = entry_price - 1.0
    return enriched, cfg


def test_partial_regime_filter_off_returns_partial():
    """默认 partial_exit_regime_filter=False → 兼容 L8D2 行为，TP 命中走 partial."""
    enriched, cfg = _tp_hit_df()
    cfg.partial_exit_regime_filter = False
    res = exit_signal_from_enriched(
        enriched, entry_price=100.0, entry_date="2024-01-01",
        trailing_stop_price=None, cfg=cfg, regime_above_ma=True,  # 哪怕 regime=True 也忽略
    )
    assert res["signal"] is True
    assert res.get("partial") is True
    assert res["reason"].startswith("take_profit_partial:")


def test_partial_regime_filter_on_bull_skips_partial():
    """regime_filter=True + regime_above_ma=True（牛市）→ 跳过 partial，走全平 TP."""
    enriched, cfg = _tp_hit_df()
    cfg.partial_exit_regime_filter = True
    cfg.partial_exit_regime_ma_days = 200
    res = exit_signal_from_enriched(
        enriched, entry_price=100.0, entry_date="2024-01-01",
        trailing_stop_price=None, cfg=cfg, regime_above_ma=True,
    )
    assert res["signal"] is True
    assert res.get("partial") is not True
    assert res["reason"].startswith("take_profit:")


def test_partial_regime_filter_on_bear_keeps_partial():
    """regime_filter=True + regime_above_ma=False（熊/震荡）→ 保留 partial."""
    enriched, cfg = _tp_hit_df()
    cfg.partial_exit_regime_filter = True
    cfg.partial_exit_regime_ma_days = 200
    res = exit_signal_from_enriched(
        enriched, entry_price=100.0, entry_date="2024-01-01",
        trailing_stop_price=None, cfg=cfg, regime_above_ma=False,
    )
    assert res["signal"] is True
    assert res.get("partial") is True
    assert res["reason"].startswith("take_profit_partial:")


def test_partial_regime_filter_on_none_keeps_partial():
    """regime_above_ma=None（无样本/异常）→ 退化为 partial（安全 fallback）."""
    enriched, cfg = _tp_hit_df()
    cfg.partial_exit_regime_filter = True
    res = exit_signal_from_enriched(
        enriched, entry_price=100.0, entry_date="2024-01-01",
        trailing_stop_price=None, cfg=cfg, regime_above_ma=None,
    )
    assert res["signal"] is True
    assert res.get("partial") is True
    assert res["reason"].startswith("take_profit_partial:")


def test_partial_done_then_regime_filter_no_partial_again():
    """partial_exit_done=True 时无论 regime 都不会再走 partial（约束维持）."""
    enriched, cfg = _tp_hit_df()
    cfg.partial_exit_regime_filter = True
    # 第二次触发 TP（partial_done=True） → 走全平 TP，不论 regime
    for ra in (True, False, None):
        res = exit_signal_from_enriched(
            enriched, entry_price=100.0, entry_date="2024-01-01",
            trailing_stop_price=None, cfg=cfg,
            partial_exit_done=True, regime_above_ma=ra,
        )
        assert res["signal"] is True
        assert res.get("partial") is not True
        assert res["reason"].startswith("take_profit:")


def test_yaml_node_parses_l9_fields():
    """timing_config_from_yaml_node 必须能读出新字段，未声明时取默认值."""
    from quant_system.strategies.equity_factor.timing.signals import timing_config_from_yaml_node

    cfg_default = timing_config_from_yaml_node({})
    assert cfg_default.partial_exit_regime_filter is False
    assert cfg_default.partial_exit_regime_ma_days == 200

    cfg_on = timing_config_from_yaml_node(
        {"partial_exit_regime_filter": True, "partial_exit_regime_ma_days": 120}
    )
    assert cfg_on.partial_exit_regime_filter is True
    assert cfg_on.partial_exit_regime_ma_days == 120
