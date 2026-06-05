"""组合层风控 alerts —— 仅 alert 不自动平仓的契约测试。

覆盖：
- PortfolioRiskConfig 默认 disabled → _aggregate 不产生 alerts (向后兼容)
- enabled=True + 任一阈值触发 → alerts 命中且文案含具体数字
- 3 个阈值之间相互独立（一个触发不连带其他）
- enabled=False 时即使阈值满足也不触发（开关优先）
"""
from __future__ import annotations

from quant_system.strategies.equity_factor.risk.monitor import (
    PortfolioRisk,
    PortfolioRiskConfig,
    PositionRisk,
    RiskMonitor,
)


def _mk_pos(symbol: str, entry: float, size: int, current: float, action: str = "HOLD") -> PositionRisk:
    pnl = current / entry - 1.0
    return PositionRisk(
        trade_id=0, symbol=symbol, market="a_share", entry_date="2026-05-01",
        entry_price=entry, entry_size=size,
        current_date="2026-06-04", current_price=current,
        pnl_pct=pnl, pnl_amount=(current - entry) * size,
        hold_days=10, prev_stop=None, new_stop=entry * 0.95,
        action=action, reason="持有",
        take_profit=entry * 1.10, dist_to_target_pct=(entry * 1.10 - current) / current if current else None,
    )


def test_default_config_no_alerts_backcompat():
    positions = [_mk_pos("601939", 10.0, 100, 9.5), _mk_pos("601066", 20.0, 50, 25.0)]
    port = RiskMonitor._aggregate(positions, PortfolioRiskConfig())
    assert port.alerts == []


def test_disabled_with_thresholds_still_silent():
    """enabled=False 即使阈值满足也不触发 —— 总开关优先于个别阈值"""
    positions = [_mk_pos("601939", 10.0, 100, 5.0)]  # -50% 远低于 -5%
    cfg = PortfolioRiskConfig(
        enabled=False,
        unrealized_pnl_floor_pct=-0.05,
    )
    port = RiskMonitor._aggregate(positions, cfg)
    assert port.alerts == []


def test_max_single_weight_triggers():
    positions = [
        _mk_pos("601066", 20.0, 1000, 25.0),   # mv=25000，单只占比高
        _mk_pos("600919", 10.0, 100, 10.0),    # mv=1000
    ]
    cfg = PortfolioRiskConfig(enabled=True, max_single_weight_pct=0.30)
    port = RiskMonitor._aggregate(positions, cfg)
    assert len(port.alerts) == 1
    assert "单只权重" in port.alerts[0]
    assert "30.0%" in port.alerts[0]


def test_unrealized_pnl_floor_triggers():
    positions = [_mk_pos("601939", 10.0, 100, 8.0)]  # -20%
    cfg = PortfolioRiskConfig(enabled=True, unrealized_pnl_floor_pct=-0.05)
    port = RiskMonitor._aggregate(positions, cfg)
    assert len(port.alerts) == 1
    assert "组合浮盈" in port.alerts[0]


def test_exit_signal_ratio_triggers():
    positions = [
        _mk_pos("601939", 10.0, 100, 9.0, action="EXIT"),
        _mk_pos("600919", 10.0, 100, 10.0, action="HOLD"),
    ]
    cfg = PortfolioRiskConfig(enabled=True, exit_signal_ratio_max=0.30)
    port = RiskMonitor._aggregate(positions, cfg)
    assert len(port.alerts) == 1
    assert "EXIT 信号占比" in port.alerts[0]
    assert "50%" in port.alerts[0]


def test_thresholds_independent_only_violated_triggers():
    """单只权重超限但浮盈正常 → 只有 max_single_weight alert，pnl/exit 不连带"""
    positions = [
        _mk_pos("601066", 20.0, 1000, 21.0),   # mv=21000 占比高，浮盈 +5%
        _mk_pos("600919", 10.0, 100, 11.0),    # mv=1100，浮盈 +10%
    ]
    cfg = PortfolioRiskConfig(
        enabled=True,
        max_single_weight_pct=0.30,
        unrealized_pnl_floor_pct=-0.05,
        exit_signal_ratio_max=0.50,
    )
    port = RiskMonitor._aggregate(positions, cfg)
    assert len(port.alerts) == 1
    assert "单只权重" in port.alerts[0]


def test_null_threshold_disables_only_that_check():
    """单个阈值留 None → 该项 disabled，其他正常评估"""
    positions = [_mk_pos("601939", 10.0, 100, 8.0)]  # -20%
    cfg = PortfolioRiskConfig(
        enabled=True,
        max_single_weight_pct=None,           # disabled
        unrealized_pnl_floor_pct=-0.05,        # enabled，触发
        exit_signal_ratio_max=None,           # disabled
    )
    port = RiskMonitor._aggregate(positions, cfg)
    assert len(port.alerts) == 1
    assert "组合浮盈" in port.alerts[0]


def test_empty_positions_no_crash():
    cfg = PortfolioRiskConfig(enabled=True, max_single_weight_pct=0.30)
    port = RiskMonitor._aggregate([], cfg)
    assert isinstance(port, PortfolioRisk)
    assert port.alerts == []
