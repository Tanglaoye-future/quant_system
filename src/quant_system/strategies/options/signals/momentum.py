"""
QQQ 动量门控信号.

条件：
  1. QQQ 收盘 > MA200（牛市环境）
  2. RSI(14) 在 [rsi_low, rsi_high]（不追超买，不接飞刀）
  3. 3 个月涨幅 > 0（正向动量）

返回 MomentumSignal，包含所有中间值，供信号卡展示。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None  # type: ignore


@dataclass
class MomentumSignal:
    date: str
    price: float
    ma200: float
    rsi: float
    momentum_3m: float       # 3 个月收益率（小数）
    above_ma200: bool
    rsi_in_range: bool
    momentum_positive: bool
    bullish: bool            # 三个条件全部满足
    note: str = ""


def check_momentum(
    ticker: str = "QQQ",
    ma_period: int = 200,
    rsi_period: int = 14,
    rsi_low: float = 50.0,
    rsi_high: float = 78.0,
    lookback_days: int = 300,
) -> MomentumSignal:
    """
    拉取 QQQ 日线，计算动量指标。

    使用 yfinance 获取数据（无需 IBKR 连接）。
    """
    if yf is None:
        raise ImportError("请安装 yfinance：pip install yfinance")

    end = datetime.now()
    start = end - timedelta(days=int(lookback_days * 1.5))
    try:
        hist = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )
    except Exception as e:
        return MomentumSignal(
            date=end.strftime("%Y-%m-%d"), price=0.0, ma200=0.0, rsi=0.0,
            momentum_3m=0.0, above_ma200=False, rsi_in_range=False,
            momentum_positive=False, bullish=False, note=f"数据获取失败: {e}",
        )

    if len(hist) < ma_period + rsi_period:
        return MomentumSignal(
            date=end.strftime("%Y-%m-%d"), price=0.0, ma200=0.0, rsi=0.0,
            momentum_3m=0.0, above_ma200=False, rsi_in_range=False,
            momentum_positive=False, bullish=False, note="历史数据不足",
        )

    # yfinance ≥1.0 对单 ticker 可能返回 MultiIndex columns (field, ticker)；统一拍平
    if isinstance(hist.columns, pd.MultiIndex):
        hist.columns = hist.columns.get_level_values(0)
    close_col = "Close" if "Close" in hist.columns else hist.columns[0]
    close = hist[close_col].squeeze().dropna()

    price = float(close.iloc[-1])
    ma200 = float(close.rolling(ma_period).mean().iloc[-1])
    rsi_val = float(_compute_rsi(close, rsi_period).iloc[-1])
    mom_3m = float(close.iloc[-1] / close.iloc[-63] - 1.0) if len(close) >= 63 else 0.0

    above_ma = price > ma200
    rsi_ok = rsi_low <= rsi_val <= rsi_high
    mom_ok = mom_3m > 0.0
    bullish = above_ma and rsi_ok and mom_ok

    date_str = close.index[-1].strftime("%Y-%m-%d") if hasattr(close.index[-1], "strftime") else str(close.index[-1])[:10]

    notes = []
    if not above_ma:
        notes.append(f"价格({price:.2f}) < MA200({ma200:.2f})")
    if not rsi_ok:
        notes.append(f"RSI({rsi_val:.1f}) 超出范围 [{rsi_low},{rsi_high}]")
    if not mom_ok:
        notes.append(f"3月动量({mom_3m*100:.1f}%) 为负")

    return MomentumSignal(
        date=date_str,
        price=round(price, 2),
        ma200=round(ma200, 2),
        rsi=round(rsi_val, 1),
        momentum_3m=round(mom_3m, 4),
        above_ma200=above_ma,
        rsi_in_range=rsi_ok,
        momentum_positive=mom_ok,
        bullish=bullish,
        note=" | ".join(notes) if notes else "所有条件通过",
    )


def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    # avg_loss == 0 → 无下跌日 → RSI = 100
    rsi = np.where(avg_loss == 0, 100.0, 100.0 - 100.0 / (1.0 + avg_gain / avg_loss))
    return pd.Series(rsi, index=close.index)
