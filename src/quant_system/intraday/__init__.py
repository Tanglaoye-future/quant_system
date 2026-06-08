"""盘中实时风控 (PR5 of docs/specs/position_v2_harness.md §6)。

evaluate_alerts: 纯函数，喂 PositionRisk-like list + cfg → list[AlertEvent]，便于单测；
fetch_realtime_prices: akshare wrapper，失败 / 缺失 → None；
run_once / run_loop: scripts/intraday/intraday_risk_check.py 调用入口。
"""
from quant_system.intraday.core import (
    AlertEvent,
    IntradayConfig,
    PositionSnapshot,
    PortfolioSnapshot,
    evaluate_alerts,
    is_in_trading_window,
)

__all__ = [
    "AlertEvent",
    "IntradayConfig",
    "PositionSnapshot",
    "PortfolioSnapshot",
    "evaluate_alerts",
    "is_in_trading_window",
]
