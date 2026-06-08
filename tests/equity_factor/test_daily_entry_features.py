"""L2 of self_learning_pipeline — _build_entry_features_for_code 契约测试.

Backstop #5 (采集 ≠ 新计算): 全部从 timing.enrich 已计算列抽; sector_sw1
留 None 占位; NaN safe; fail-soft 失败返回 None 不阻断 open_trade.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SPEC_PATH = Path(__file__).resolve().parents[2] / "scripts" / "daily" / "daily_equity.py"


@pytest.fixture(scope="module")
def daily_equity_mod():
    """以 module 形式加载 daily_equity.py (script 形式), 拿 _build_entry_features_for_code."""
    spec = importlib.util.spec_from_file_location("_daily_equity_for_test", SPEC_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_daily_equity_for_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _synthetic_daily(n: int = 90, base_price: float = 10.0, breakout_at_end: bool = True) -> pd.DataFrame:
    """生成 n 天合成日线 — 后半段缓升, 最后一天突破 20d 高."""
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    rng = np.random.default_rng(42)
    drift = np.linspace(0, 0.05, n)
    noise = rng.normal(0, 0.005, n)
    close = base_price * np.cumprod(1 + drift / n + noise)
    if breakout_at_end:
        close[-1] = close[:-1].max() * 1.02  # 创新高
    high = close * 1.005
    low = close * 0.995
    open_ = close * 0.999
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)
    volume[-1] = volume[:-1].mean() * 2.0  # 量比 ~2
    return pd.DataFrame({
        "date": dates, "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
    })


class _FakeLoader:
    def __init__(self, df: pd.DataFrame | None):
        self._df = df

    def get_daily(self, market, code, start, end):
        return self._df


def test_build_entry_features_normal_case(daily_equity_mod):
    from quant_system.strategies.equity_factor.timing.signals import TimingConfig
    df = _synthetic_daily(n=90)
    loader = _FakeLoader(df)
    tcfg = TimingConfig()
    feats = daily_equity_mod._build_entry_features_for_code(
        loader, "a_share", "601988", "2026-05-08", "equity_momentum", tcfg, 0.318,
    )
    assert feats is not None
    # 契约字段都在
    expected_keys = {
        "rsi", "vol_ratio", "ma_short", "ma_long", "ma_short_above_long",
        "atr", "close", "dist_to_20d_high_pct", "price_position_20d",
        "strategy", "market", "asof", "sector_sw1", "zscore_within_universe",
    }
    assert set(feats.keys()) == expected_keys
    # JSONB 友好 — 无 NaN / Inf
    for k, v in feats.items():
        if isinstance(v, float):
            assert np.isfinite(v), f"{k}={v}: NaN/Inf 应转 None"
    # 突破日 dist_to_20d_high_pct 应 >= 0 (创新高)
    assert feats["dist_to_20d_high_pct"] >= 0.0
    # 量比应 ~2x
    assert 1.5 <= feats["vol_ratio"] <= 3.0
    # context
    assert feats["strategy"] == "equity_momentum"
    assert feats["market"] == "a_share"
    assert feats["asof"] == "2026-05-08"
    assert feats["sector_sw1"] is None  # L2 不接入
    assert feats["zscore_within_universe"] == pytest.approx(0.318)


def test_build_entry_features_fail_soft_empty_df(daily_equity_mod):
    """loader 返空 df → 返 None (Backstop #5: fail-soft)."""
    from quant_system.strategies.equity_factor.timing.signals import TimingConfig
    loader = _FakeLoader(pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"]))
    feats = daily_equity_mod._build_entry_features_for_code(
        loader, "a_share", "601988", "2026-05-08", "equity_momentum", TimingConfig(), 0.0,
    )
    assert feats is None


def test_build_entry_features_fail_soft_loader_throws(daily_equity_mod):
    """loader 抛错 → 返 None, 不抛 (Backstop #5: 永不阻断 open_trade)."""
    from quant_system.strategies.equity_factor.timing.signals import TimingConfig

    class ThrowingLoader:
        def get_daily(self, *args, **kwargs):
            raise RuntimeError("baostock down")

    feats = daily_equity_mod._build_entry_features_for_code(
        ThrowingLoader(), "a_share", "601988", "2026-05-08", "equity_momentum",
        TimingConfig(), 0.0,
    )
    assert feats is None
