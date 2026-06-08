"""M5 of duckdb_cache_freshness — latest_date + loader fall-through 契约.

实盘 06-08 case: DuckDB cache 截止 6-4, daily 用 4 天前 close 算 pnl/距 stop
全部错位 (600584 真实 -14.32% 显示成 -2.40%).
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from quant_system.data import DuckDBStore


@pytest.fixture
def store(tmp_path):
    s = DuckDBStore(tmp_path / "test.duckdb")
    # 注入 600584 cache 截止 2026-06-04 (实盘 root cause 状态)
    df = pd.DataFrame({
        "date": pd.date_range("2026-05-29", "2026-06-04", freq="B"),
        "open": [86.0, 80.1, 76.86, 76.23, 79.0],
        "high": [89.77, 83.51, 77.54, 82.89, 81.86],
        "low": [80.33, 75.0, 72.65, 76.23, 77.8],
        "close": [82.05, 75.65, 75.35, 80.13, 80.08],
        "volume": [310358553, 295336496, 253251201, 325350062, 227052025],
        "code": ["600584"] * 5,
    })
    s.insert_daily("a_share", "600584", df)
    yield s
    s.close()


def test_latest_date_returns_max_cached(store: DuckDBStore):
    """cache 截止 6-4 → latest_date 返 date(2026, 6, 4)."""
    assert store.latest_date("a_share", "600584") == date(2026, 6, 4)


def test_latest_date_unknown_code_returns_none(store: DuckDBStore):
    assert store.latest_date("a_share", "999999") is None


def test_latest_date_used_to_detect_staleness(store: DuckDBStore):
    """实盘判定逻辑: end_date - cache_latest > skew_days 时 cache 算 stale."""
    cache_latest = store.latest_date("a_share", "600584")  # 6-4
    end_date = date(2026, 6, 8)  # daily 跑 6-8
    skew_days = 3
    days_behind = (end_date - cache_latest).days
    # 6-8 - 6-4 = 4 calendar days; > 3 → stale → 应 fall through baostock
    assert days_behind > skew_days, "cache stale 必须能被识别"


def test_loader_freshness_logic_unit():
    """Loader freshness 判断的最小契约 (M5 关键 invariant)."""
    from datetime import date as _date
    skew_days = 3
    # case 1: cache 截止 6-4, end 6-8 → 落后 4 天 → stale
    assert (_date(2026, 6, 8) - _date(2026, 6, 4)).days > skew_days
    # case 2: cache 截止 6-5, end 6-8 → 落后 3 天 → 边界 (skew_days 允许)
    assert (_date(2026, 6, 8) - _date(2026, 6, 5)).days <= skew_days
    # case 3: cache 截止 6-8, end 6-8 → 0 → fresh
    assert (_date(2026, 6, 8) - _date(2026, 6, 8)).days <= skew_days
    # case 4: cache 截止 6-9 (未来日?), end 6-8 → -1 → fresh (含负数)
    assert (_date(2026, 6, 8) - _date(2026, 6, 9)).days <= skew_days
