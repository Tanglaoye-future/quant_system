"""CBDataLoader — 可转债数据接口契约 (PR2 红灯阶段 stub).

本 PR 仅落契约 (类常量 + 方法签名), 所有方法 raise NotImplementedError.
tests/cb_double_low/test_loader.py 用 unittest.mock 替换 akshare 端点,
PR2 阶段预期全部失败 (红灯), PR3 完整实现后转绿.

契约源: docs/specs/convertible_bond_sleeve.md §3
Probe 依据: memory/cb_data_probe_2026-06.md
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd


class CBDataLoader:
    """可转债数据 loader 契约."""

    UNIVERSE_COLUMNS = (
        "bond_code",
        "bond_name",
        "stock_code",
        "stock_name",
        "listing_date",
        "delisting_date",
        "scale_remain",
        "credit_rating",
        "exit_status",
    )
    PANEL_COLUMNS = (
        "date",
        "bond_code",
        "close",
        "pure_bond_value",
        "conversion_value",
        "pure_bond_premium_rate",
        "conversion_premium_rate",
    )
    REDEMPTION_COLUMNS = (
        "bond_code",
        "bond_name",
        "announcement_date",
        "last_trading_date",
        "maturity_date",
        "redemption_price",
        "status",
    )
    SPOT_COLUMNS = (
        "bond_code",
        "bond_name",
        "close",
        "change_pct",
        "volume",
        "amount",
    )

    def __init__(self, cache_dir: Path, refresh_days: int = 1) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.refresh_days = int(refresh_days)

    def load_universe(self, asof: Optional[date] = None) -> pd.DataFrame:
        raise NotImplementedError("PR3 — bond_zh_cov + bond_cb_redeem_jsl merge")

    def load_panel(
        self,
        start: date,
        end: date,
        codes: Optional[list[str]] = None,
    ) -> pd.DataFrame:
        raise NotImplementedError(
            "PR3 — bond_zh_cov_value_analysis + DuckDB cache (cb_panel)"
        )

    def load_redemption_events(self, asof: Optional[date] = None) -> pd.DataFrame:
        raise NotImplementedError("PR3 — bond_cb_redeem_jsl + asof filter")

    def get_spot_today(self) -> pd.DataFrame:
        raise NotImplementedError("PR3 — bond_zh_hs_cov_spot")

    def close(self) -> None:
        pass
