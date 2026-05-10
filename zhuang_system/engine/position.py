"""
持仓模型.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Position:
    """单笔持仓."""
    code: str
    entry_date: str
    entry_price: float
    size: int                    # 持仓股数
    atr_at_entry: float          # 入场时的 ATR(14)，用于止损计算
    stop_loss_price: float       # 止损价（固定，入场后不移动）
    take_profit_price: float     # 止盈目标价
    accumulation_score: float = 0.0
    phase: str = "A"
    entry_reason: str = ""


@dataclass
class ClosedTrade:
    """已平仓交易记录."""
    code: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    size: int
    pnl: float                   # 净盈亏（扣手续费）
    pnl_pct: float               # 收益率
    hold_days: int
    exit_reason: str
    accumulation_score: float = 0.0
    phase: str = "A"
