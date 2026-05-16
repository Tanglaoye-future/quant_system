"""
IV 引擎：基于 VXN 计算 QQQ 的 IV Rank，输出策略模式。

VXN = CBOE NASDAQ-100 波动率指数，是 QQQ 的 implied vol 代理。
IVR = (当前 VXN - 52周最低) / (52周最高 - 52周最低)

策略模式：
  LOW_IV  (IVR < 25) → 期权便宜 → 买入认购 / Bull Call Spread
  MID_IV  (IVR 25-50) → 适中   → Bull Call Spread（卖出腿对冲成本）
  HIGH_IV (IVR > 50)  → 期权贵 → 跳过或缩小价差宽度
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None  # type: ignore


class IVMode(str, Enum):
    LOW = "LOW_IV"
    MID = "MID_IV"
    HIGH = "HIGH_IV"
    UNKNOWN = "UNKNOWN"


@dataclass
class IVSnapshot:
    date: str
    vxn_current: float
    vxn_52w_low: float
    vxn_52w_high: float
    ivr: float               # 0–100
    mode: IVMode
    signal_grade: str        # A/B/C/D
    note: str = ""


def _require_yf() -> None:
    if yf is None:
        raise ImportError("请安装 yfinance：pip install yfinance")


def compute_ivr(
    vxn_ticker: str = "^VXN",
    lookback_days: int = 252,
    cache_dir: Optional[Path] = None,
    refresh_hours: float = 4.0,
) -> IVSnapshot:
    """
    拉取 VXN 历史数据，计算 IV Rank。

    Parameters
    ----------
    vxn_ticker : str
        雅虎财经 ticker，默认 ^VXN（NASDAQ 波动率）
    lookback_days : int
        历史窗口（交易日），默认 252（≈52周）
    cache_dir : Path | None
        缓存目录；None 则不缓存
    refresh_hours : float
        缓存有效时间（小时），默认 4 小时
    """
    _require_yf()

    # ── 缓存 ──────────────────────────────────────────────────────────────────
    cache_path: Optional[Path] = None
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / "vxn_history.csv"
        if cache_path.exists():
            age_hours = (time.time() - os.path.getmtime(cache_path)) / 3600
            if age_hours < refresh_hours:
                hist = pd.read_csv(cache_path, index_col=0, parse_dates=True)
            else:
                hist = _fetch_vxn(vxn_ticker, lookback_days)
                hist.to_csv(cache_path)
        else:
            hist = _fetch_vxn(vxn_ticker, lookback_days)
            hist.to_csv(cache_path)
    else:
        hist = _fetch_vxn(vxn_ticker, lookback_days)

    if hist.empty:
        return IVSnapshot(
            date=datetime.now().strftime("%Y-%m-%d"),
            vxn_current=0.0, vxn_52w_low=0.0, vxn_52w_high=0.0,
            ivr=0.0, mode=IVMode.UNKNOWN, signal_grade="D",
            note="无法获取 VXN 数据",
        )

    # yfinance ≥1.0 对单 ticker 可能返回 MultiIndex columns (field, ticker)；统一拍平
    if isinstance(hist.columns, pd.MultiIndex):
        hist.columns = hist.columns.get_level_values(0)
    close_col = "Close" if "Close" in hist.columns else hist.columns[0]
    series = hist[close_col].squeeze().dropna()  # squeeze 确保 Series 而非 DataFrame

    current = float(series.iloc[-1])
    low_52w = float(series.min())
    high_52w = float(series.max())

    if high_52w == low_52w:
        ivr = 50.0
    else:
        ivr = (current - low_52w) / (high_52w - low_52w) * 100.0

    date_str = series.index[-1].strftime("%Y-%m-%d") if hasattr(series.index[-1], "strftime") else str(series.index[-1])[:10]

    mode, grade = _classify(ivr)
    return IVSnapshot(
        date=date_str,
        vxn_current=round(current, 2),
        vxn_52w_low=round(low_52w, 2),
        vxn_52w_high=round(high_52w, 2),
        ivr=round(ivr, 1),
        mode=mode,
        signal_grade=grade,
    )


def _fetch_vxn(ticker: str, lookback_days: int) -> pd.DataFrame:
    end = datetime.now()
    # 加 buffer 确保足够的交易日
    start = end - timedelta(days=int(lookback_days * 1.5))
    try:
        hist = yf.download(ticker, start=start.strftime("%Y-%m-%d"),
                           end=end.strftime("%Y-%m-%d"), progress=False, auto_adjust=True)
        return hist.tail(lookback_days)
    except Exception as e:
        print(f"[WARN] VXN fetch failed: {e}")
        return pd.DataFrame()


def _classify(ivr: float) -> tuple[IVMode, str]:
    if ivr < 25:
        return IVMode.LOW, "A"
    elif ivr < 40:
        return IVMode.MID, "B"
    elif ivr < 50:
        return IVMode.MID, "C"
    else:
        return IVMode.HIGH, "D"
