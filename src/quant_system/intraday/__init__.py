"""盘中实时风控 (PR5 of docs/specs/position_v2_harness.md §6 + PR1/PR2/PR3 扩展)
+ T+1 开盘入场状态 (feat/t1-open-entry).

evaluate_alerts: 持仓告警 (proximity / break_* / portfolio_*); 纯函数;
evaluate_breakout_alerts: PR2 daily_screen_breakout 候选股盘中突破; 纯函数;
fetch_realtime_prices: akshare wrapper, 失败 / 缺失 → None;
run_once / run_loop: scripts/intraday/intraday_risk_check.py 调用入口;
PendingEntry / dump_pending_entries / load_pending_entries: T+1 入场锁.
"""
from quant_system.intraday.core import (
    AlertEvent,
    BreakoutCandidateQuote,
    BreakoutConfig,
    IntradayConfig,
    PortfolioSnapshot,
    PositionSnapshot,
    evaluate_alerts,
    evaluate_breakout_alerts,
    is_in_trading_window,
)
from quant_system.intraday.watchlist import (
    PendingEntry,
    PendingEntryManifest,
    Watchlist,
    WatchlistCandidate,
    dump_pending_entries,
    dump_watchlist,
    is_watchlist_stale,
    load_pending_entries,
    load_watchlist,
)

__all__ = [
    "AlertEvent",
    "BreakoutCandidateQuote",
    "BreakoutConfig",
    "IntradayConfig",
    "PendingEntry",
    "PendingEntryManifest",
    "PositionSnapshot",
    "PortfolioSnapshot",
    "Watchlist",
    "WatchlistCandidate",
    "dump_pending_entries",
    "dump_watchlist",
    "evaluate_alerts",
    "evaluate_breakout_alerts",
    "is_in_trading_window",
    "is_watchlist_stale",
    "load_pending_entries",
    "load_watchlist",
]
