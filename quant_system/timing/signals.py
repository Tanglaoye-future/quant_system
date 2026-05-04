"""
技术择时: 中线 (20-60 日持仓) 的入场 / 出场信号 + 移动止损.

M2（与 timing.regime 配合）:
  - 指数市况门: MarketRegimeGate（策略 screen / daily_run 外层）——指数收盘 > MA(N) 才允许新仓。
  - 单票层（本模块）: RSI 带宽可按 ATR% 微调、可选收阳/近端中位量、前 N 日收盘结构突破。
M3（在 M2 之上）:
  - RSI 入场带与指数市况/波动显式联动：`TimingRegimeContext` + `_effective_rsi_entry_band`。
  - 多周期一致性：更长周期的 RSI（同根日线）需不低于阈值。
  配置入口: config.yaml -> strategy.timing（由 timing_config_from_yaml_node 映射为 TimingConfig）。

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

from dataclasses import dataclass, fields
from typing import Optional

import numpy as np
import pandas as pd

from quant_system.timing.exit_taxonomy import exit_layer_from_reason
from quant_system.timing.regime import TimingRegimeContext


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
    # 额外过滤 (偏向提高胜率, 降低追高/高波动噪声交易)
    trend_strength_min: float = 0.005    # MA_short 相对 MA_long 的最小强度 (0.5%)
    chase_max: float = 0.06              # close 相对 MA_short 的最大偏离 (避免追高)
    max_risk_pct: float = 0.08           # (entry-stop)/entry 超过则放弃 (默认 8%)

    # --- M2（单票层；市况指数门控在 engine.strategy + timing.regime）---
    m2_regime_enabled: bool = False          # 若 True：BottomupTimingStrategy / daily_run 外层拦截新仓
    m2_regime_ma_days: int = 60              # 指数收盘 > SMA(m2_regime_ma_days)
    m2_rsi_atr_adjust: bool = False          # 用 ATR/close 放宽/收紧 RSI 入场带
    m2_rsi_atr_k: float = 400.0             # 下沿偏移 ≈ min(cap, ATR%/close * k) 的缩放
    m2_rsi_atr_cap: float = 8.0             # RSI 点数偏移上限
    m2_vol_green_bar: bool = False         # 要求收阳 (close>=open)
    m2_vol_median_lookback: int = 5         # 与当日量比较的 median 窗口
    m2_vol_median_mult: float = 1.0        # volume >= mult * median(vol); <=1 关闭
    m2_structure_lookback: int = 0         # 收盘突破过去 N 日最高收盘 (>0 启用)
    m2_structure_eps: float = 0.002       # 突破缓冲: close >= prev_max_close * (1-eps)

    # --- M3：RSI 与指数市况/波动显式联动 + 慢周期 RSI ---
    m3_regime_rsi_band: bool = False
    m3_reg_rsi_lo_widen_pts_per_ma_gap_1pct: float = 1.5
    m3_reg_rsi_lo_widen_cap: float = 8.0
    m3_reg_vol_tighten_hi: bool = False
    m3_reg_vol_hi_tighten_k: float = 18.0
    m3_reg_vol_hi_tighten_cap: float = 6.0
    m3_reg_index_atr_pct_median_window: int = 20

    m3_mtf_rsi_enabled: bool = False
    m3_mtf_rsi_period: int = 28
    m3_mtf_rsi_min: float = 48.0

    # --- M5：为 true 时技术出场未触发且指数市况门不通过则强制 EXIT（REGIME 层）---
    m5_regime_exit_enabled: bool = False


def timing_config_from_yaml_node(node: dict | None) -> TimingConfig:
    """从 config.yaml `strategy.timing` 映射到 TimingConfig；未知键忽略。"""
    node = node or {}
    valid = {f.name for f in fields(TimingConfig)}
    kwargs = {k: v for k, v in node.items() if k in valid}
    return TimingConfig(**kwargs)


def _effective_rsi_entry_band(
    cfg: TimingConfig,
    close: float,
    atr_val: float | None,
    regime_ctx: TimingRegimeContext | None = None,
) -> tuple[float, float]:
    lo, hi = cfg.rsi_entry_low, cfg.rsi_entry_high
    if cfg.m2_rsi_atr_adjust and atr_val is not None and close > 0:
        atr_pct = float(atr_val) / float(close)
        delta = min(cfg.m2_rsi_atr_cap, atr_pct * cfg.m2_rsi_atr_k)
        lo, hi = lo - delta, hi + min(cfg.m2_rsi_atr_cap * 0.5, delta * 0.5)

    if regime_ctx is not None:
        if cfg.m3_regime_rsi_band:
            r = regime_ctx.index_close_vs_ma
            if r is not None and r > 0:
                gap_pct = r * 100.0
                bonus_lo = min(
                    cfg.m3_reg_rsi_lo_widen_cap,
                    gap_pct * cfg.m3_reg_rsi_lo_widen_pts_per_ma_gap_1pct,
                )
                lo -= bonus_lo
        if cfg.m3_reg_vol_tighten_hi:
            rel = regime_ctx.index_atr_pct_rel
            if rel is not None and rel > 0:
                tight_hi = min(cfg.m3_reg_vol_hi_tighten_cap, rel * cfg.m3_reg_vol_hi_tighten_k)
                hi -= tight_hi

    lo = float(max(1.0, min(lo, 92.0)))
    hi = float(max(lo + 2.0, min(hi, 99.0)))
    return lo, hi


def _m2_volume_quality_fail(df: pd.DataFrame, today: pd.Series, cfg: TimingConfig, reasons: list[str]) -> bool:
    """返回 True 表示未通过 M2 量能附加规则。"""
    if cfg.m2_vol_green_bar:
        o = float(today["open"]) if pd.notna(today["open"]) else None
        c = float(today["close"])
        if o is not None and c < o:
            reasons.append("M2量能X: 非收阳(close<open)")
            return True
    if cfg.m2_vol_median_mult > 1.0:
        lb = max(2, int(cfg.m2_vol_median_lookback))
        tail = df.iloc[-lb:]
        med = pd.to_numeric(tail["volume"], errors="coerce").median()
        v0 = float(today["volume"]) if pd.notna(today["volume"]) else 0.0
        if pd.isna(med) or med <= 0:
            reasons.append("M2量能X: median 量无效")
            return True
        if v0 < float(med) * cfg.m2_vol_median_mult:
            reasons.append(
                f"M2量能X: 量{v0:.0f} < median×{cfg.m2_vol_median_mult:.2f} ({float(med)*cfg.m2_vol_median_mult:.0f})"
            )
            return True
    return False


def _m2_structure_fail(df: pd.DataFrame, today: pd.Series, cfg: TimingConfig, reasons: list[str]) -> bool:
    """返回 True 表示未通过结构过滤。"""
    n = int(cfg.m2_structure_lookback)
    if n <= 0:
        return False
    if len(df) < n + 2:
        reasons.append("M2结构X: 历史不足")
        return True
    prev = df["close"].iloc[-(n + 1): -1]
    prev_max = float(pd.to_numeric(prev, errors="coerce").max())
    close = float(today["close"])
    thr = prev_max * (1.0 - cfg.m2_structure_eps)
    if close < thr:
        reasons.append(f"M2结构X: 收盘 {close:.2f} < 前{n}日高收×(1-ε)={thr:.2f}")
        return True
    reasons.append(f"M2结构OK: 收盘突破前{n}日最高收盘(含缓冲)")
    return False


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
    if cfg.m3_mtf_rsi_enabled:
        p = max(int(cfg.m3_mtf_rsi_period), int(cfg.rsi_period) + 1)
        out["rsi_mtf"] = rsi(out["close"], p)
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


def entry_signal_from_enriched(
    enriched: pd.DataFrame,
    cfg: Optional[TimingConfig] = None,
    regime_ctx: Optional[TimingRegimeContext] = None,
) -> dict:
    """与 entry_signal 同, 但接收已 enrich 的 df (避免重复 enrich, 用于回测加速). regime_ctx 供 M3 RSI 带联动。"""
    cfg = cfg or TimingConfig()
    min_rows = cfg.ma_long + 5
    if cfg.m3_mtf_rsi_enabled:
        min_rows = max(min_rows, int(cfg.m3_mtf_rsi_period) + 3)
    if len(enriched) < min_rows:
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
    # 趋势强度: MA_short 与 MA_long 差距太小, 容易假突破/来回切换
    if pd.notna(today["ma_short"]) and pd.notna(today["ma_long"]) and today["ma_long"] > 0:
        strength = float(today["ma_short"] / today["ma_long"] - 1.0)
        if strength < cfg.trend_strength_min:
            return _no_entry(
                f"趋势 X: 强度不足 (MA差={strength*100:.2f}% < {cfg.trend_strength_min*100:.2f}%)",
                close, None, None,
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
    rsi_lo, rsi_hi = _effective_rsi_entry_band(cfg, close, a, regime_ctx)
    if pd.isna(r) or not (rsi_lo <= float(r) <= rsi_hi):
        reasons.append(f"动量 X: RSI={r:.1f} 不在 [{rsi_lo:.1f},{rsi_hi:.1f}]")
        return {"signal": False, "reasons": reasons,
                "entry_price": close, "stop_loss": None, "take_profit": None}
    reasons.append(f"动量 OK: RSI={r:.1f} (带 [{rsi_lo:.1f},{rsi_hi:.1f}])")

    if cfg.m3_mtf_rsi_enabled:
        if "rsi_mtf" not in df.columns:
            return _no_entry(
                "M3 X: 无 rsi_mtf 列(需以 m3_mtf_rsi_enabled 的 cfg 调用 enrich)", close, None, None
            )
        rm = today["rsi_mtf"]
        if pd.isna(rm) or float(rm) < cfg.m3_mtf_rsi_min:
            reasons.append(
                f"M3多周期X: RSI({cfg.m3_mtf_rsi_period})={rm} < {cfg.m3_mtf_rsi_min}"
            )
            return {"signal": False, "reasons": reasons,
                    "entry_price": close, "stop_loss": None, "take_profit": None}
        reasons.append(
            f"M3多周期OK: RSI({cfg.m3_mtf_rsi_period})={float(rm):.1f} >= {cfg.m3_mtf_rsi_min}"
        )

    vol_mult = (
        float(today["volume"]) / float(today["vol_ma"])
        if pd.notna(today["vol_ma"]) and today["vol_ma"] > 0 else 0.0
    )
    if vol_mult < cfg.vol_breakout_mult:
        reasons.append(f"量能 X: 量比={vol_mult:.2f} < {cfg.vol_breakout_mult}")
        return {"signal": False, "reasons": reasons,
                "entry_price": close, "stop_loss": None, "take_profit": None}
    reasons.append(f"量能 OK: 量比={vol_mult:.2f}")

    if _m2_volume_quality_fail(df, today, cfg, reasons):
        return {"signal": False, "reasons": reasons,
                "entry_price": close, "stop_loss": None, "take_profit": None}
    if _m2_structure_fail(df, today, cfg, reasons):
        return {"signal": False, "reasons": reasons,
                "entry_price": close, "stop_loss": None, "take_profit": None}

    if a is None:
        return _no_entry("ATR 缺失", close, None, None)

    # 不追高: close 明显高于 MA_short, 容易回撤洗出 (胜率差)
    if pd.notna(today["ma_short"]) and today["ma_short"] > 0:
        chase = float(close / float(today["ma_short"]) - 1.0)
        if chase > cfg.chase_max:
            return _no_entry(
                f"追高 X: close 相对 MA{cfg.ma_short} 偏离 {chase*100:.1f}% > {cfg.chase_max*100:.0f}%",
                close, None, None,
            )

    stop = close - cfg.atr_stop_mult * a
    risk_pct = (close - stop) / close if close else 0.0
    if risk_pct > cfg.max_risk_pct:
        return _no_entry(
            f"风险 X: 单笔风险 {risk_pct*100:.1f}% > {cfg.max_risk_pct*100:.0f}%",
            close, None, None,
        )

    return {
        "signal": True, "reasons": reasons, "entry_price": close,
        "stop_loss": stop,
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
        rs = f"trailing_stop: close={close:.2f} <= stop={trailing_stop_price:.2f}"
        return {"signal": True, "reason": rs, "exit_price": close, "exit_layer": exit_layer_from_reason(rs)}
    if pd.notna(today["ma_long"]) and close < float(today["ma_long"]):
        rs = f"break_ma{cfg.ma_long}: close={close:.2f} < MA{cfg.ma_long}={today['ma_long']:.2f}"
        return {"signal": True, "reason": rs, "exit_price": close, "exit_layer": exit_layer_from_reason(rs)}
    if a is not None:
        target = entry_price + cfg.atr_target_mult * a
        if close >= target:
            rs = f"take_profit: close={close:.2f} >= target={target:.2f}"
            return {"signal": True, "reason": rs, "exit_price": close, "exit_layer": exit_layer_from_reason(rs)}
    r = today["rsi"]
    if pd.notna(r) and r >= cfg.rsi_overbought:
        rs = f"overbought: RSI={r:.1f} >= {cfg.rsi_overbought}"
        return {"signal": True, "reason": rs, "exit_price": close, "exit_layer": exit_layer_from_reason(rs)}
    if hold_days >= cfg.max_hold_days:
        rs = f"time_stop: 持有 {hold_days} 天 >= {cfg.max_hold_days}"
        return {"signal": True, "reason": rs, "exit_price": close, "exit_layer": exit_layer_from_reason(rs)}
    return {"signal": False, "reason": "持有", "exit_price": close, "exit_layer": ""}


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


def entry_signal(
    price_df: pd.DataFrame,
    cfg: Optional[TimingConfig] = None,
    regime_ctx: Optional[TimingRegimeContext] = None,
) -> dict:
    """
    判断 price_df 的最后一行 (= 当日) 是否触发入场.
    price_df: loader.get_daily 返回的 OHLCV (日期升序).
    regime_ctx: 可选指数上下文（M3 RSI 带联动）；与 entry_signal_from_enriched 语义对齐。
    """
    cfg = cfg or TimingConfig()
    min_rows = cfg.ma_long + 5
    if cfg.m3_mtf_rsi_enabled:
        min_rows = max(min_rows, int(cfg.m3_mtf_rsi_period) + 3)
    if len(price_df) < min_rows:
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

    if pd.notna(today["ma_short"]) and pd.notna(today["ma_long"]) and today["ma_long"] > 0:
        strength = float(today["ma_short"] / today["ma_long"] - 1.0)
        if strength < cfg.trend_strength_min:
            return _no_entry(
                f"趋势 X: 强度不足 (MA差={strength*100:.2f}% < {cfg.trend_strength_min*100:.2f}%)",
                close, None, None,
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
    rsi_lo, rsi_hi = _effective_rsi_entry_band(cfg, close, a, regime_ctx)
    if pd.isna(r) or not (rsi_lo <= float(r) <= rsi_hi):
        reasons.append(f"动量 X: RSI={r:.1f} 不在 [{rsi_lo:.1f},{rsi_hi:.1f}]")
        return {"signal": False, "reasons": reasons,
                "entry_price": close, "stop_loss": None, "take_profit": None}
    reasons.append(f"动量 OK: RSI={r:.1f} (带 [{rsi_lo:.1f},{rsi_hi:.1f}])")

    if cfg.m3_mtf_rsi_enabled:
        if "rsi_mtf" not in df.columns:
            return _no_entry(
                "M3 X: 无 rsi_mtf 列(需以 m3_mtf_rsi_enabled 的 cfg 调用 enrich)", close, None, None
            )
        rm = today["rsi_mtf"]
        if pd.isna(rm) or float(rm) < cfg.m3_mtf_rsi_min:
            reasons.append(
                f"M3多周期X: RSI({cfg.m3_mtf_rsi_period})={rm} < {cfg.m3_mtf_rsi_min}"
            )
            return {"signal": False, "reasons": reasons,
                    "entry_price": close, "stop_loss": None, "take_profit": None}
        reasons.append(
            f"M3多周期OK: RSI({cfg.m3_mtf_rsi_period})={float(rm):.1f} >= {cfg.m3_mtf_rsi_min}"
        )

    vol_mult = (
        float(today["volume"]) / float(today["vol_ma"])
        if pd.notna(today["vol_ma"]) and today["vol_ma"] > 0 else 0.0
    )
    if vol_mult < cfg.vol_breakout_mult:
        reasons.append(f"量能 X: 量比={vol_mult:.2f} < {cfg.vol_breakout_mult}")
        return {"signal": False, "reasons": reasons,
                "entry_price": close, "stop_loss": None, "take_profit": None}
    reasons.append(f"量能 OK: 量比={vol_mult:.2f}")

    if _m2_volume_quality_fail(df, today, cfg, reasons):
        return {"signal": False, "reasons": reasons,
                "entry_price": close, "stop_loss": None, "take_profit": None}
    if _m2_structure_fail(df, today, cfg, reasons):
        return {"signal": False, "reasons": reasons,
                "entry_price": close, "stop_loss": None, "take_profit": None}

    if a is None:
        return _no_entry("ATR 缺失", close, None, None)

    if pd.notna(today["ma_short"]) and today["ma_short"] > 0:
        chase = float(close / float(today["ma_short"]) - 1.0)
        if chase > cfg.chase_max:
            return _no_entry(
                f"追高 X: close 相对 MA{cfg.ma_short} 偏离 {chase*100:.1f}% > {cfg.chase_max*100:.0f}%",
                close, None, None,
            )

    stop = close - cfg.atr_stop_mult * a
    risk_pct = (close - stop) / close if close else 0.0
    if risk_pct > cfg.max_risk_pct:
        return _no_entry(
            f"风险 X: 单笔风险 {risk_pct*100:.1f}% > {cfg.max_risk_pct*100:.0f}%",
            close, None, None,
        )

    return {
        "signal": True,
        "reasons": reasons,
        "entry_price": close,
        "stop_loss": stop,
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
        rs = f"trailing_stop: close={close:.2f} <= stop={trailing_stop_price:.2f}"
        return {"signal": True, "reason": rs, "exit_price": close, "exit_layer": exit_layer_from_reason(rs)}

    if pd.notna(today["ma_long"]) and close < float(today["ma_long"]):
        rs = f"break_ma{cfg.ma_long}: close={close:.2f} < MA{cfg.ma_long}={today['ma_long']:.2f}"
        return {"signal": True, "reason": rs, "exit_price": close, "exit_layer": exit_layer_from_reason(rs)}

    if a is not None:
        target = entry_price + cfg.atr_target_mult * a
        if close >= target:
            rs = f"take_profit: close={close:.2f} >= target={target:.2f}"
            return {"signal": True, "reason": rs, "exit_price": close, "exit_layer": exit_layer_from_reason(rs)}

    r = today["rsi"]
    if pd.notna(r) and r >= cfg.rsi_overbought:
        rs = f"overbought: RSI={r:.1f} >= {cfg.rsi_overbought}"
        return {"signal": True, "reason": rs, "exit_price": close, "exit_layer": exit_layer_from_reason(rs)}

    if hold_days >= cfg.max_hold_days:
        rs = f"time_stop: 持有 {hold_days} 天 >= {cfg.max_hold_days}"
        return {"signal": True, "reason": rs, "exit_price": close, "exit_layer": exit_layer_from_reason(rs)}

    return {"signal": False, "reason": "持有", "exit_price": close, "exit_layer": ""}


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
    regime_ctx: Optional[TimingRegimeContext] = None,
) -> list[dict]:
    """
    对 codes 列表里每只股票, 检查 asof 当日是否触发 entry signal.
    返回触发列表, 每条含 code + entry_signal 输出 (entry_price/stop_loss/take_profit/reasons).
    only_cached=True 时跳过没本地缓存的股票, 避免在线 fetch 卡死.
    regime_ctx: 与 BottomupTimingStrategy / M3 对齐，传入 entry_signal。
    """
    cfg = cfg or TimingConfig()
    hits: list[dict] = []
    min_rows = cfg.ma_long + 5
    if cfg.m3_mtf_rsi_enabled:
        min_rows = max(min_rows, int(cfg.m3_mtf_rsi_period) + 3)
    for code in codes:
        if only_cached:
            # 复权模式不同, cache 文件名不同: 统一走 loader
            cache_path = loader.daily_cache_path(market, code)
            if not cache_path.exists():
                continue
        try:
            px = loader.get_daily(market, code, history_start, asof)
        except Exception:
            continue
        if len(px) < min_rows:
            continue
        sig = entry_signal(px, cfg, regime_ctx=regime_ctx)
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
