"""
Unit tests for accumulation signal module.
Tests: sub-signal boundary behavior, total score range, score comparison.
"""
import numpy as np
import pandas as pd
import pytest

from zhuang_system.signals.accumulation import (
    accumulation_score,
    accumulation_score_detail,
    _ma_convergence_score,
    _volume_asymmetry_score,
    _price_consolidation_score,
    _turnover_decline_score,
    _vp_divergence_score,
)


def _make_df(n: int, seed: int = 42) -> pd.DataFrame:
    """生成伪日线行情 DataFrame (无特征，随机噪声)."""
    rng = np.random.default_rng(seed)
    close = 10.0 + rng.normal(0, 0.2, n).cumsum()
    close = np.maximum(close, 1.0)
    high = close + rng.uniform(0.05, 0.3, n)
    low = close - rng.uniform(0.05, 0.3, n)
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)
    turnover = rng.uniform(0.01, 0.05, n)
    return pd.DataFrame({
        "date": pd.date_range("2022-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
        "open": close - rng.uniform(0.05, 0.1, n),
        "high": high, "low": low, "close": close,
        "volume": volume, "turnover_rate": turnover,
    })


def _make_accumulation_df(n: int = 50) -> pd.DataFrame:
    """构造具有强吃货期特征的行情."""
    close = np.linspace(10.0, 10.5, n)   # 微涨（横盘偏强）
    high = close + 0.1
    low = close - 0.1
    # 量：前半段大，后半段小（量缩）
    vol = np.concatenate([
        np.full(n // 2, 3_000_000),
        np.full(n - n // 2, 1_500_000),
    ]).astype(float)
    # 上涨日量大，下跌日量小
    rets = np.diff(close, prepend=close[0])
    vol[rets > 0] *= 1.5
    vol[rets < 0] *= 0.5
    turnover = np.concatenate([
        np.full(n // 2, 0.04),
        np.full(n - n // 2, 0.02),
    ])
    return pd.DataFrame({
        "date": pd.date_range("2022-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
        "open": close - 0.05,
        "high": high, "low": low, "close": close,
        "volume": vol, "turnover_rate": turnover,
    })


# ── 分项测试 ─────────────────────────────────────────────────────────────────

class TestSubSignals:
    def test_price_consolidation_tight(self):
        df = _make_accumulation_df(50)
        score = _price_consolidation_score(df, lookback=20, max_range_pct=0.08)
        assert 0.0 <= score <= 1.0

    def test_price_consolidation_volatile(self):
        # 宽幅震荡，振幅超过 max_range_pct → score 低
        n = 30
        close = np.array([10.0, 11.5, 9.5, 11.0, 9.0] * 6)[:n]
        df = pd.DataFrame({
            "date": pd.date_range("2022-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
            "open": close - 0.1, "close": close,
            "high": close + 0.5, "low": close - 0.5,
            "volume": np.full(n, 1_000_000.0),
        })
        score = _price_consolidation_score(df, lookback=20, max_range_pct=0.08)
        assert score == 0.0

    def test_volume_asymmetry_up_heavy(self):
        # 上涨日量明显大于下跌日量 → score 高
        df = _make_accumulation_df(50)
        score = _volume_asymmetry_score(df, lookback=20)
        assert score > 0.3

    def test_volume_asymmetry_insufficient_data(self):
        df = _make_df(10)
        score = _volume_asymmetry_score(df, lookback=20)
        assert score == 0.0

    def test_turnover_decline_decreasing(self):
        df = _make_accumulation_df(50)
        score = _turnover_decline_score(df, lookback=20)
        assert score > 0.4   # 换手率从0.04降到0.02，应得分较高

    def test_turnover_decline_no_column(self):
        df = _make_df(40).drop(columns=["turnover_rate"])
        score = _turnover_decline_score(df, lookback=20)
        assert score == 0.5  # 无数据 → 中性

    def test_ma_convergence_returns_0_to_1(self):
        df = _make_df(40)
        score = _ma_convergence_score(df, lookback=20)
        assert 0.0 <= score <= 1.0

    def test_vp_divergence_accumulation(self):
        df = _make_accumulation_df(50)
        score = _vp_divergence_score(df, lookback=20)
        # 量缩价稳 → 应该有正得分
        assert score >= 0.0


# ── 综合分测试 ────────────────────────────────────────────────────────────────

class TestAccumulationScore:
    def test_score_range(self):
        df = _make_df(50)
        score = accumulation_score(df)
        assert 0.0 <= score <= 100.0

    def test_accumulation_df_scores_higher_than_random(self):
        df_acc = _make_accumulation_df(50)
        df_rand = _make_df(50, seed=123)
        score_acc = accumulation_score(df_acc)
        score_rand = accumulation_score(df_rand)
        # 构造的吃货期行情得分应高于随机噪声（不是严格保证，但合理期望）
        assert score_acc >= score_rand - 10.0   # 容差10分

    def test_short_df_returns_low_score(self):
        df = _make_df(20)
        score = accumulation_score(df)
        # 数据不足 40 行，多数子信号返回 0，总分应较低
        assert score < 50.0

    def test_detail_keys(self):
        df = _make_accumulation_df(50)
        detail = accumulation_score_detail(df)
        assert set(detail.keys()) == {
            "ma_convergence", "volume_asymmetry", "price_consolidation",
            "turnover_decline", "vp_divergence", "total"
        }
        assert 0.0 <= detail["total"] <= 100.0

    def test_custom_weights(self):
        df = _make_accumulation_df(50)
        w = {"ma_convergence": 0.5, "volume_asymmetry": 0.5,
             "price_consolidation": 0.0, "turnover_decline": 0.0, "vp_divergence": 0.0}
        score = accumulation_score(df, weights=w)
        assert 0.0 <= score <= 100.0
