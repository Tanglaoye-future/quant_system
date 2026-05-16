"""
出场信号模块.

庄股策略出场优先级（高 → 低）:
  1. 止损（硬止损）     : close <= entry_price - min(atr_mult×ATR, max_stop_pct×entry)
  2. 动量早止           : 持有≥3日且从入场价下跌≥momentum_stop_pct → 提前出场
  3. 时间止损（动态）   : 持有≥max_hold_days，若浮盈≥extend_profit_pct则延至extend_hold_days
  4. 止盈               : close >= entry_price × (1 + take_profit_pct)
  5. 派发信号           : 换手率 > distribution_thresh 且 收盘未创持仓新高
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class ExitSignal:
    """出场信号."""
    code: str
    date: str
    action: str          # "EXIT" | "HOLD"
    reason: str = ""
    exit_price: float = 0.0


def check_exit_signal(
    code: str,
    df_since_entry: pd.DataFrame,
    entry_price: float,
    entry_date: str,
    atr_at_entry: float,
    stop_loss_atr_mult: float = 2.0,
    max_stop_loss_pct: float = 0.06,        # P0: 单笔最大止损上限6%
    momentum_stop_pct: float = 0.05,        # P0: 持有≥3日跌-5%即提前离场
    take_profit_pct: float = 0.15,
    max_hold_days: int = 15,
    extend_hold_days: int = 25,             # P3: 浮盈≥extend_profit_pct时延长持有
    extend_profit_pct: float = 0.05,        # P3: 触发延长持有的浮盈门槛
    distribution_turnover_thresh: float = 8.0,
) -> ExitSignal:
    if df_since_entry.empty:
        return ExitSignal(code=code, date=entry_date, action="HOLD", reason="no_data")

    today = df_since_entry.iloc[-1]
    today_date = str(today["date"])[:10]
    close = float(today["close"])
    hold_days = len(df_since_entry) - 1

    # ── 1. 止损：ATR止损 与 固定比例止损 取较宽者（但不超过max_stop_loss_pct）
    atr_stop = entry_price - stop_loss_atr_mult * atr_at_entry
    pct_stop = entry_price * (1.0 - max_stop_loss_pct)
    stop_loss_price = max(atr_stop, pct_stop)   # 取两者中较高的（更严格）
    if close <= stop_loss_price:
        return ExitSignal(
            code=code, date=today_date, action="EXIT",
            reason=f"stop_loss: close={close:.2f} <= stop={stop_loss_price:.2f}",
            exit_price=close,
        )

    # ── 2. 动量早止（P0新增）：持有≥3日，从入场价跌幅超过momentum_stop_pct
    if hold_days >= 3:
        drawdown_from_entry = (close - entry_price) / entry_price
        if drawdown_from_entry <= -momentum_stop_pct:
            return ExitSignal(
                code=code, date=today_date, action="EXIT",
                reason=(
                    f"momentum_stop: drop={drawdown_from_entry*100:.1f}% "
                    f"<= -{momentum_stop_pct*100:.0f}% from entry"
                ),
                exit_price=close,
            )

    # ── 3. 时间止损（动态，P3）
    float_pnl = (close - entry_price) / entry_price
    if hold_days >= max_hold_days:
        if float_pnl >= extend_profit_pct and hold_days < extend_hold_days:
            # 浮盈≥5%，延长持有
            pass
        else:
            return ExitSignal(
                code=code, date=today_date, action="EXIT",
                reason=f"time_stop: {hold_days}d >= max={max_hold_days}d (float={float_pnl*100:.1f}%)",
                exit_price=close,
            )

    # ── 4. 止盈
    take_profit_price = entry_price * (1.0 + take_profit_pct)
    if close >= take_profit_price:
        return ExitSignal(
            code=code, date=today_date, action="EXIT",
            reason=f"take_profit: close={close:.2f} >= target={take_profit_price:.2f}",
            exit_price=close,
        )

    # ── 5. 派发信号（持有≥2日后生效）
    if hold_days >= 2 and "turnover_rate" in df_since_entry.columns:
        turnover = pd.to_numeric(today.get("turnover_rate", 0), errors="coerce")
        if not pd.isna(turnover) and turnover > distribution_turnover_thresh:
            high_since_entry = df_since_entry["close"].astype(float).max()
            if close < high_since_entry:
                return ExitSignal(
                    code=code, date=today_date, action="EXIT",
                    reason=(
                        f"distribution: turnover={turnover:.3f}>{distribution_turnover_thresh}"
                        f" close={close:.2f}<high={high_since_entry:.2f}"
                    ),
                    exit_price=close,
                )

    return ExitSignal(code=code, date=today_date, action="HOLD", reason="持有")
