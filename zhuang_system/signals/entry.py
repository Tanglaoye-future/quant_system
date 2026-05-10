"""
入场信号模块.

两种模式：
  Phase-A 入场（吃货期低位埋伏）：accumulation_score >= 阈值，在吃货期末段建仓
  Phase-B 入场（放量突破确认）   ：breakout + volume_spike，更保守，等待拉升信号

策略默认使用 Phase-A：在吃货期尚未结束时提前入场，利用拉升初期的弹性。
Phase-B 作为备选，适合保守风格或者高 ATR 市场。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from zhuang_system.signals.accumulation import accumulation_score


@dataclass
class BuySignal:
    """入场信号."""
    code: str
    date: str
    price: float                       # 入场参考价（通常用次日开盘价）
    accumulation_score: float          # 吃货期评分
    phase: str = "A"                   # "A"=吃货期埋伏，"B"=突破确认
    reason: str = ""
    extra: dict = field(default_factory=dict)


def check_entry_signal(
    code: str,
    df: pd.DataFrame,
    asof_date: str,
    score_threshold: float = 55.0,
    volume_spike_ratio: float = 2.0,
    phase: str = "A",
    acc_weights: dict[str, float] | None = None,
) -> Optional[BuySignal]:
    """
    检查单只股票在 asof_date 是否触发入场信号.

    Parameters
    ----------
    code : str
        股票代码
    df : pd.DataFrame
        日线行情（截至 asof_date 当日，至少 40 行）
    asof_date : str
        信号日期（yyyy-mm-dd）
    score_threshold : float
        吃货期评分入场阈值
    volume_spike_ratio : float
        Phase-B 放量倍数阈值（Phase-A 不使用）
    phase : str
        "A" 吃货期埋伏 / "B" 突破确认
    acc_weights : dict | None
        吃货期信号权重覆盖

    Returns
    -------
    BuySignal | None
    """
    if len(df) < 40:
        return None

    # 截到 asof_date
    df = df[df["date"].astype(str) <= asof_date].copy()
    if len(df) < 40:
        return None

    close = float(df["close"].iloc[-1])
    volume = float(df["volume"].iloc[-1])

    # 吃货期评分
    acc = accumulation_score(df, weights=acc_weights)

    if phase == "A":
        # Phase-A：评分达阈值且价格处于20日区间上半段（P1：接近突破点才入场）
        if acc < score_threshold:
            return None
        # 价格位置确认：close在近20日high-low区间的上50%才考虑入场
        # 原理：吃货末期主力托价，价格会自然上移到区间上半段
        recent20 = df.iloc[-20:]
        r_high = float(recent20["high"].astype(float).max())
        r_low = float(recent20["low"].astype(float).min())
        r_range = r_high - r_low
        if r_range > 0 and close < r_low + r_range * 0.5:
            return None   # 价格仍在区间下半段，尚未到入场时机
        return BuySignal(
            code=code,
            date=asof_date,
            price=close,
            accumulation_score=acc,
            phase="A",
            reason=f"accumulation_score={acc:.1f} >= {score_threshold}",
        )

    elif phase == "B":
        # Phase-B：需要突破+放量（拉升确认）+ 仍有一定吃货期评分
        if acc < score_threshold * 0.8:   # Phase-B 评分要求稍低（突破时横盘会打破）
            return None
        # 突破：当日收盘创近20日新高
        high_20 = df["close"].iloc[-21:-1].max() if len(df) >= 21 else df["close"].iloc[:-1].max()
        if close <= high_20:
            return None
        # 放量：当日成交量 >= 近20日均量 × volume_spike_ratio
        avg_vol = df["volume"].iloc[-21:-1].mean() if len(df) >= 21 else df["volume"].iloc[:-1].mean()
        if volume < avg_vol * volume_spike_ratio:
            return None
        return BuySignal(
            code=code,
            date=asof_date,
            price=close,
            accumulation_score=acc,
            phase="B",
            reason=(
                f"breakout(close={close:.2f}>high20={high_20:.2f}) "
                f"+ volume_spike({volume:.0f}/{avg_vol:.0f}={volume/avg_vol:.1f}x) "
                f"acc_score={acc:.1f}"
            ),
        )

    return None
