"""回测性能指标计算."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BacktestMetrics:
    # 交易统计
    n_trades: int = 0
    win_rate: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    win_loss_ratio: float = 0.0
    avg_hold_days: float = 0.0

    # 收益与风险
    total_return: float = 0.0
    annual_return: float = 0.0
    annual_volatility: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    calmar_ratio: float = 0.0

    # 基准对比
    benchmark_total_return: float = 0.0
    excess_return: float = 0.0          # total_return - benchmark_total_return


def compute_metrics(
    equity: pd.Series,
    closed_trades: list,
    benchmark: pd.Series | None = None,
    risk_free_rate: float = 0.02,
) -> BacktestMetrics:
    """equity: 每日净值 series, index 是日期; closed_trades: list[ClosedTrade]"""
    m = BacktestMetrics()
    if equity.empty or len(equity) < 2:
        return m

    initial = float(equity.iloc[0])
    final = float(equity.iloc[-1])
    m.total_return = final / initial - 1.0

    # 年化 (按 252 个交易日)
    n_days = len(equity)
    years = n_days / 252.0
    m.annual_return = (final / initial) ** (1.0 / years) - 1.0 if years > 0 else 0.0

    # 日收益序列
    daily_ret = equity.pct_change().dropna()
    m.annual_volatility = float(daily_ret.std() * np.sqrt(252))

    # Sharpe (扣无风险)
    excess_daily = daily_ret - risk_free_rate / 252
    sd = float(excess_daily.std())
    m.sharpe_ratio = float(excess_daily.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0

    # 最大回撤
    cummax = equity.cummax()
    drawdown = (equity - cummax) / cummax
    m.max_drawdown = float(drawdown.min())

    m.calmar_ratio = m.annual_return / abs(m.max_drawdown) if m.max_drawdown < 0 else 0.0

    # 交易统计
    if closed_trades:
        m.n_trades = len(closed_trades)
        wins = [t.pnl_pct for t in closed_trades if t.pnl_pct > 0]
        losses = [t.pnl_pct for t in closed_trades if t.pnl_pct <= 0]
        m.win_rate = len(wins) / len(closed_trades)
        m.avg_win_pct = float(np.mean(wins)) if wins else 0.0
        m.avg_loss_pct = float(np.mean(losses)) if losses else 0.0
        m.win_loss_ratio = abs(m.avg_win_pct / m.avg_loss_pct) if m.avg_loss_pct < 0 else float("inf")
        m.avg_hold_days = float(np.mean([t.hold_days for t in closed_trades]))

    if benchmark is not None and len(benchmark) >= 2:
        b_ret = float(benchmark.iloc[-1] / benchmark.iloc[0] - 1.0)
        m.benchmark_total_return = b_ret
        m.excess_return = m.total_return - b_ret

    return m


def check_admission(
    metrics: BacktestMetrics,
    min_sharpe: float = 0.5,
    max_drawdown: float = 0.25,
    min_win_rate: float = 0.40,
) -> tuple[bool, list[str]]:
    """准入门槛检查. 返回 (pass, [失败原因])."""
    fails = []
    if metrics.sharpe_ratio < min_sharpe:
        fails.append(f"Sharpe {metrics.sharpe_ratio:.2f} < 门槛 {min_sharpe}")
    if abs(metrics.max_drawdown) > max_drawdown:
        fails.append(f"最大回撤 {metrics.max_drawdown*100:.2f}% 超过门槛 {max_drawdown*100:.0f}%")
    if metrics.win_rate < min_win_rate:
        fails.append(f"胜率 {metrics.win_rate*100:.2f}% < 门槛 {min_win_rate*100:.0f}%")
    if metrics.n_trades < 10:
        fails.append(f"样本不足: 仅 {metrics.n_trades} 笔交易")
    return (len(fails) == 0, fails)
