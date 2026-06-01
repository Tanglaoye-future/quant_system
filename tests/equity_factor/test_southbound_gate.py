"""A1' southbound gate 单测: TimingConfig 字段 / entry_signal 拒入场 / regime_ctx 字段."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_system.strategies.equity_factor.timing.regime import TimingRegimeContext
from quant_system.strategies.equity_factor.timing.signals import (
    TimingConfig,
    enrich,
    entry_signal_from_enriched,
)


def _trending_df(days: int = 220) -> pd.DataFrame:
    """构造一只稳定上涨趋势 + 当日突破的股票, 保证除 gate 外其他入场条件能通过."""
    rng = np.random.RandomState(0)
    close = np.linspace(10.0, 30.0, days) + rng.normal(0, 0.1, days)
    high = close + 0.5
    low = close - 0.5
    open_ = close - 0.1
    volume = np.full(days, 1_000_000.0)
    # 当日量放大触发突破检测
    volume[-1] = 3_000_000.0
    dates = pd.date_range("2024-01-01", periods=days, freq="B").strftime("%Y-%m-%d")
    df = pd.DataFrame({
        "date": dates, "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
    })
    return df


def _default_cfg(**overrides) -> TimingConfig:
    """默认 cfg: m2_breakout_mode (避开金叉历史复杂), gate disabled."""
    base = {
        "m2_breakout_mode": True,
        "m2_structure_lookback": 20,
        "m2_structure_eps": 0.0,
        "rsi_entry_low": 40.0,
        "rsi_entry_high": 90.0,
    }
    base.update(overrides)
    return TimingConfig(**base)


def test_timing_config_includes_southbound_gate_fields():
    cfg = TimingConfig()
    assert hasattr(cfg, "m3_southbound_gate_enabled")
    assert hasattr(cfg, "m3_southbound_gate_lookback_days")
    assert hasattr(cfg, "m3_southbound_gate_threshold_yi")
    assert cfg.m3_southbound_gate_enabled is False
    assert cfg.m3_southbound_gate_lookback_days == 10
    assert cfg.m3_southbound_gate_threshold_yi == 200.0


def test_regime_context_includes_southbound_cum_field():
    rc = TimingRegimeContext(None, None, None)
    assert hasattr(rc, "southbound_cum_lookback")
    assert rc.southbound_cum_lookback is None


def test_gate_disabled_does_not_filter_entry():
    """gate disabled (默认) → entry_signal 不受南向数据影响."""
    cfg = _default_cfg()
    enriched = enrich(_trending_df(), cfg)
    # regime_ctx 不存在不影响
    sig = entry_signal_from_enriched(enriched, cfg, regime_ctx=None)
    # baseline 应该能 pass (breakout 触发)
    # 即使 fail 也不是因为 gate
    assert "南向gateX" not in "|".join(sig.get("reasons", []))


def test_gate_enabled_below_threshold_rejects_entry():
    """gate enabled + 累计 100 亿 < 200 阈值 → 拒入场."""
    cfg = _default_cfg(
        m3_southbound_gate_enabled=True,
        m3_southbound_gate_lookback_days=10,
        m3_southbound_gate_threshold_yi=200.0,
    )
    enriched = enrich(_trending_df(), cfg)
    rc = TimingRegimeContext(None, None, None, southbound_cum_lookback=100.0)  # < 200
    sig = entry_signal_from_enriched(enriched, cfg, regime_ctx=rc)
    assert sig["signal"] is False
    assert any("南向gateX" in r for r in sig["reasons"])
    assert any("100.0亿" in r for r in sig["reasons"])


def test_gate_enabled_above_threshold_allows_entry():
    """gate enabled + 累计 300 亿 >= 200 阈值 → gate 不拦截 (signal 结果可能因后续 entry 检查 fail, 但拒绝原因不应是 gate)."""
    cfg = _default_cfg(
        m3_southbound_gate_enabled=True,
        m3_southbound_gate_lookback_days=10,
        m3_southbound_gate_threshold_yi=200.0,
    )
    enriched = enrich(_trending_df(), cfg)
    rc = TimingRegimeContext(None, None, None, southbound_cum_lookback=300.0)  # >= 200
    sig = entry_signal_from_enriched(enriched, cfg, regime_ctx=rc)
    # 不应被 gate 拒绝 (即便后续 entry 因别的原因 fail, 拒绝信息不应包含 gate)
    assert not any("南向gateX" in r for r in sig.get("reasons", []))
    assert not any("累计数据不可用" in r for r in sig.get("reasons", []))
    assert not any("regime_ctx 缺失" in r for r in sig.get("reasons", []))


def test_gate_enabled_data_unavailable_rejects_conservatively():
    """gate enabled + 累计数据 None (实盘日数据停更模拟) → 保守拒入场."""
    cfg = _default_cfg(
        m3_southbound_gate_enabled=True,
        m3_southbound_gate_threshold_yi=200.0,
    )
    enriched = enrich(_trending_df(), cfg)
    rc = TimingRegimeContext(None, None, None, southbound_cum_lookback=None)
    sig = entry_signal_from_enriched(enriched, cfg, regime_ctx=rc)
    assert sig["signal"] is False
    assert any("累计数据不可用" in r for r in sig["reasons"])


def test_gate_enabled_no_regime_ctx_rejects():
    """gate enabled + regime_ctx 完全缺失 → 拒入场 (defense in depth)."""
    cfg = _default_cfg(m3_southbound_gate_enabled=True)
    enriched = enrich(_trending_df(), cfg)
    sig = entry_signal_from_enriched(enriched, cfg, regime_ctx=None)
    assert sig["signal"] is False
    assert any("regime_ctx 缺失" in r for r in sig["reasons"])


def test_yaml_loader_accepts_gate_fields():
    """yaml 节点直接构造 TimingConfig 应能接受新字段."""
    from quant_system.strategies.equity_factor.timing.signals import (
        timing_config_from_yaml_node,
    )
    node = {
        "m3_southbound_gate_enabled": True,
        "m3_southbound_gate_lookback_days": 5,
        "m3_southbound_gate_threshold_yi": 150.0,
    }
    cfg = timing_config_from_yaml_node(node)
    assert cfg.m3_southbound_gate_enabled is True
    assert cfg.m3_southbound_gate_lookback_days == 5
    assert cfg.m3_southbound_gate_threshold_yi == 150.0
