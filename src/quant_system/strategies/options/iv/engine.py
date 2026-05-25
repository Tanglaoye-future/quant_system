"""
IV 引擎：基于 vol_proxy ticker 计算标的的 IV Rank，输出策略模式。

vol_proxy ticker 由 market 配置注入，例如：
  - QQQ (NASDAQ-100 ETF) → ^VXN (CBOE NASDAQ-100 波动率指数)
  - HSI (恒生指数)        → VHSI (恒指波动率指数)

IVR = (当前 vol_proxy - 52周最低) / (52周最高 - 52周最低)

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
    vxn_current: float       # 字段名保留 vxn_ 前缀向下兼容；实际承载任意 vol_proxy 的当前值
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
    vxn_ticker: str,
    lookback_days: int = 252,
    cache_dir: Optional[Path] = None,
    refresh_hours: float = 4.0,
    cache_filename: Optional[str] = None,
) -> IVSnapshot:
    """
    拉取 vol_proxy 历史数据，计算 IV Rank。

    Parameters
    ----------
    vxn_ticker : str
        雅虎财经 ticker，例如 '^VXN' (NASDAQ-100 波动率) / 'VHSI' (恒指波动率)
        参数名保留 vxn_ticker 是历史命名（向下兼容）；实际可承载任意 vol proxy。
    lookback_days : int
        历史窗口（交易日），默认 252（≈52周）
    cache_dir : Path | None
        缓存目录；None 则不缓存
    refresh_hours : float
        缓存有效时间（小时），默认 4 小时
    cache_filename : str | None
        缓存文件名，默认基于 ticker 推导（多 market 时避免覆盖）
    """
    _require_yf()

    # ── 缓存 ──────────────────────────────────────────────────────────────────
    cache_path: Optional[Path] = None
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        # 默认按 ticker 推导 cache 文件名以避免多 market 互相覆盖
        # ^VXN → vol_proxy_VXN.csv / VHSI → vol_proxy_VHSI.csv
        if cache_filename is None:
            safe_name = vxn_ticker.lstrip("^").replace("/", "_")
            cache_filename = f"vol_proxy_{safe_name}.csv"
        cache_path = cache_dir / cache_filename
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
            note=f"无法获取 {vxn_ticker} 数据",
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
        print(f"[WARN] vol_proxy {ticker} fetch failed: {e}")
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
