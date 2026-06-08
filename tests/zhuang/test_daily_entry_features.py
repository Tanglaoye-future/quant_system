"""L3 of self_learning_pipeline — _build_zhuang_entry_features 契约测试.

Backstop #5 (采集 ≠ 新计算): 全部从 accumulation_score_detail (已算) 抽;
sig 的 accumulation_score / phase / price 已存; ATR 由 main 传; fail-soft 异常返 None.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SPEC_PATH = Path(__file__).resolve().parents[2] / "scripts" / "daily" / "daily_zhuang.py"


@pytest.fixture(scope="module")
def daily_zhuang_mod():
    """以 module 形式加载 daily_zhuang.py, 拿 _build_zhuang_entry_features."""
    spec = importlib.util.spec_from_file_location("_daily_zhuang_for_test", SPEC_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_daily_zhuang_for_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@dataclass
class _FakeSig:
    code: str = "600103"
    accumulation_score: float = 60.8
    phase: str = "A"
    price: float = 4.58
    reason: str = "accumulation_score=60.8 >= 45"


def _synthetic_zhuang_daily(n: int = 60) -> pd.DataFrame:
    """合成日线 — 后半段缩量横盘 (吃货期典型形态)."""
    rng = np.random.default_rng(7)
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    base = 4.5
    close = base + rng.normal(0, 0.02, n).cumsum() * 0.1
    close = np.clip(close, 4.2, 5.0)
    high = close * 1.005
    low = close * 0.995
    open_ = close * 0.999
    volume = rng.integers(5_000_000, 8_000_000, n).astype(float)
    # 后段缩量 (吃货期信号)
    volume[-20:] *= 0.6
    turnover_rate = rng.uniform(0.5, 2.5, n)
    return pd.DataFrame({
        "date": dates, "open": open_, "high": high, "low": low,
        "close": close, "volume": volume, "turnover_rate": turnover_rate,
    })


def test_build_zhuang_features_normal_case(daily_zhuang_mod):
    df = _synthetic_zhuang_daily(n=60)
    sig = _FakeSig()
    feats = daily_zhuang_mod._build_zhuang_entry_features(
        df=df, sig=sig, atr_val=0.18, position_pct=0.05,
        market="a_share", asof="2026-05-28", market_trend=True, acc_weights=None,
    )
    assert feats is not None
    expected = {
        "accumulation_ma_convergence", "accumulation_volume_asymmetry",
        "accumulation_price_consolidation", "accumulation_turnover_decline",
        "accumulation_vp_divergence", "accumulation_total",
        "phase", "atr_at_entry", "entry_price", "position_pct",
        "market", "market_trend_on", "asof", "market_cap_band", "industry_sw1",
    }
    assert set(feats.keys()) == expected
    # JSONB 友好: 无 NaN / Inf
    for k, v in feats.items():
        if isinstance(v, float):
            assert np.isfinite(v), f"{k}={v}: NaN/Inf 应转 None"
    # 数值化字段 + 占位 None
    assert feats["accumulation_total"] == pytest.approx(60.8)
    assert feats["phase"] == "A"
    assert feats["entry_price"] == pytest.approx(4.58)
    assert feats["position_pct"] == pytest.approx(0.05)
    assert feats["atr_at_entry"] == pytest.approx(0.18)
    assert feats["market"] == "a_share"
    assert feats["market_trend_on"] is True
    assert feats["asof"] == "2026-05-28"
    assert feats["market_cap_band"] is None
    assert feats["industry_sw1"] is None


def test_build_zhuang_features_market_trend_none_keeps_none(daily_zhuang_mod):
    """market_trend None (上游不可用) → market_trend_on 也 None, 不假成 False."""
    df = _synthetic_zhuang_daily()
    feats = daily_zhuang_mod._build_zhuang_entry_features(
        df=df, sig=_FakeSig(), atr_val=0.1, position_pct=0.05,
        market="a_share", asof="2026-05-28", market_trend=None, acc_weights=None,
    )
    assert feats is not None
    assert feats["market_trend_on"] is None


def test_build_zhuang_features_fail_soft_sig_none(daily_zhuang_mod):
    """sig=None → 取 sig.accumulation_score 抛 → 返 None (Backstop #5: fail-soft)."""
    df = _synthetic_zhuang_daily()
    feats = daily_zhuang_mod._build_zhuang_entry_features(
        df=df, sig=None, atr_val=0.1, position_pct=0.05,
        market="a_share", asof="2026-05-28", market_trend=True, acc_weights=None,
    )
    assert feats is None
