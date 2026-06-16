"""Universe §2 filter 单元测试 (PR4).

锁定 docs/specs/convertible_bond_sleeve.md §2 五项排除规则:
- 已公告强赎 / 公告要强赎
- 剩余年限 < 0.5 年
- 剩余规模 < 1 亿
- 债现价 < 80
- 评级 < AA-（默认 None 不卡）

Smoke test (2026-06-16) 实测 nuance 已落入设计:
- redeem status 80% 空字符串 → loader 已归一化, filter 走 universe.exit_status
- universe scale_remain 经常 NaN → 不当作"低规模"砍 (保守保留)
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from quant_system.strategies.cb_double_low.universe.filter import (
    UniverseFilterConfig,
    filter_universe,
)


@pytest.fixture
def sample_universe() -> pd.DataFrame:
    """5 只债, 覆盖 active / 已公告强赎 / 公告要强赎 / 低规模 / NaN 规模."""
    return pd.DataFrame(
        {
            "bond_code": ["100001", "100002", "100003", "100004", "100005"],
            "bond_name": ["A", "B", "C", "D", "E"],
            "stock_code": ["6000{}".format(i) for i in range(1, 6)],
            "stock_name": ["a", "b", "c", "d", "e"],
            "listing_date": pd.to_datetime(["2020-01-01"] * 5),
            "delisting_date": [pd.NaT] * 5,
            "scale_remain": [10.0, 5.0, 3.0, 0.5, None],  # 100004 低规模; 100005 NaN
            "credit_rating": ["AAA", "AA+", "AA", "AA-", "A"],
            "exit_status": [
                "active",
                "已公告强赎",   # 排除
                "公告要强赎",   # 排除
                "active",
                "active",
            ],
        }
    )


@pytest.fixture
def sample_panel_today() -> pd.DataFrame:
    """asof 当日切片. 100005 close=75 (低于 80 排除)."""
    return pd.DataFrame(
        {
            "bond_code": ["100001", "100002", "100003", "100004", "100005"],
            "close": [110.0, 95.0, 88.0, 90.0, 75.0],
            "conversion_premium_rate": [10.0, 5.0, 20.0, 30.0, 5.0],
        }
    )


@pytest.fixture
def sample_redemption() -> pd.DataFrame:
    """100002 已公告强赎 last_trading_date 2026-07-01 (近), 100004 即将到期."""
    return pd.DataFrame(
        {
            "bond_code": ["100002", "100004"],
            "bond_name": ["B", "D"],
            "announcement_date": [pd.NaT, pd.NaT],
            "last_trading_date": pd.to_datetime(["2026-07-01", "2026-08-01"]),
            "maturity_date": pd.to_datetime(["2027-01-01", "2026-10-01"]),
            "redemption_price": [100.5, 100.0],
            "status": ["已公告强赎", ""],  # 100004 空字符串 (smoke 实测占 80%)
        }
    )


def test_filter_drops_redeem_announced(
    sample_universe, sample_panel_today, sample_redemption
):
    """exit_status='已公告强赎' / '公告要强赎' 必须排除."""
    filtered, stats = filter_universe(
        sample_universe,
        sample_panel_today,
        sample_redemption,
        asof=date(2026, 6, 16),
        config=UniverseFilterConfig(),
    )
    codes = set(filtered["bond_code"])
    assert "100002" not in codes, "已公告强赎必须排除"
    assert "100003" not in codes, "公告要强赎必须排除"
    assert stats["dropped_redeem"] == 2


def test_filter_drops_low_close(
    sample_universe, sample_panel_today, sample_redemption
):
    """close < min_close (默认 80) 必须排除."""
    filtered, stats = filter_universe(
        sample_universe,
        sample_panel_today,
        sample_redemption,
        asof=date(2026, 6, 16),
        config=UniverseFilterConfig(min_close=80.0),
    )
    codes = set(filtered["bond_code"])
    assert "100005" not in codes, "close=75 < 80 必须排除"
    assert stats["dropped_low_close"] >= 1


def test_filter_drops_low_scale_remain(
    sample_universe, sample_panel_today, sample_redemption
):
    """scale_remain < 1 亿必须排除 (100004 = 0.5 亿)."""
    filtered, stats = filter_universe(
        sample_universe,
        sample_panel_today,
        sample_redemption,
        asof=date(2026, 6, 16),
        config=UniverseFilterConfig(min_scale_remain_yi=1.0),
    )
    codes = set(filtered["bond_code"])
    assert "100004" not in codes, "scale_remain=0.5 < 1.0 亿必须排除"
    assert stats["dropped_low_scale"] >= 1


def test_filter_keeps_scale_remain_nan(
    sample_universe, sample_panel_today, sample_redemption
):
    """scale_remain NaN (数据缺失) 不应当"低规模"砍 — 保守保留.

    Smoke test 实测: universe.scale_remain 经常 NaN, 砍掉等于砍掉大半 universe.
    """
    filtered, _ = filter_universe(
        sample_universe,
        sample_panel_today,
        sample_redemption,
        asof=date(2026, 6, 16),
        config=UniverseFilterConfig(min_close=70.0),  # 放宽 close 让 100005 进
    )
    codes = set(filtered["bond_code"])
    assert "100005" in codes, "scale_remain NaN 必须保留 (数据缺失保守)"


def test_filter_drops_near_maturity(
    sample_universe, sample_panel_today, sample_redemption
):
    """剩余年限 < 0.5 年必须排除 (100002 last_trading 2026-07-01 距 06-16 ≈ 0.04 年)."""
    filtered, stats = filter_universe(
        sample_universe,
        sample_panel_today,
        sample_redemption,
        asof=date(2026, 6, 16),
        config=UniverseFilterConfig(min_years_to_maturity=0.5),
    )
    codes = set(filtered["bond_code"])
    # 100002 已被 exit_status 砍掉, 100004 距 last_trading=2026-08-01 也 < 0.5 年应砍
    assert "100004" not in codes, "100004 last_trading 2026-08-01 距 asof 06-16 < 0.5 年"


def test_filter_stats_count_total(
    sample_universe, sample_panel_today, sample_redemption
):
    """stats dict 必须含 initial / passed / 各 dropped_*."""
    _, stats = filter_universe(
        sample_universe,
        sample_panel_today,
        sample_redemption,
        asof=date(2026, 6, 16),
        config=UniverseFilterConfig(),
    )
    for key in [
        "initial",
        "passed",
        "dropped_redeem",
        "dropped_low_close",
        "dropped_low_scale",
        "dropped_near_maturity",
        "dropped_low_rating",
    ]:
        assert key in stats, f"stats 缺字段 {key}"
    assert stats["initial"] == 5
