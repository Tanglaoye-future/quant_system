"""
吃货期（积累期）信号检测.

核心函数: accumulation_score()
输入：近 N 日日线 DataFrame（至少 40 行）
输出：0–100 的综合评分，越高越像吃货期

五维信号：
  1. ma_convergence    均线收敛（MA5/MA10/MA20 收窄）
  2. volume_asymmetry  量的不对称（上涨日量 vs 下跌日量比值）
  3. price_consolidation 价格振幅收窄（横盘整理）
  4. turnover_decline  换手率趋势下降（浮筹减少 → 主力锁仓）
  5. vp_divergence     量价背离（成交量下降，价格未跌）
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ── 子信号：均线收敛 ──────────────────────────────────────────────────────────

def _ma_convergence_score(df: pd.DataFrame, lookback: int = 20) -> float:
    """
    MA5/MA10/MA20 越收越紧 → 1.0；发散 → 0.0.

    衡量方式：过去 lookback 日内，三条均线的极差（spread）是否收窄。
    spread = (max_ma - min_ma) / close
    近10日 spread 均值 vs 前10日 spread 均值，下降则得分高。
    """
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
    ratio = recent / prev          # <1 → 收敛，>1 → 发散
    score = max(0.0, min(1.0, 2.0 - ratio * 2.0))   # ratio=0.5→1.0, ratio=1.0→0.0
    return score


# ── 子信号：量的不对称 ───────────────────────────────────────────────────────

def _volume_asymmetry_score(df: pd.DataFrame, lookback: int = 20) -> float:
    """
    上涨日平均成交量 / 下跌日平均成交量 > 1 → 主力在涨时吸筹.
    目标比值 >= 2.0 → score=1.0；<= 1.0 → score=0.0.
    """
    if len(df) < lookback + 1:
        return 0.0
    recent = df.iloc[-lookback:].copy()
    recent["ret"] = recent["close"].astype(float).pct_change()
    up_vol = recent[recent["ret"] > 0]["volume"].astype(float).mean()
    down_vol = recent[recent["ret"] < 0]["volume"].astype(float).mean()
    if not down_vol or np.isnan(down_vol) or down_vol == 0:
        return 0.5
    ratio = up_vol / down_vol
    return float(np.clip((ratio - 1.0) / 1.5, 0.0, 1.0))  # ratio=1→0, ratio=2.5→1


# ── 子信号：价格横盘收敛 ─────────────────────────────────────────────────────

def _price_consolidation_score(
    df: pd.DataFrame, lookback: int = 20, max_range_pct: float = 0.08
) -> float:
    """
    过去 lookback 日内高低振幅 / 均值 <= max_range_pct → score=1.0.
    振幅越大 → score 越低.
    """
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


# ── 子信号：换手率趋势下降 ────────────────────────────────────────────────────

def _turnover_decline_score(df: pd.DataFrame, lookback: int = 20) -> float:
    """
    换手率近半段 vs 前半段均值下降 → 主力锁仓，浮筹减少.
    无换手率列时返回 0.5（中性）.
    """
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
    ratio = late_mean / prev_mean   # <1 → 下降（好）
    return float(np.clip(1.5 - ratio, 0.0, 1.0))    # ratio=0.5→1.0, ratio=1.0→0.5, ratio=1.5→0.0


# ── 子信号：量价背离 ────────────────────────────────────────────────────────

def _vp_divergence_score(df: pd.DataFrame, lookback: int = 20) -> float:
    """
    量价背离：成交量下降（萎缩），但价格未跌（甚至微涨）→ 庄家锁仓特征.

    计算方式：
      vol_trend = 后半段量均 / 前半段量均 （<1 = 量萎缩）
      price_trend = 收盘价后半段末 / 前半段末 （>= 1 = 价未跌）
    两者同时满足时得分高.
    """
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

    vol_ratio = vol_late / vol_prev        # < 1 好
    price_ratio = close_late / close_prev  # >= 1 好

    vol_score = float(np.clip(1.5 - vol_ratio, 0.0, 1.0))      # vol_ratio=0.5→1.0
    price_score = float(np.clip((price_ratio - 0.97) / 0.05, 0.0, 1.0))  # price_ratio=1.0→0.6

    return (vol_score + price_score) / 2.0


# ── 综合评分 ─────────────────────────────────────────────────────────────────

def accumulation_score(
    df: pd.DataFrame,
    weights: dict[str, float] | None = None,
    lookback: int = 20,
) -> float:
    """
    计算吃货期综合评分（0–100）.

    Parameters
    ----------
    df : pd.DataFrame
        日线 OHLCV，至少 40 行（含 turnover_rate 列则更精确）
    weights : dict
        五维权重（默认值来自 config accumulation_weights）
    lookback : int
        各子信号的回望窗口（默认 20 日）

    Returns
    -------
    float
        0–100 的评分，>= 55 可触发入场观察，>= 65 可确认入场
    """
    if weights is None:
        weights = {
            "ma_convergence": 0.20,
            "volume_asymmetry": 0.30,
            "price_consolidation": 0.20,
            "turnover_decline": 0.15,
            "vp_divergence": 0.15,
        }

    scores = {
        "ma_convergence": _ma_convergence_score(df, lookback),
        "volume_asymmetry": _volume_asymmetry_score(df, lookback),
        "price_consolidation": _price_consolidation_score(df, lookback),
        "turnover_decline": _turnover_decline_score(df, lookback),
        "vp_divergence": _vp_divergence_score(df, lookback),
    }

    total_weight = sum(weights.get(k, 0.0) for k in scores)
    if total_weight <= 0:
        return 0.0
    raw = sum(scores[k] * weights.get(k, 0.0) for k in scores) / total_weight
    return round(raw * 100.0, 1)


def accumulation_score_detail(
    df: pd.DataFrame,
    weights: dict[str, float] | None = None,
    lookback: int = 20,
) -> dict[str, float]:
    """与 accumulation_score 相同，但返回各维度明细（含 total）."""
    if weights is None:
        weights = {
            "ma_convergence": 0.20,
            "volume_asymmetry": 0.30,
            "price_consolidation": 0.20,
            "turnover_decline": 0.15,
            "vp_divergence": 0.15,
        }
    detail: dict[str, float] = {
        "ma_convergence": round(_ma_convergence_score(df, lookback) * 100, 1),
        "volume_asymmetry": round(_volume_asymmetry_score(df, lookback) * 100, 1),
        "price_consolidation": round(_price_consolidation_score(df, lookback) * 100, 1),
        "turnover_decline": round(_turnover_decline_score(df, lookback) * 100, 1),
        "vp_divergence": round(_vp_divergence_score(df, lookback) * 100, 1),
    }
    total_weight = sum(weights.get(k, 0.0) for k in detail)
    if total_weight > 0:
        detail["total"] = round(
            sum(detail[k] * weights.get(k, 0.0) for k in detail if k != "total")
            / total_weight, 1
        )
    else:
        detail["total"] = 0.0
    return detail
