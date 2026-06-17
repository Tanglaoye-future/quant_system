"""CB 双低 sleeve journal facade — 复用 equity_factor 的 Journal 表族.

设计决策 (PR8, 2026-06-16):
  - 不新建 cb_trades 表; 复用 journal_trades (含 strategy 列, 已有 entry_features JSONB).
  - 沿用 [[project-north-star]] 多策略共享 ledger 的思路:
      strategy='cb_double_low', market='cb_a', symbol=bond_code (6 位数字).
  - RiskMonitor 已按 (market, strategy) filter (equity_factor/risk/monitor.py:147),
    串台风险已消, zhuang 当年独立 ledger 的核心顾虑不再成立.
  - CB 特有指标 (dual_low_score / conversion_premium / scale / rating / redeem_date)
    全部走 entry_features JSONB, schema 零变更, 无需 alembic migration.

PR8 范围:
  - 提供 CB 语义的 API + 常量 (供 PR9+ rebalance signal / PR10 实时风控调用)
  - 不在 daily_cb.py 中实际写 journal_trades (advisory_only 期, 由 PM 月初人工 rebalance 时录入)
"""
from __future__ import annotations

from datetime import date as _date
from typing import Any, Optional

# 复用 equity_factor 的 Journal 实现 — 同表族, 通过 strategy 列隔离
from quant_system.strategies.equity_factor.journal.journal import Journal, TradeOpen

__all__ = [
    "Journal",
    "TradeOpen",
    "CB_STRATEGY",
    "CB_MARKET",
    "build_cb_entry_features",
    "build_cb_trade_open",
    "list_open_cb_holdings",
]

# CB sleeve 在 journal_trades 中的固定 tag
CB_STRATEGY = "cb_double_low"
CB_MARKET = "cb_a"  # 区分 equity 的 a_share / hk_share / us_share


def build_cb_entry_features(
    *,
    rank: int,
    dual_low_score: float,
    close: float,
    conversion_premium_rate: float,
    scale_remain_yi: Optional[float] = None,
    rating: Optional[str] = None,
    years_to_maturity: Optional[float] = None,
    pure_bond_premium_rate: Optional[float] = None,
    last_trading_date: Optional[Any] = None,
) -> dict[str, Any]:
    """构造 CB entry_features JSONB payload.

    self_learning_pipeline L2 retrospective 用这些字段做 winner-vs-loser 分桶:
      - dual_low_score / conversion_premium_rate / rank 分位
      - scale_remain_yi (流动性带) / rating (信用带)
      - years_to_maturity (久期带)
      - last_trading_date (距强赎日) → 入场时 vs 出场时差值反映"强赎风险吃了多少"
    """
    return {
        "rank_at_entry": int(rank),
        "dual_low_score": float(dual_low_score),
        "close_at_entry": float(close),
        "conversion_premium_rate": float(conversion_premium_rate),
        "scale_remain_yi": (
            float(scale_remain_yi) if scale_remain_yi is not None else None
        ),
        "rating": str(rating) if rating is not None else None,
        "years_to_maturity": (
            float(years_to_maturity) if years_to_maturity is not None else None
        ),
        "pure_bond_premium_rate": (
            float(pure_bond_premium_rate) if pure_bond_premium_rate is not None else None
        ),
        "last_trading_date": (
            str(last_trading_date) if last_trading_date is not None else None
        ),
    }


def build_cb_trade_open(
    *,
    bond_code: str,
    bond_name: Optional[str],
    entry_date: Any,
    entry_price: float,
    entry_size: int,
    dual_low_score: float,
    rank: int,
    conversion_premium_rate: float,
    stop_loss_close: float = 85.0,
    scale_remain_yi: Optional[float] = None,
    rating: Optional[str] = None,
    years_to_maturity: Optional[float] = None,
    pure_bond_premium_rate: Optional[float] = None,
    last_trading_date: Optional[Any] = None,
    notes: Optional[str] = None,
) -> TradeOpen:
    """从 CB 语义参数构造一个 TradeOpen, 供 PR9+ rebalance 时调用 journal.open_trade().

    note: take_profit_price 留 None — CB 出场不是固定 TP, 是 dual_low_score>180 或强赎.
    """
    features = build_cb_entry_features(
        rank=rank,
        dual_low_score=dual_low_score,
        close=entry_price,
        conversion_premium_rate=conversion_premium_rate,
        scale_remain_yi=scale_remain_yi,
        rating=rating,
        years_to_maturity=years_to_maturity,
        pure_bond_premium_rate=pure_bond_premium_rate,
        last_trading_date=last_trading_date,
    )
    return TradeOpen(
        symbol=str(bond_code),
        market=CB_MARKET,
        strategy=CB_STRATEGY,
        entry_date=str(entry_date) if not isinstance(entry_date, str) else entry_date,
        entry_price=float(entry_price),
        entry_size=int(entry_size),
        entry_score=float(dual_low_score),  # 与 equity entry_score 字段语义对齐
        stop_loss_price=float(stop_loss_close),
        take_profit_price=None,  # CB 出场是 score/强赎, 不是固定 TP
        reason_topdown=None,
        reason_bottomup=f"dual_low_score={dual_low_score:.2f} rank={rank} premium={conversion_premium_rate:+.2f}%",
        reason_catalyst=None,
        reason_timing="monthly_rebalance",
        notes=notes if notes is not None else (bond_name or ""),
        entry_features=features,
    )


def list_open_cb_holdings(journal: Journal) -> list[str]:
    """从 journal_trades 反查 CB sleeve 当前未平仓的 bond_code 列表.

    PR9 月度 rebalance signal 入口: daily_cb 跑批前调本函数拿到 current_holdings,
    传入 compute_target_portfolio 算 BUY/SELL/HOLD diff.

    advisory_only 期 PM 未下单 → 返回空 list, compute_target_portfolio 走 cold start.
    PR9 月初首次 rebalance 后 PM 录 journal_trades → 后续 daily 自动看到真持仓.
    """
    rows = journal.list_open(market=CB_MARKET, strategy=CB_STRATEGY)
    return [r["symbol"] for r in rows]
