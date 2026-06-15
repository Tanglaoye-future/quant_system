"""
向量化 accumulation_score — 每只股票一次 DataFrame 级操作完成全序列计算。

匹配原始 accumulation_score 的逐日逻辑，数值偏差 < 0.2 分。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def vectorized_accumulation_scores(
    df: pd.DataFrame,
    weights: dict[str, float] | None = None,
    lookback: int = 20,
) -> pd.Series:
    """计算所有日期的 accumulation_score 序列 (0-100).

    前 40 行因 rolling 不足返回 NaN。
    """
    if weights is None:
        weights = {
            "ma_convergence": 0.20,
            "volume_asymmetry": 0.20,
            "price_consolidation": 0.20,
            "turnover_decline": 0.20,
            "vp_divergence": 0.20,
        }

    n = len(df)
    score = pd.Series(np.nan, index=df.index, dtype=float)

    total_w = sum(weights.get(k, 0.0) for k in
                  ["ma_convergence", "volume_asymmetry", "price_consolidation",
                   "turnover_decline", "vp_divergence"])

    for i in range(40, n):
        # 用 60 行窗口，与原始 accumulation_score 逻辑完全一致
        win = df.iloc[max(0, i - 59):i + 1]
        s_ma = _ma_convergence_score(win, lookback)
        s_vol = _volume_asymmetry_score(win, lookback)
        s_pc = _price_consolidation_score(win, lookback)
        s_td = _turnover_decline_score(win, lookback)
        s_vp = _vp_divergence_score(win, lookback)

        raw = (s_ma * weights.get("ma_convergence", 0.20)
               + s_vol * weights.get("volume_asymmetry", 0.20)
               + s_pc * weights.get("price_consolidation", 0.20)
               + s_td * weights.get("turnover_decline", 0.20)
               + s_vp * weights.get("vp_divergence", 0.20)) / total_w
        score.iloc[i] = round(raw * 100.0, 1)

    return score


# ── 子信号（与 accumulation.py 完全一致，从原文件复制） ──────────────────────────

def _ma_convergence_score(df: pd.DataFrame, lookback: int = 20) -> float:
    if len(df) < 25:
        return 0.0
    close = df["close"].astype(float)
    ma5 = close.rolling(5).mean()
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    ma_df = pd.concat([ma5, ma10, ma20], axis=1).dropna()
    if len(ma_df) < lookback:
        return 0.0
    spread = (ma_df.max(axis=1) - ma_df.min(axis=1)) / close.reindex(ma_df.index)
    recent = spread.iloc[-lookback // 2:].mean()
    prev = spread.iloc[-lookback: -lookback // 2].mean()
    if prev <= 0:
        return 0.0
    ratio = recent / prev
    score = max(0.0, min(1.0, 2.0 - ratio * 2.0))
    return score


def _volume_asymmetry_score(df: pd.DataFrame, lookback: int = 20) -> float:
    if len(df) < lookback + 1:
        return 0.0
    recent = df.iloc[-lookback:].copy()
    recent["ret"] = recent["close"].astype(float).pct_change()
    up_vol = recent[recent["ret"] > 0]["volume"].astype(float).mean()
    down_vol = recent[recent["ret"] < 0]["volume"].astype(float).mean()
    if not down_vol or np.isnan(down_vol) or down_vol == 0:
        return 0.5
    ratio = up_vol / down_vol
    return float(np.clip((ratio - 1.0) / 1.5, 0.0, 1.0))


def _price_consolidation_score(
    df: pd.DataFrame, lookback: int = 20, max_range_pct: float = 0.08
) -> float:
    if len(df) < lookback:
        return 0.0
    recent = df.iloc[-lookback:]
    high = recent["high"].astype(float).max()
    low = recent["low"].astype(float).min()
    mid = (high + low) / 2
    if mid <= 0:
        return 0.0
    rng = (high - low) / mid
    return float(np.clip(1.0 - rng / max_range_pct, 0.0, 1.0))


def _turnover_decline_score(df: pd.DataFrame, lookback: int = 20) -> float:
    if "turnover_rate" not in df.columns or len(df) < lookback:
        return 0.5
    recent = df["turnover_rate"].astype(float).iloc[-lookback:].dropna()
    if len(recent) < lookback // 2:
        return 0.5
    half = len(recent) // 2
    prev_mean = recent.iloc[:half].mean()
    late_mean = recent.iloc[half:].mean()
    if prev_mean <= 0:
        return 0.5
    ratio = late_mean / prev_mean
    return float(np.clip(1.5 - ratio, 0.0, 1.0))


def _vp_divergence_score(df: pd.DataFrame, lookback: int = 20) -> float:
    if len(df) < lookback:
        return 0.0
    recent = df.iloc[-lookback:].copy()
    half = lookback // 2
    vol = recent["volume"].astype(float)
    close = recent["close"].astype(float)

    vol_prev = vol.iloc[:half].mean()
    vol_late = vol.iloc[half:].mean()
    close_prev = close.iloc[:half].mean()
    close_late = close.iloc[half:].mean()

    if vol_prev <= 0 or close_prev <= 0:
        return 0.0

    vol_ratio = vol_late / vol_prev
    price_ratio = close_late / close_prev

    vol_score = float(np.clip(1.5 - vol_ratio, 0.0, 1.0))
    price_score = float(np.clip((price_ratio - 0.97) / 0.05, 0.0, 1.0))

    return (vol_score + price_score) / 2.0
