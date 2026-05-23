"""
M4 — 组合层：在因子分排序之后，对「当日可买队列」做行业集中度 / 新开仓风险预算约束，
并在回测引擎里重排信号顺序（使前 slots 个为可行集，保持与 pending 逻辑兼容）。

因子侧离散度惩罚在 factors.score_universe（m4_factor_dispersion_lambda）。
换手惩罚在 BottomupTimingStrategy（m4_turnover_penalty + _m4_prev_top）。
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


@dataclass
class M4Config:
    m4_enabled: bool = False
    m4_max_same_industry: int = 0
    m4_new_risk_budget_frac: float = 0.0
    m4_factor_dispersion_lambda: float = 0.0
    m4_turnover_penalty: float = 0.0
    m4_turnover_top_n: int = 30


def m4_config_from_yaml(node: dict | None) -> M4Config:
    node = node or {}
    valid = {f.name for f in fields(M4Config)}
    kwargs = {k: v for k, v in node.items() if k in valid}
    return M4Config(**kwargs)


def _risk_frac(sig: "BuySignal") -> float:
    if sig.entry_price and sig.entry_price > 0 and sig.stop_loss is not None:
        return max(0.0, (float(sig.entry_price) - float(sig.stop_loss)) / float(sig.entry_price))
    return 0.0


def _industry(
    code: str,
    industry_map: dict[str, str] | None,
) -> str:
    if not industry_map:
        return ""
    return str(industry_map.get(code, "") or "")


def m4_prioritize_signals(
    signals: list["BuySignal"],
    positions: dict[str, "Position"],
    pending_buys: list["BuySignal"],
    slots: int,
    loader: "DataLoader",
    market: str,
    _day_str: str,
    cfg: M4Config,
    *,
    market_ctx: "Any" = None,    # Phase 2a: MarketContext, 旧调用 None 时按 market 名推默认
) -> list["BuySignal"]:
    """
    在保持相对得分顺序的前提下，将「能通过 M4 行业 / 风险预算」的信号排到前部，
    使 backtest 按顺序截取 slots 根 pending 时与 M4 一致。
    """
    if not cfg.m4_enabled or slots <= 0 or not signals:
        return signals

    max_same = int(cfg.m4_max_same_industry)
    industry_map: dict[str, str] | None = None
    # Phase 2a: 由 MarketContext.industry_concentration 决定，而非字符串硬比 'a_share'
    if market_ctx is not None:
        industry_enabled = bool(market_ctx.industry_concentration)
    else:
        # 旧调用兼容路径：保留原硬编码行为（仅 a_share 启用）
        industry_enabled = (market == "a_share")
    use_industry = industry_enabled and max_same > 0
    if use_industry:
        try:
            industry_map = loader.get_a_share_industry_map()
        except Exception:
            industry_map = {}
        if not industry_map:
            use_industry = False

    from collections import Counter

    ind_ct: Counter[str] = Counter()
    if use_industry:
        for pos in positions.values():
            ind = _industry(pos.symbol, industry_map)
            key = ind or "__NA__"
            ind_ct[key] += 1
        for pb in pending_buys:
            ind = _industry(pb.symbol, industry_map)
            key = ind or "__NA__"
            ind_ct[key] += 1

    budget = float(cfg.m4_new_risk_budget_frac)

    feasible: list[BuySignal] = []
    tail: list[BuySignal] = []
    cum_risk = 0.0
    held_syms = set(positions.keys())

    for sig in signals:
        if sig.symbol in held_syms:
            tail.append(sig)
            continue
        if len(feasible) >= slots:
            tail.append(sig)
            continue

        ok = True
        ind = _industry(sig.symbol, industry_map if use_industry else None)
        key = ind or "__NA__"
        if use_industry and ind_ct[key] >= max_same:
            ok = False
        rf = _risk_frac(sig)
        if ok and budget > 0 and cum_risk + rf > budget + 1e-12:
            ok = False

        if ok:
            feasible.append(sig)
            if use_industry:
                ind_ct[key] += 1
            cum_risk += rf
        else:
            tail.append(sig)

    return feasible + tail
