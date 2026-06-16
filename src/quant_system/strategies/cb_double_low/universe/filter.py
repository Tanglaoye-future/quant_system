"""CB universe §2 filter — 排除强赎/到期近/小规模/深贴价/低评级.

锁定 docs/specs/convertible_bond_sleeve.md §2 五项规则.

Smoke test (2026-06-16) 实测 nuance 已落入设计:
- redeem.status 80% 空字符串 (in-table 但状态空), loader 已归一化 → universe.exit_status.
  本模块走 universe.exit_status 而非 redemption.status, 不直接撞这个坑.
- universe.scale_remain 经常 NaN, 不当作"低规模"砍 (数据缺失保守保留).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class UniverseFilterConfig:
    """支柱 1 + 2 联合的 universe 准入硬卡."""

    min_close: float = 80.0
    min_scale_remain_yi: float = 1.0
    min_years_to_maturity: float = 0.5
    min_rating: Optional[str] = None
    exclude_exit_statuses: tuple[str, ...] = ("已公告强赎", "公告要强赎")


_RATING_ORDER = {"AAA": 4, "AA+": 3, "AA": 2, "AA-": 1}


def filter_universe(
    universe: pd.DataFrame,
    panel_today: pd.DataFrame,
    redemption: pd.DataFrame,
    asof: date,
    config: UniverseFilterConfig = UniverseFilterConfig(),
) -> tuple[pd.DataFrame, dict]:
    """每日 asof 截面 filter.

    universe + panel_today inner join on bond_code, 依次砍 5 项规则.

    Args:
        universe: CBDataLoader.load_universe(asof) 输出.
        panel_today: panel 切到 asof 当日的子集 (bond_code/close/conversion_premium_rate).
        redemption: CBDataLoader.load_redemption_events(asof) 输出.
        asof: 截面日期.

    Returns:
        (filtered_df, stats_dict)
    """
    merged = universe.merge(
        panel_today[["bond_code", "close", "conversion_premium_rate"]],
        on="bond_code",
        how="inner",
    ).copy()
    initial = len(merged)
    stats: dict[str, int] = {"initial": initial}

    # 1. exit_status
    mask = ~merged["exit_status"].isin(config.exclude_exit_statuses)
    stats["dropped_redeem"] = int((~mask).sum())
    merged = merged[mask].copy()

    # 2. close < min_close
    mask = merged["close"] >= config.min_close
    stats["dropped_low_close"] = int((~mask).sum())
    merged = merged[mask].copy()

    # 3. 剩余规模: NaN 保留 (数据缺失保守)
    scale = pd.to_numeric(merged["scale_remain"], errors="coerce")
    mask = scale.isna() | (scale >= config.min_scale_remain_yi)
    stats["dropped_low_scale"] = int((~mask).sum())
    merged = merged[mask].copy()

    # 4. 剩余年限: 用 redemption.last_trading_date (优先) 或 maturity_date
    if not redemption.empty:
        red = redemption.copy()
        red["effective_end"] = red["last_trading_date"].fillna(red["maturity_date"])
        red = red.dropna(subset=["effective_end"])
        if not red.empty:
            asof_ts = pd.Timestamp(asof)
            red["years_left"] = (red["effective_end"] - asof_ts).dt.days / 365.25
            drop_codes = set(
                red[red["years_left"] < config.min_years_to_maturity]["bond_code"]
            )
            mask = ~merged["bond_code"].isin(drop_codes)
            stats["dropped_near_maturity"] = int((~mask).sum())
            merged = merged[mask].copy()
        else:
            stats["dropped_near_maturity"] = 0
    else:
        stats["dropped_near_maturity"] = 0

    # 5. 评级 (默认 None 不卡)
    if config.min_rating is not None:
        min_score = _RATING_ORDER.get(config.min_rating, 0)
        rating_scores = merged["credit_rating"].map(
            lambda r: _RATING_ORDER.get(r, 0)
        )
        mask = rating_scores >= min_score
        stats["dropped_low_rating"] = int((~mask).sum())
        merged = merged[mask].copy()
    else:
        stats["dropped_low_rating"] = 0

    stats["passed"] = len(merged)
    return merged.reset_index(drop=True), stats
