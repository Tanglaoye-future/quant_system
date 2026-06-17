"""CB 月度 rebalance signal — daily_cb 输出 BUY/SELL/HOLD 三栏的 payload builder.

设计 (PR9, 2026-06-17):
  - compute_target_portfolio (PR4) 已输出 kept/exited/entered 三栏, 等价 HOLD/SELL/BUY
  - PR9 不重做 diff 逻辑, 只做"payload 结构化 + mode 判定 + 控制台/JSON 渲染"
  - rebalance vs maintenance:
      * 月初前 5 天视为 rebalance window (PM 月初首日人工执行)
      * 之后为 maintenance window (BUY 信号显示但标"等月初执行", SELL 仍立即触发, HOLD 不变)
  - PR10 接 intraday_risk_check 后, maintenance 期 SELL 也会同步成实时告警

advisory_only 期 (PR8/PR9): JSON payload 三栏空持仓 = entered 走 cold start full top N,
PM 月初下单后录 journal_trades → 后续 daily 自动出真 diff.
"""
from __future__ import annotations

from datetime import date
from typing import Any


def is_rebalance_day(today: date) -> bool:
    """月初 rebalance window 判定 — 启发式: 每月前 5 天.

    Why 启发式: A 股月初第一个 trading day 通常在 1-3 号, 但跨春节/国庆假期可能延到 5-8 号.
    精确判定需 trading calendar, 但 advisory only 系统 PM 看 mode 标签自己拍板, 工具不必替 PM 决策.
    PR10+ 接 trading calendar 后可升级为"该月第一个 trading day == today" 精确判定.
    """
    return today.day <= 5


def build_rebalance_payload(
    *,
    portfolio_out: dict[str, Any],
    ranked: list[dict[str, Any]],
    redeem_active: set[str],
    is_rebalance: bool,
) -> dict[str, Any]:
    """把 compute_target_portfolio 输出 + ranked top 转成 BUY/SELL/HOLD 三栏 payload.

    Args:
        portfolio_out: compute_target_portfolio 返回 dict, 含 kept/exited/entered/target_weights
        ranked: daily_cb 的 advisory_entries (每条 dict 含 bond_code/bond_name/close/score/...)
        redeem_active: 强赎临近 (≤30d) 的 bond_code 集合
        is_rebalance: 是否 rebalance window (True=月初执行 / False=平日 maintenance)

    Returns dict:
        mode: "rebalance" | "maintenance"
        hold: [{bond_code, bond_name, dual_low_score, close, conversion_premium_rate, weight}]
        sell: [{bond_code, reason, urgent}]
        buy:  [{bond_code, bond_name, dual_low_score, close, conversion_premium_rate, weight, deferred}]
            * deferred=True 当 is_rebalance=False (BUY 等月初再执行)
        diff_summary: 计数三栏
    """
    ranked_map = {str(r["bond_code"]): r for r in ranked}

    target_weights = portfolio_out.get("target_weights", {})
    kept = portfolio_out.get("kept", [])
    exited = portfolio_out.get("exited", [])
    entered = portfolio_out.get("entered", [])

    hold = [
        {
            "bond_code": code,
            "bond_name": ranked_map.get(code, {}).get("bond_name", ""),
            "dual_low_score": ranked_map.get(code, {}).get("dual_low_score"),
            "close": ranked_map.get(code, {}).get("close"),
            "conversion_premium_rate": ranked_map.get(code, {}).get(
                "conversion_premium_rate"
            ),
            "weight": float(target_weights.get(code, 0.0)),
        }
        for code in kept
    ]

    sell = [
        {
            "bond_code": code,
            "reason": reason,
            # 强赎类 + 止损类 = urgent (无论 mode 都立即出场)
            "urgent": (reason in {"redeem_announced", "stop_loss"})
            or (code in redeem_active),
        }
        for code, reason in exited
    ]

    buy = [
        {
            "bond_code": code,
            "bond_name": ranked_map.get(code, {}).get("bond_name", ""),
            "dual_low_score": ranked_map.get(code, {}).get("dual_low_score"),
            "close": ranked_map.get(code, {}).get("close"),
            "conversion_premium_rate": ranked_map.get(code, {}).get(
                "conversion_premium_rate"
            ),
            "weight": float(target_weights.get(code, 0.0)),
            "deferred": not is_rebalance,
        }
        for code in entered
    ]

    return {
        "mode": "rebalance" if is_rebalance else "maintenance",
        "hold": hold,
        "sell": sell,
        "buy": buy,
        "diff_summary": {
            "n_hold": len(hold),
            "n_sell": len(sell),
            "n_sell_urgent": sum(1 for s in sell if s["urgent"]),
            "n_buy": len(buy),
            "n_buy_deferred": sum(1 for b in buy if b["deferred"]),
        },
    }
