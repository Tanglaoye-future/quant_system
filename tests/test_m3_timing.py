"""M3: RSI 带与市况上下文、多周期 RSI 列。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant_system.timing.regime import TimingRegimeContext
from quant_system.timing.signals import TimingConfig, _effective_rsi_entry_band, enrich


def test_effective_rsi_band_m3_regime_widen():
    cfg = TimingConfig(
        rsi_entry_low=50.0,
        rsi_entry_high=70.0,
        m2_rsi_atr_adjust=False,
        m3_regime_rsi_band=True,
        m3_reg_rsi_lo_widen_pts_per_ma_gap_1pct=1.5,
        m3_reg_rsi_lo_widen_cap=8.0,
    )
    ctx = TimingRegimeContext(index_close_vs_ma=0.02, index_atr_pct=0.01, index_atr_pct_rel=None)
    lo, hi = _effective_rsi_entry_band(cfg, 100.0, None, ctx)
    assert lo < 50.0
    assert hi == 70.0


def test_effective_rsi_band_m3_vol_tighten_hi():
    cfg = TimingConfig(
        m2_rsi_atr_adjust=False,
        m3_reg_vol_tighten_hi=True,
        m3_reg_vol_hi_tighten_k=10.0,
        m3_reg_vol_hi_tighten_cap=5.0,
    )
    ctx = TimingRegimeContext(None, None, 0.5)
    lo, hi = _effective_rsi_entry_band(cfg, 100.0, None, ctx)
    assert hi < cfg.rsi_entry_high


def test_enrich_adds_rsi_mtf_when_enabled():
    rng = np.random.default_rng(0)
    n = 120
    dr = pd.date_range("2020-01-01", periods=n, freq="D")
    walk = 10.0 + np.cumsum(rng.normal(0, 0.15, size=n))
    df = pd.DataFrame(
        {
            "date": dr.strftime("%Y-%m-%d"),
            "open": walk,
            "high": walk + 0.2,
            "low": walk - 0.2,
            "close": walk,
            "volume": [1e6] * n,
        }
    )
    cfg = TimingConfig(m3_mtf_rsi_enabled=True, m3_mtf_rsi_period=28)
    out = enrich(df, cfg)
    assert "rsi_mtf" in out.columns
    assert out["rsi_mtf"].notna().sum() > 40
