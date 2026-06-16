"""CB double-low §1 评分 + §3 入场/持有/出场.

锁定 docs/specs/convertible_bond_sleeve.md §1 + §3.

出场优先级 (evaluate_holdings):
1. redeem_announced      — 持仓命中强赎事件
2. out_of_universe       — 持仓被 filter 砍出评分池
3. stop_loss             — close < stop_loss_close
4. dual_low_too_high     — score > exit_dual_low_threshold
5. out_of_top_band       — rank >= n_entry * n_hold_buffer
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pandas as pd

from quant_system.strategies.cb_double_low.universe.filter import (
    UniverseFilterConfig,
    filter_universe,
)


@dataclass(frozen=True)
class CBDoubleLowConfig:
    """CB 双低 v1 策略配置."""

    n_entry: int = 20
    n_hold_buffer: float = 1.5
    exit_dual_low_threshold: float = 150.0
    stop_loss_close: float = 85.0
    weight_scheme: str = "equal"
    filter_config: UniverseFilterConfig = field(default_factory=UniverseFilterConfig)


def score_dual_low(panel_slice: pd.DataFrame) -> pd.Series:
    """§1 双低评分: close + conversion_premium_rate."""
    return panel_slice["close"] + panel_slice["conversion_premium_rate"]


def select_entry(scored: pd.DataFrame, n: int) -> list[str]:
    """每日按 dual_low_score 升序取前 N. NaN score 自动排除."""
    return (
        scored.dropna(subset=["dual_low_score"])
        .nsmallest(n, "dual_low_score")["bond_code"]
        .tolist()
    )


def evaluate_holdings(
    current_holdings: list[str],
    scored: pd.DataFrame,
    config: CBDoubleLowConfig,
    redemption_today_codes: set[str],
) -> dict:
    """对已持仓评估保留 vs 出场.

    Returns:
        {"kept": [...], "exited": [(bond_code, reason), ...]}
    """
    n_keep_band = int(config.n_entry * config.n_hold_buffer)
    ranked = (
        scored.dropna(subset=["dual_low_score"])
        .sort_values("dual_low_score")
        .reset_index(drop=True)
    )
    rank_map = {code: i for i, code in enumerate(ranked["bond_code"])}
    close_map = dict(zip(scored["bond_code"], scored["close"]))
    score_map = dict(zip(scored["bond_code"], scored["dual_low_score"]))

    kept: list[str] = []
    exited: list[tuple[str, str]] = []
    for code in current_holdings:
        if code in redemption_today_codes:
            exited.append((code, "redeem_announced"))
            continue
        if code not in rank_map:
            exited.append((code, "out_of_universe"))
            continue
        if close_map.get(code, float("inf")) < config.stop_loss_close:
            exited.append((code, "stop_loss"))
            continue
        if score_map.get(code, float("inf")) > config.exit_dual_low_threshold:
            exited.append((code, "dual_low_too_high"))
            continue
        if rank_map[code] >= n_keep_band:
            exited.append((code, "out_of_top_band"))
            continue
        kept.append(code)
    return {"kept": kept, "exited": exited}


def compute_target_portfolio(
    universe: pd.DataFrame,
    panel_today: pd.DataFrame,
    redemption: pd.DataFrame,
    current_holdings: list[str],
    asof: date,
    config: CBDoubleLowConfig,
) -> dict:
    """端到端: filter → 评分 → 评估持仓 → 补足新仓 → 等权 target.

    Returns:
        {
          "asof": "YYYY-MM-DD",
          "filter_stats": {...},
          "kept": [...],
          "exited": [(code, reason), ...],
          "entered": [...],
          "target_weights": {code: 1/N, ...},
        }
    """
    filtered, stats = filter_universe(
        universe, panel_today, redemption, asof, config.filter_config
    )
    filtered = filtered.copy()
    filtered["dual_low_score"] = score_dual_low(filtered)

    redeem_codes: set[str] = set()
    if not redemption.empty and "status" in redemption.columns:
        redeem_codes = set(
            redemption[
                redemption["status"].isin(
                    config.filter_config.exclude_exit_statuses
                )
            ]["bond_code"]
        )

    holdings_eval = evaluate_holdings(
        current_holdings, filtered, config, redeem_codes
    )
    kept = holdings_eval["kept"]
    exited = holdings_eval["exited"]

    top_n = select_entry(filtered, config.n_entry)
    slots = max(config.n_entry - len(kept), 0)
    new_entries = [c for c in top_n if c not in kept][:slots]

    target_codes = kept + new_entries
    weight = 1.0 / config.n_entry if config.n_entry > 0 else 0.0
    target_weights = {code: weight for code in target_codes}

    return {
        "asof": str(asof),
        "filter_stats": stats,
        "kept": kept,
        "exited": exited,
        "entered": new_entries,
        "target_weights": target_weights,
    }
