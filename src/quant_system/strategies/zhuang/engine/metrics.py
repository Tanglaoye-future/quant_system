"""
回测绩效计算（与 quant_system 同逻辑，独立实现，无依赖）.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant_system.strategies.zhuang.engine.position import ClosedTrade


def compute_metrics(
    trades: list[ClosedTrade],
    equity_curve: pd.Series,        # 每日净值（index=日期，值=账户总资产）
    initial_capital: float,
    risk_free_rate: float = 0.02,
) -> dict:
    """
    计算主要回测绩效指标.

    Returns dict with:
      total_return, annualized_return, sharpe_ratio, max_drawdown,
      win_rate, avg_pnl_pct, avg_win_pct, avg_loss_pct, profit_factor,
      total_trades, hold_days_avg
    """
    if not trades:
        return _empty_metrics()

    # ── 收益指标 ─────────────────────────────────────────────────────────────
    final_value = float(equity_curve.iloc[-1]) if len(equity_curve) else initial_capital
    total_return = (final_value - initial_capital) / initial_capital

    n_days = len(equity_curve)
    years = n_days / 252.0
    annualized_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0.0

    # ── 夏普比率 ──────────────────────────────────────────────────────────────
    daily_ret = equity_curve.pct_change().dropna()
    excess = daily_ret - risk_free_rate / 252
    sharpe = float(excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 0 else 0.0

    # ── 最大回撤 ─────────────────────────────────────────────────────────────
    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve - rolling_max) / rolling_max
    max_drawdown = float(drawdown.min())

    # ── 胜率 / 盈亏比 ────────────────────────────────────────────────────────
    pnl_pcts = [t.pnl_pct for t in trades]
    wins = [p for p in pnl_pcts if p > 0]
    losses = [p for p in pnl_pcts if p <= 0]
    win_rate = len(wins) / len(pnl_pcts) if pnl_pcts else 0.0
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = np.mean(losses) if losses else 0.0
    profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

    hold_days = [t.hold_days for t in trades]

    return {
        "total_return": round(total_return, 4),
        "annualized_return": round(annualized_return, 4),
        "sharpe_ratio": round(sharpe, 4),
        "max_drawdown": round(max_drawdown, 4),
        "win_rate": round(win_rate, 4),
        "avg_pnl_pct": round(np.mean(pnl_pcts), 4),
        "avg_win_pct": round(avg_win, 4),
        "avg_loss_pct": round(avg_loss, 4),
        "profit_factor": round(profit_factor, 4),
        "total_trades": len(trades),
        "hold_days_avg": round(np.mean(hold_days), 1) if hold_days else 0.0,
    }


def _empty_metrics() -> dict:
    return {
        "total_return": 0.0, "annualized_return": 0.0, "sharpe_ratio": 0.0,
        "max_drawdown": 0.0, "win_rate": 0.0, "avg_pnl_pct": 0.0,
        "avg_win_pct": 0.0, "avg_loss_pct": 0.0, "profit_factor": 0.0,
        "total_trades": 0, "hold_days_avg": 0.0,
    }
