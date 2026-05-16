"""
行权价选择器 & 仓位计算.

核心函数：
  find_best_spread()  →  给定期权链 + 目标 Delta，找最优 Bull Call Spread
  size_position()     →  根据账户规模 + 净权利金，计算合约张数
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from quant_system.strategies.options.broker.ibkr import IBKRClient, OptionQuote, SpreadQuote


def find_best_spread(
    client: "IBKRClient",
    symbol: str,
    chain: dict[str, list[float]],   # {expiry: [strikes]}
    current_price: float,
    long_delta_target: float = 0.45,
    short_delta_target: float = 0.27,
    min_spread_width_pct: float = 0.025,
    max_bid_ask_pct: float = 0.06,
) -> Optional["SpreadQuote"]:
    """
    遍历期权链，找到最符合目标 Delta 的 Bull Call Spread。

    策略：
      1. 选 DTE 居中的到期日（避免最短/最长）
      2. 买入腿：离目标 Delta 最近的行权价
      3. 卖出腿：买入腿上方，离目标 Delta 最近的行权价
      4. 验证流动性（bid-ask 价差）
    """
    from quant_system.strategies.options.broker.ibkr import SpreadQuote

    if not chain:
        return None

    # 选 DTE 居中的到期日
    expiries = sorted(chain.keys())
    expiry = expiries[len(expiries) // 2]
    strikes = chain[expiry]

    min_width = current_price * min_spread_width_pct

    # 候选行权价：在当前价附近 ±15%
    candidates = [s for s in strikes
                  if current_price * 0.85 <= s <= current_price * 1.15]
    if not candidates:
        return None

    print(f"[selector] 到期日: {expiry}，候选行权价: {len(candidates)} 个", flush=True)

    # 获取所有候选期权报价（批量，减少请求次数）
    quotes: dict[float, "OptionQuote"] = {}
    for strike in candidates:
        q = client.get_option_quote(symbol, expiry, strike, "C")
        if q and q.mid > 0 and q.bid_ask_spread_pct <= max_bid_ask_pct:
            quotes[strike] = q
        # 避免 IBKR 请求限速
        import time
        time.sleep(0.3)

    if len(quotes) < 2:
        print("[selector] 有效报价不足，无法构建价差", flush=True)
        return None

    # 找买入腿（Delta 最接近 long_delta_target）
    long_candidates = {
        s: q for s, q in quotes.items() if q.delta > 0
    }
    if not long_candidates:
        return None

    long_strike = min(long_candidates,
                      key=lambda s: abs(long_candidates[s].delta - long_delta_target))
    long_q = long_candidates[long_strike]

    # 找卖出腿（行权价 > 买入腿，Delta 最接近 short_delta_target）
    short_candidates = {
        s: q for s, q in quotes.items()
        if s > long_strike and (s - long_strike) >= min_width
    }
    if not short_candidates:
        print(f"[selector] 找不到合适的卖出腿（买入腿={long_strike}，最小宽度={min_width:.1f}）", flush=True)
        return None

    short_strike = min(short_candidates,
                       key=lambda s: abs(short_candidates[s].delta - short_delta_target))
    short_q = short_candidates[short_strike]

    # 构建 SpreadQuote
    net_debit = round(long_q.mid - short_q.mid, 2)
    if net_debit <= 0:
        return None
    spread_width = short_strike - long_strike
    max_profit = round(spread_width - net_debit, 2)
    breakeven = round(long_strike + net_debit, 2)
    profit_ratio = round(max_profit / net_debit, 2) if net_debit > 0 else 0.0

    return SpreadQuote(
        long_leg=long_q,
        short_leg=short_q,
        net_debit=net_debit,
        max_profit=max_profit,
        max_loss=net_debit,
        breakeven=breakeven,
        spread_width=spread_width,
        profit_ratio=profit_ratio,
    )


def size_position(
    net_debit_per_contract: float,   # 每张合约净权利金（美元）
    account_net_liq: float,
    risk_pct: float = 0.03,
    min_contracts: int = 1,
    max_contracts: int = 5,
) -> dict:
    """
    计算合约张数和实际风险金额.

    1张合约 = 100 股 → 每张最大亏损 = net_debit × 100
    """
    risk_budget = account_net_liq * risk_pct
    cost_per_contract = net_debit_per_contract * 100  # 每张美元成本

    if cost_per_contract <= 0:
        return {"contracts": 0, "total_risk": 0.0, "risk_pct_actual": 0.0}

    contracts = max(min_contracts, min(max_contracts, int(risk_budget / cost_per_contract)))
    total_risk = round(contracts * cost_per_contract, 2)
    risk_pct_actual = round(total_risk / account_net_liq * 100, 2)

    return {
        "contracts": contracts,
        "cost_per_contract": round(cost_per_contract, 2),
        "total_risk": total_risk,
        "risk_pct_actual": risk_pct_actual,
        "risk_budget": round(risk_budget, 2),
    }
