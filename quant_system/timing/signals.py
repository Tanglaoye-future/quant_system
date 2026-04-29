"""
技术择时: 中线 (20-60 日持仓) 的入场 / 出场信号 + 移动止损.

入场规则 (三条全过才入):
  1. 趋势: 过去 5 日内 MA20 上穿 MA60 且当前仍维持金叉之上
          (严格当日金叉实测一年 0 触发, 故放宽窗口让爆量日跟进)
  2. 动量: RSI(14) 在 [50, 70] (确认上行但未过热)
  3. 量能: 当日成交量 >= 20 日均量 * 1.5

出场规则 (任一触发即出, 优先级从高到低):
  1. 跌破 trailing stop (close <= 当前止损价)
  2. 跌破 MA60 (硬止损, 趋势破坏)
  3. 触及 take profit (close >= 入场价 + ATR * 4)
  4. RSI(14) >= 80 (超买退出)
  5. 持有 >= 60 天 (时间止盈, 强制评估)

Trailing stop:
  初始 = entry_price - ATR * 2
  每日更新 = max(prev_stop, close - ATR * 2)   # 只上调, 不下调
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class TimingConfig:
    ma_short: int = 20
    ma_long: int = 60
    rsi_period: int = 14
    rsi_entry_low: float = 50.0
    rsi_entry_high: float = 70.0
    rsi_overbought: float = 80.0
    vol_ma_period: int = 20
    vol_breakout_mult: float = 1.5
    atr_period: int = 14
    atr_stop_mult: float = 2.0
    atr_target_mult: float = 4.0
    max_hold_days: int = 60
    cross_lookback: int = 5    # 当日 + 过去 N 日内有金叉即可


# ---------- 指标 ----------

def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1.0 / n, min_periods=n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / n, min_periods=n, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    prev_close = c.shift(1)
    tr = pd.concat(
        [h - l, (h - prev_close).abs(), (l - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / n, min_periods=n, adjust=False).mean()


def enrich(df: pd.DataFrame, cfg: TimingConfig) -> pd.DataFrame:
    out = df.copy()
    out["ma_short"] = sma(out["close"], cfg.ma_short)
    out["ma_long"] = sma(out["close"], cfg.ma_long)
    out["rsi"] = rsi(out["close"], cfg.rsi_period)
    out["atr"] = atr(out, cfg.atr_period)
    out["vol_ma"] = sma(out["volume"], cfg.vol_ma_period)
    return out


# ---------- 入场 ----------

def _no_entry(reason: str, price, stop, target) -> dict:
    return {
        "signal": False,
        "reasons": [reason],
        "entry_price": price,
        "stop_loss": stop,
        "take_profit": target,
    }


def entry_signal_from_enriched(enriched: pd.DataFrame, cfg: Optional[TimingConfig] = None) -> dict:
    """与 entry_signal 同, 但接收已 enrich 的 df (避免重复 enrich, 用于回测加速)."""
    cfg = cfg or TimingConfig()
    if len(enriched) < cfg.ma_long + 5:
        return _no_entry("数据不足", None, None, None)
    df = enriched
    today = df.iloc[-1]
    close = float(today["close"])
    a = float(today["atr"]) if pd.notna(today["atr"]) else None
    reasons: list[str] = []

    if not (pd.notna(today["ma_long"]) and today["ma_short"] > today["ma_long"]):
        return _no_entry(
            f"趋势 X: 当前 MA{cfg.ma_short} 未在 MA{cfg.ma_long} 之上", close, None, None
        )
    window = df.iloc[-(cfg.cross_lookback + 1):]
    above = (window["ma_short"] > window["ma_long"]).reset_index(drop=True)
    cross_days = (~above.shift(1).fillna(False)) & above
    cross_idx = cross_days[cross_days].index.tolist()
    if not cross_idx:
        return _no_entry(
            f"趋势 X: 过去 {cfg.cross_lookback} 日无 MA{cfg.ma_short}/{cfg.ma_long} 金叉",
            close, None, None,
        )
    cross_date = window.iloc[cross_idx[-1]]["date"]
    reasons.append(
        f"趋势 OK: {cross_date} 金叉 (MA{cfg.ma_short}={today['ma_short']:.2f} > "
        f"MA{cfg.ma_long}={today['ma_long']:.2f})"
    )

    r = today["rsi"]
    if pd.isna(r) or not (cfg.rsi_entry_low <= r <= cfg.rsi_entry_high):
        reasons.append(f"动量 X: RSI={r:.1f} 不在 [{cfg.rsi_entry_low},{cfg.rsi_entry_high}]")
        return {"signal": False, "reasons": reasons,
                "entry_price": close, "stop_loss": None, "take_profit": None}
    reasons.append(f"动量 OK: RSI={r:.1f}")

    vol_mult = (
        float(today["volume"]) / float(today["vol_ma"])
        if pd.notna(today["vol_ma"]) and today["vol_ma"] > 0 else 0.0
    )
    if vol_mult < cfg.vol_breakout_mult:
        reasons.append(f"量能 X: 量比={vol_mult:.2f} < {cfg.vol_breakout_mult}")
        return {"signal": False, "reasons": reasons,
                "entry_price": close, "stop_loss": None, "take_profit": None}
    reasons.append(f"量能 OK: 量比={vol_mult:.2f}")

    if a is None:
        return _no_entry("ATR 缺失", close, None, None)

    return {
        "signal": True, "reasons": reasons, "entry_price": close,
        "stop_loss": close - cfg.atr_stop_mult * a,
        "take_profit": close + cfg.atr_target_mult * a,
    }


def exit_signal_from_enriched(
    enriched: pd.DataFrame, entry_price: float, entry_date: str,
    trailing_stop_price: Optional[float] = None, cfg: Optional[TimingConfig] = None,
) -> dict:
    """与 exit_signal 同, 但接收已 enrich 的 df."""
    cfg = cfg or TimingConfig()
    df = enriched
    today = df.iloc[-1]
    close = float(today["close"])
    a = float(today["atr"]) if pd.notna(today["atr"]) else None
    today_date = pd.to_datetime(today["date"])
    hold_days = (today_date - pd.to_datetime(entry_date)).days

    if trailing_stop_price is not None and close <= trailing_stop_price:
        return {"signal": True,
                "reason": f"trailing_stop: close={close:.2f} <= stop={trailing_stop_price:.2f}",
                "exit_price": close}
    if pd.notna(today["ma_long"]) and close < float(today["ma_long"]):
        return {"signal": True,
                "reason": f"break_ma{cfg.ma_long}: close={close:.2f} < MA{cfg.ma_long}={today['ma_long']:.2f}",
                "exit_price": close}
    if a is not None:
        target = entry_price + cfg.atr_target_mult * a
        if close >= target:
            return {"signal": True,
                    "reason": f"take_profit: close={close:.2f} >= target={target:.2f}",
                    "exit_price": close}
    r = today["rsi"]
    if pd.notna(r) and r >= cfg.rsi_overbought:
        return {"signal": True,
                "reason": f"overbought: RSI={r:.1f} >= {cfg.rsi_overbought}",
                "exit_price": close}
    if hold_days >= cfg.max_hold_days:
        return {"signal": True,
                "reason": f"time_stop: 持有 {hold_days} 天 >= {cfg.max_hold_days}",
                "exit_price": close}
    return {"signal": False, "reason": "持有", "exit_price": close}


def trailing_stop_from_enriched(
    enriched: pd.DataFrame, entry_price: float,
    prev_stop: Optional[float] = None, cfg: Optional[TimingConfig] = None,
) -> float:
    cfg = cfg or TimingConfig()
    today = enriched.iloc[-1]
    a = float(today["atr"]) if pd.notna(today["atr"]) else 0.0
    candidate = float(today["close"]) - cfg.atr_stop_mult * a
    base = prev_stop if prev_stop is not None else (entry_price - cfg.atr_stop_mult * a)
    return max(base, candidate)


def entry_signal(price_df: pd.DataFrame, cfg: Optional[TimingConfig] = None) -> dict:
    """
    判断 price_df 的最后一行 (= 当日) 是否触发入场.
    price_df: loader.get_daily 返回的 OHLCV (日期升序).
    """
    cfg = cfg or TimingConfig()
    if len(price_df) < cfg.ma_long + 5:
        return _no_entry("数据不足", None, None, None)

    df = enrich(price_df, cfg)
    today = df.iloc[-1]
    close = float(today["close"])
    a = float(today["atr"]) if pd.notna(today["atr"]) else None

    reasons: list[str] = []

    if not (pd.notna(today["ma_long"]) and today["ma_short"] > today["ma_long"]):
        return _no_entry(
            f"趋势 X: 当前 MA{cfg.ma_short} 未在 MA{cfg.ma_long} 之上", close, None, None
        )

    # 过去 N 日内 (含当日) 是否发生过金叉
    window = df.iloc[-(cfg.cross_lookback + 1):]
    above = (window["ma_short"] > window["ma_long"]).reset_index(drop=True)
    cross_days = (~above.shift(1).fillna(False)) & above
    cross_idx = cross_days[cross_days].index.tolist()
    if not cross_idx:
        return _no_entry(
            f"趋势 X: 过去 {cfg.cross_lookback} 日无 MA{cfg.ma_short}/{cfg.ma_long} 金叉",
            close, None, None,
        )
    cross_date = window.iloc[cross_idx[-1]]["date"]
    reasons.append(
        f"趋势 OK: {cross_date} 金叉 (MA{cfg.ma_short}={today['ma_short']:.2f} > "
        f"MA{cfg.ma_long}={today['ma_long']:.2f})"
    )

    r = today["rsi"]
    if pd.isna(r) or not (cfg.rsi_entry_low <= r <= cfg.rsi_entry_high):
        reasons.append(
            f"动量 X: RSI={r:.1f} 不在 [{cfg.rsi_entry_low},{cfg.rsi_entry_high}]"
        )
        return {"signal": False, "reasons": reasons,
                "entry_price": close, "stop_loss": None, "take_profit": None}
    reasons.append(f"动量 OK: RSI={r:.1f}")

    vol_mult = (
        float(today["volume"]) / float(today["vol_ma"])
        if pd.notna(today["vol_ma"]) and today["vol_ma"] > 0 else 0.0
    )
    if vol_mult < cfg.vol_breakout_mult:
        reasons.append(f"量能 X: 量比={vol_mult:.2f} < {cfg.vol_breakout_mult}")
        return {"signal": False, "reasons": reasons,
                "entry_price": close, "stop_loss": None, "take_profit": None}
    reasons.append(f"量能 OK: 量比={vol_mult:.2f}")

    if a is None:
        return _no_entry("ATR 缺失", close, None, None)

    return {
        "signal": True,
        "reasons": reasons,
        "entry_price": close,
        "stop_loss": close - cfg.atr_stop_mult * a,
        "take_profit": close + cfg.atr_target_mult * a,
    }


# ---------- 出场 ----------

def exit_signal(
    price_df: pd.DataFrame,
    entry_price: float,
    entry_date: str,
    trailing_stop_price: Optional[float] = None,
    cfg: Optional[TimingConfig] = None,
) -> dict:
    cfg = cfg or TimingConfig()
    df = enrich(price_df, cfg)
    today = df.iloc[-1]
    close = float(today["close"])
    a = float(today["atr"]) if pd.notna(today["atr"]) else None
    today_date = pd.to_datetime(today["date"])
    hold_days = (today_date - pd.to_datetime(entry_date)).days

    if trailing_stop_price is not None and close <= trailing_stop_price:
        return {"signal": True,
                "reason": f"trailing_stop: close={close:.2f} <= stop={trailing_stop_price:.2f}",
                "exit_price": close}

    if pd.notna(today["ma_long"]) and close < float(today["ma_long"]):
        return {"signal": True,
                "reason": f"break_ma{cfg.ma_long}: close={close:.2f} < MA{cfg.ma_long}={today['ma_long']:.2f}",
                "exit_price": close}

    if a is not None:
        target = entry_price + cfg.atr_target_mult * a
        if close >= target:
            return {"signal": True,
                    "reason": f"take_profit: close={close:.2f} >= target={target:.2f}",
                    "exit_price": close}

    r = today["rsi"]
    if pd.notna(r) and r >= cfg.rsi_overbought:
        return {"signal": True,
                "reason": f"overbought: RSI={r:.1f} >= {cfg.rsi_overbought}",
                "exit_price": close}

    if hold_days >= cfg.max_hold_days:
        return {"signal": True,
                "reason": f"time_stop: 持有 {hold_days} 天 >= {cfg.max_hold_days}",
                "exit_price": close}

    return {"signal": False, "reason": "持有", "exit_price": close}


# ---------- Trailing stop ----------

def trailing_stop(
    price_df: pd.DataFrame,
    entry_price: float,
    prev_stop: Optional[float] = None,
    cfg: Optional[TimingConfig] = None,
) -> float:
    """当前应设的浮动止损 = max(prev_stop, close - ATR * 2). 只上调, 不下调."""
    cfg = cfg or TimingConfig()
    df = enrich(price_df, cfg)
    today = df.iloc[-1]
    a = float(today["atr"]) if pd.notna(today["atr"]) else 0.0
    candidate = float(today["close"]) - cfg.atr_stop_mult * a
    base = prev_stop if prev_stop is not None else (entry_price - cfg.atr_stop_mult * a)
    return max(base, candidate)


# ---------- 全市场单日扫描 (daily_run 用) ----------

def scan_today_entries(
    loader,
    market: str,
    codes: list[str],
    asof: str,
    cfg: Optional[TimingConfig] = None,
    only_cached: bool = False,
    history_start: str = "2024-01-01",
) -> list[dict]:
    """
    对 codes 列表里每只股票, 检查 asof 当日是否触发 entry signal.
    返回触发列表, 每条含 code + entry_signal 输出 (entry_price/stop_loss/take_profit/reasons).
    only_cached=True 时跳过没本地缓存的股票, 避免在线 fetch 卡死.
    """
    cfg = cfg or TimingConfig()
    hits: list[dict] = []
    for code in codes:
        if only_cached:
            cache_path = loader.cache_dir / f"daily_{market}_{code}.parquet"
            if not cache_path.exists():
                continue
        try:
            px = loader.get_daily(market, code, history_start, asof)
        except Exception:
            continue
        if len(px) < cfg.ma_long + 5:
            continue
        sig = entry_signal(px, cfg)
        if sig["signal"]:
            hits.append({"code": code, **sig})
    return hits


# ---------- 历史扫描 (demo + 后续回测用) ----------

def scan_entries(price_df: pd.DataFrame, cfg: Optional[TimingConfig] = None) -> pd.DataFrame:
    """对历史的每一天回放 entry_signal, 返回所有触发日."""
    cfg = cfg or TimingConfig()
    df = enrich(price_df, cfg)
    hits = []
    for i in range(cfg.ma_long + 1, len(df)):
        sub = price_df.iloc[: i + 1]
        sig = entry_signal(sub, cfg)
        if sig["signal"]:
            row = df.iloc[i]
            hits.append({
                "date": row["date"],
                "close": float(row["close"]),
                "ma20": float(row["ma_short"]),
                "ma60": float(row["ma_long"]),
                "rsi": float(row["rsi"]),
                "vol_mult": float(row["volume"]) / float(row["vol_ma"]),
                "stop_loss": sig["stop_loss"],
                "take_profit": sig["take_profit"],
            })
    return pd.DataFrame(hits)
