"""
M5 — 出场原因分层（与 exit_events / trades 的 reason 字符串对齐，供汇总与审计）。

约定：layer 为稳定英文枚举，便于 JSON/CSV 聚合；原始 reason 仍完整保留。
"""
from __future__ import annotations

LAYER_STOP_TRAIL = "STOP_TRAIL"
LAYER_STOP_TREND = "STOP_TREND"
LAYER_TAKE_PROFIT = "TAKE_PROFIT"
LAYER_OVERBOUGHT = "OVERBOUGHT"
LAYER_TIME_STOP = "TIME_STOP"
LAYER_REGIME = "REGIME"
LAYER_FORCED_CLOSE = "FORCED_CLOSE"
LAYER_OTHER = "OTHER"


def exit_layer_from_reason(reason: str) -> str:
    """由 timing.exit_signal* 返回的 reason 映射到 M5 分层。"""
    r = (reason or "").strip().lower()
    if r.startswith("trailing_stop"):
        return LAYER_STOP_TRAIL
    if r.startswith("break_ma"):
        return LAYER_STOP_TREND
    if r.startswith("take_profit"):
        return LAYER_TAKE_PROFIT
    if r.startswith("overbought"):
        return LAYER_OVERBOUGHT
    if r.startswith("time_stop"):
        return LAYER_TIME_STOP
    if "m5_regime_exit" in r or r.startswith("regime"):
        return LAYER_REGIME
    if "backtest_end" in r:
        return LAYER_FORCED_CLOSE
    if r in ("持有", "hold", "") or "not in enriched" in r or "insufficient" in r:
        return ""
    return LAYER_OTHER
