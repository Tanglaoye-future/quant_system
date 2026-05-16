"""
持仓监控模块.

每日运行：检查现有期权仓位，输出需要操作的提醒。

出场规则（与 config 对齐）：
  - 权利金盈利 ≥ 100% → 止盈
  - 权利金亏损 ≥ 50%  → 止损
  - 剩余 DTE ≤ 21     → 评估滚仓
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quant_system.strategies.options.broker.ibkr import IBKRClient


@dataclass
class PositionAlert:
    code: str           # HOLD / TAKE_PROFIT / STOP_LOSS / ROLL_SOON
    symbol: str
    expiry: str
    strike: float
    right: str
    position: int       # 持仓张数（正=多，负=空）
    avg_cost: float     # 平均成本（每股）
    current_mid: float  # 当前中间价
    pnl_pct: float      # 盈亏百分比
    dte: int
    message: str


def check_positions(
    client: "IBKRClient",
    symbol: str = "QQQ",
    profit_target_mult: float = 2.0,
    stop_loss_mult: float = 0.50,
    dte_warning: int = 21,
) -> list[PositionAlert]:
    """
    拉取当前期权持仓，返回需要操作的提醒列表.
    """
    positions = client.get_option_positions(symbol)
    if not positions:
        return []

    alerts: list[PositionAlert] = []
    today = datetime.now().date()

    for pos in positions:
        expiry = pos["expiry"]
        strike = pos["strike"]
        right = pos["right"]
        avg_cost = pos["avg_cost"] / 100  # IBKR 返回的是每合约成本，除以100得每股
        position_size = pos["position"]

        # 计算 DTE
        try:
            exp_dt = datetime.strptime(expiry[:8], "%Y%m%d").date()
            dte = (exp_dt - today).days
        except Exception:
            dte = 0

        # 获取当前报价
        quote = client.get_option_quote(symbol, expiry[:8], strike, right)
        if quote is None:
            continue

        current_mid = quote.mid
        if avg_cost <= 0 or current_mid <= 0:
            continue

        # 对于多头头寸（买入期权）
        if position_size > 0:
            pnl_pct = (current_mid - avg_cost) / avg_cost

            if pnl_pct >= profit_target_mult - 1.0:
                code = "TAKE_PROFIT"
                msg = f"盈利 {pnl_pct*100:+.1f}% ≥ 目标 {(profit_target_mult-1)*100:.0f}% → 建议平仓止盈"
            elif pnl_pct <= -(1.0 - stop_loss_mult):
                code = "STOP_LOSS"
                msg = f"亏损 {pnl_pct*100:+.1f}% ≥ 止损线 {(1-stop_loss_mult)*100:.0f}% → 立即平仓"
            elif dte <= dte_warning:
                code = "ROLL_SOON"
                msg = f"剩余 {dte} DTE ≤ {dte_warning} → 评估滚仓至下一个月"
            else:
                code = "HOLD"
                msg = f"持仓正常  PnL {pnl_pct*100:+.1f}%  DTE {dte}"

            alerts.append(PositionAlert(
                code=code, symbol=symbol, expiry=expiry[:8],
                strike=strike, right=right, position=position_size,
                avg_cost=avg_cost, current_mid=current_mid,
                pnl_pct=round(pnl_pct, 4), dte=dte, message=msg,
            ))

    return alerts
