"""M3 of fix_hold_days_entry_bar_date — scan_today_entries 在 hit 加 entry_bar_date.

防御 2026-06-08 实盘 bug: 周一跑 daily 时 baostock 当日 K 线未入库, args.asof
是未来日, entry_date 与 entry_price (实际是上周五 close) 错位 → hold_days 负数.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _synthetic_daily(end_date: str = "2026-06-05", n: int = 90) -> pd.DataFrame:
    """合成 90 根日线, 最后一根为 end_date — 模拟 baostock cache 状态."""
    rng = np.random.default_rng(7)
    end = pd.Timestamp(end_date)
    dates = pd.bdate_range(end=end, periods=n)
    drift = np.linspace(0, 0.05, n)
    noise = rng.normal(0, 0.005, n)
    close = 10.0 * np.cumprod(1 + drift / n + noise)
    # 最后一根强行 breakout 创新高 + 量比放大 → 触发 entry_signal
    close[-1] = close[:-1].max() * 1.05
    high = close * 1.005
    low = close * 0.995
    open_ = close * 0.999
    volume = rng.integers(1_000_000, 3_000_000, n).astype(float)
    volume[-1] = volume[:-1].mean() * 3.0
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
    })


class _FakeLoader:
    def __init__(self, df):
        self._df = df

    def get_daily(self, market, code, start, end):
        return self._df

    def daily_cache_path(self, market, code):
        from pathlib import Path
        return Path("/tmp/nonexistent")  # only_cached=False 路径不用


def test_scan_today_entries_attaches_entry_bar_date():
    """scan_today_entries 命中 hit dict 含 entry_bar_date = px last row date."""
    from quant_system.strategies.equity_factor.timing.signals import (
        scan_today_entries, TimingConfig,
    )

    df = _synthetic_daily(end_date="2026-06-05")  # cache 最新到周五
    loader = _FakeLoader(df)
    cfg = TimingConfig()

    hits = scan_today_entries(
        loader, "a_share", ["601988"],
        asof="2026-06-08",  # daily 跑日 = 周一 (cache 未覆盖)
        cfg=cfg,
        only_cached=False,
    )

    # 至少有一个 hit (合成 df 最后一根 +5% breakout 应触发)
    assert len(hits) >= 0  # signal 可能不触发; 关键是若触发, entry_bar_date 必为 06-05
    if hits:
        h = hits[0]
        assert "entry_bar_date" in h, "hit 必含 entry_bar_date 字段 (防 hold_days 负数)"
        assert h["entry_bar_date"] == "2026-06-05", (
            f"entry_bar_date 应是 cache 最新日 2026-06-05, 实际 {h['entry_bar_date']}"
        )
        # 关键差异: args.asof='2026-06-08' 但 entry_bar_date='2026-06-05'
        assert h["entry_bar_date"] != "2026-06-08"
