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

from quant_system.strategies.equity_factor.timing.exit_taxonomy import exit_layer_from_reason
from quant_system.strategies.equity_factor.timing.regime import TimingRegimeContext


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

    # --- M3 南向资金联动（仅 HK）：南向今日强 → 放宽 RSI 带 + 量能门槛 ---
    m3_southbound_widen_enabled: bool = False
    m3_southbound_ma_window: int = 20
    m3_southbound_threshold: float = 0.5      # strength = (today-MA20)/|MA20|；>threshold 触发
    m3_southbound_widen_lo_pts: float = 5.0   # RSI 下沿放宽点数（接受更深超卖入场）
    m3_southbound_widen_hi_pts: float = 3.0   # RSI 上沿放宽点数（追高动量也宽松）
    m3_southbound_vol_relax: float = 0.3      # 量能门槛 vol_breakout_mult × (1-relax)（南向强买时 1.5×→1.05×）

    # --- M5：为 true 时技术出场未触发且指数市况门不通过则强制 EXIT（REGIME 层）---
    m5_regime_exit_enabled: bool = False

    # --- M5 部分出场 (main HEAD): ATR 止盈触发 → 卖 partial_exit_pct，剩余切换到更宽松 trailing stop ---
    partial_exit_enabled: bool = False
    partial_exit_pct: float = 0.5          # 首次止盈时出场比例（0.5 = 50%）
    partial_exit_trail_mult: float = 1.5   # 剩余仓位的 trailing stop 倍数扩展（相对 atr_stop_mult）

    # --- L9-A: regime-aware partial_exit ---
    # 仅当 partial_exit_enabled=True 时生效。True 时：基准指数收盘 > MA(partial_exit_regime_ma_days)
    # (即"牛市"段) → 跳过 partial_exit，走默认全平 TP（让趋势奔跑）；
    # 基准 <= MA → 保留 partial_exit（震荡/熊市锁利）。
    # 解决 8y 牛市段 partial_exit 早锁利导致的 Sharpe / 收益拖累；默认 False = 行为兼容 L8D2.
    partial_exit_regime_filter: bool = False
    partial_exit_regime_ma_days: int = 200

    # --- M5 L1 (worktree HK): TP 命中时不卖任何仓，仅上移 stop + 启用 runner trail ---
    # 注：与 partial_exit_enabled 互斥使用——同时启用时 partial_exit 优先（main 主线）
    tp_runner_enabled: bool = False
    atr_stop_mult_runner: float = 0.0        # runner 模式下使用的 trail 倍数；<=0 沿用 atr_stop_mult
    tp_runner_lock_atr_mult: float = 1.0     # promote 时把 stop 拉到 target - 这个倍数 × ATR

    # --- Level 3 (main HEAD): 入场信号替换（突破+量能）---
    # True  → 取消 MA20/60 金叉要求，改为「收盘创 m2_structure_lookback 日新高 + 量能确认」
    # False → 原 MA20/60 金叉逻辑（默认）
    m2_breakout_mode: bool = False
    # m2_breakout_mode=True 时，要求收盘价 > MA60（趋势确认，替代金叉）
    m2_breakout_ma_trend: bool = True

    # --- 价格位置过滤（L6 防追高）---
    # 拒绝在价格区间高位入场。price_position = (close - min_N) / (max_N - min_N).
    # =1 表示创 N 日新高位置；=0 表示 N 日最低。
    # entry_price_position_max=1.0 → 不过滤（默认，兼容旧行为）。
    # 实盘建议 0.6-0.8（避开顶部 20-40%）；与 zhuang 的 entry_price_position_min 互补。
    entry_price_position_max: float = 1.0
    entry_price_position_lookback: int = 20

    # --- Pullback 模式（L7 低位识别，与突破/金叉模式互斥）---
    # 主动识别"大趋势在 + 回调到 MA + 量缩 + RSI 反弹"的低位机会
    # 与 m2_breakout_mode 互斥；同时启用以 m2_pullback_mode 优先
    m2_pullback_mode: bool = False
    # 大趋势过滤：MA60 必须在 MA(pullback_long_trend_ma) 之上
    pullback_require_long_trend: bool = True
    pullback_long_trend_ma: int = 200
    # 价格位置：在近 N 日区间下半段
    pullback_price_position_max: float = 0.5
    pullback_price_position_lookback: int = 20
    # RSI 反弹带（低于追高模式的 50-70）
    pullback_rsi_low: float = 35.0
    pullback_rsi_high: float = 55.0
    # 量缩：当日量 <= 近 N 日均量 × ratio
    pullback_vol_max_ratio: float = 1.0
    pullback_vol_lookback: int = 5
    # 企稳信号：近 N 日内至少 M 个收阳
    pullback_green_bars_min: int = 2
    pullback_green_bars_lookback: int = 5

    # --- Plan B 强势 regime gate（B1）---
    # 仅在 HS300 自身强势时入场（避免熊市 catching falling knives）
    pullback_b1_regime_strict: bool = False
    pullback_b1_require_ma200: bool = True       # index > MA200
    pullback_b1_require_ma_short: bool = True    # index > MA60 (用现有 index_close_vs_ma)
    pullback_b1_max_drawdown_from_high: float = -0.05  # index drawdown from 20d high 不深于 -5%

    # --- Plan B 反弹确认（B2）---
    pullback_b2_reversal_required: bool = False
    pullback_b2_higher_low_lookback: int = 5      # 今日 low > 前 N 日 low 的最小值
    pullback_b2_close_above_ma_short: bool = True # close > MA20 (反弹已发生)

    # --- Plan B 相对强度（B3）---
    # 个股 20d 收益 - 指数 20d 收益 >= threshold (默认 None=关闭)
    pullback_b3_relative_strength_min: float | None = None
    pullback_b3_lookback: int = 20


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
        # 南向强买放宽 RSI 带（下沿优先：HK 折价策略可吃更深超卖；上沿次之）
        if cfg.m3_southbound_widen_enabled:
            sb = getattr(regime_ctx, "southbound_strength", None)
            if sb is not None and sb > cfg.m3_southbound_threshold:
                lo -= float(cfg.m3_southbound_widen_lo_pts)
                hi += float(cfg.m3_southbound_widen_hi_pts)

    lo = float(max(1.0, min(lo, 92.0)))
    hi = float(max(lo + 2.0, min(hi, 99.0)))
    return lo, hi


def _effective_vol_breakout_mult(cfg: TimingConfig, regime_ctx: TimingRegimeContext | None) -> float:
    """量能门槛 — 启用南向信号且当日强买时，降低 vol_breakout_mult 阈值（让更多候选过量能筛）。"""
    base = float(cfg.vol_breakout_mult)
    if regime_ctx is not None and cfg.m3_southbound_widen_enabled:
        sb = getattr(regime_ctx, "southbound_strength", None)
        if sb is not None and sb > cfg.m3_southbound_threshold:
            base = base * max(0.1, 1.0 - float(cfg.m3_southbound_vol_relax))
    return base


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


def _pullback_entry_check(
    df: pd.DataFrame,
    cfg: TimingConfig,
    a: float | None,
    close: float,
    reasons: list[str],
    regime_ctx: TimingRegimeContext | None = None,
) -> dict:
    """
    L7 Pullback 模式：主动识别"大趋势在 + 回调到 MA + 量缩 + RSI 反弹"低位机会.

    基础检查 (B0):
      1. 大趋势 OK: MA60 > MA(pullback_long_trend_ma=200)  (require_long_trend=True)
      2. 价格位置: (close - low_N) / (high_N - low_N) <= pullback_price_position_max (0.5)
      3. RSI 反弹带: pullback_rsi_low <= RSI <= pullback_rsi_high  (35-55)
      4. 量缩: 当日 volume <= avg(volume, N) × pullback_vol_max_ratio (1.0×5d)
      5. 企稳: 近 N 日内至少 M 个收阳 (2/5)

    Plan B 增量检查（pullback_b1/b2/b3_* 开关启用时叠加）:
      B1 (regime_strict): HS300 > MA200 AND > MA60 AND 20d drawdown 不深
      B2 (reversal_required): higher_low + close > MA20 (确认反弹已开始)
      B3 (relative_strength): 个股 20d 收益 - 指数 20d 收益 >= 阈值
    """
    today = df.iloc[-1]

    # ── Plan B1: 强势 regime gate (基于指数侧 context) ────────────────────────
    if cfg.pullback_b1_regime_strict and regime_ctx is not None:
        if cfg.pullback_b1_require_ma200:
            v = regime_ctx.index_close_vs_ma200
            if v is None or v <= 0:
                return _no_entry(
                    f"B1 X: 指数未 > MA200 (vs_ma200={v})", close, None, None,
                )
            reasons.append(f"B1 OK: 指数 > MA200 ({v*100:+.1f}%)")
        if cfg.pullback_b1_require_ma_short:
            v = regime_ctx.index_close_vs_ma
            if v is None or v <= 0:
                return _no_entry(
                    f"B1 X: 指数未 > MA60 (vs_ma={v})", close, None, None,
                )
            reasons.append(f"B1 OK: 指数 > MA60 ({v*100:+.1f}%)")
        dd = regime_ctx.index_drawdown_from_20d_high
        if dd is not None and dd < cfg.pullback_b1_max_drawdown_from_high:
            return _no_entry(
                f"B1 X: 指数已从 20d 高点回撤 {dd*100:.1f}% "
                f"< {cfg.pullback_b1_max_drawdown_from_high*100:.1f}%",
                close, None, None,
            )
        if dd is not None:
            reasons.append(f"B1 OK: 指数 20d dd={dd*100:.1f}%")

    # 1. 大趋势 OK：MA60 > MA200
    if cfg.pullback_require_long_trend:
        n_long = int(cfg.pullback_long_trend_ma)
        ma_long_trend = sma(df["close"], n_long).iloc[-1]
        ma60 = float(today["ma_long"]) if pd.notna(today["ma_long"]) else None
        if pd.isna(ma_long_trend) or ma60 is None:
            return _no_entry(f"大趋势 X: MA{n_long} 不足", close, None, None)
        if not (ma60 > float(ma_long_trend)):
            return _no_entry(
                f"大趋势 X: MA{cfg.ma_long}({ma60:.2f}) <= MA{n_long}({float(ma_long_trend):.2f})",
                close, None, None,
            )
        reasons.append(f"大趋势 OK: MA{cfg.ma_long}({ma60:.2f}) > MA{n_long}({float(ma_long_trend):.2f})")

    # 2. 价格位置低：近 N 日下半段
    lb = max(2, int(cfg.pullback_price_position_lookback))
    if len(df) < lb:
        return _no_entry(f"价格位置 X: 历史不足 {lb} 日", close, None, None)
    tail = df.iloc[-lb:]
    lo = float(pd.to_numeric(tail["low"], errors="coerce").min())
    hi = float(pd.to_numeric(tail["high"], errors="coerce").max())
    if hi <= lo:
        return _no_entry("价格位置 X: 区间退化", close, None, None)
    pos = (close - lo) / (hi - lo)
    if pos > cfg.pullback_price_position_max:
        return _no_entry(
            f"价格位置 X: pos={pos:.2f} > {cfg.pullback_price_position_max:.2f} "
            f"(近{lb}日 [{lo:.2f}, {hi:.2f}])",
            close, None, None,
        )
    reasons.append(f"价格位置 OK: pos={pos:.2f} <= {cfg.pullback_price_position_max:.2f}")

    # 3. RSI 反弹带
    r = today["rsi"]
    if pd.isna(r) or not (cfg.pullback_rsi_low <= float(r) <= cfg.pullback_rsi_high):
        return _no_entry(
            f"RSI X: {r:.1f} 不在反弹带 [{cfg.pullback_rsi_low}, {cfg.pullback_rsi_high}]",
            close, None, None,
        )
    reasons.append(f"RSI OK: {float(r):.1f} 在反弹带")

    # 4. 量缩
    vlb = max(2, int(cfg.pullback_vol_lookback))
    if len(df) < vlb + 1:
        return _no_entry(f"量缩 X: 历史不足 {vlb} 日", close, None, None)
    vol_tail = df["volume"].iloc[-(vlb + 1):-1]  # 最近 N 日 (不含今日)
    avg_vol = float(pd.to_numeric(vol_tail, errors="coerce").mean())
    vol_today = float(today["volume"]) if pd.notna(today["volume"]) else 0.0
    if avg_vol <= 0:
        return _no_entry("量缩 X: 均量无效", close, None, None)
    vol_ratio = vol_today / avg_vol
    if vol_ratio > cfg.pullback_vol_max_ratio:
        return _no_entry(
            f"量缩 X: 量比={vol_ratio:.2f} > {cfg.pullback_vol_max_ratio:.2f}",
            close, None, None,
        )
    reasons.append(f"量缩 OK: 量比={vol_ratio:.2f}")

    # 5. 企稳信号：近 N 日内 >= M 个收阳
    gbb = max(1, int(cfg.pullback_green_bars_lookback))
    if len(df) < gbb:
        return _no_entry(f"企稳 X: 历史不足 {gbb} 日", close, None, None)
    recent = df.iloc[-gbb:]
    green_bars = int(((recent["close"] >= recent["open"]) & recent["close"].notna()).sum())
    if green_bars < int(cfg.pullback_green_bars_min):
        return _no_entry(
            f"企稳 X: 近{gbb}日收阳数={green_bars} < {cfg.pullback_green_bars_min}",
            close, None, None,
        )
    reasons.append(f"企稳 OK: 近{gbb}日收阳数={green_bars} >= {cfg.pullback_green_bars_min}")

    # ── Plan B2: 反弹确认 (higher low + close > MA20) ─────────────────────
    if cfg.pullback_b2_reversal_required:
        hll = max(2, int(cfg.pullback_b2_higher_low_lookback))
        if len(df) >= hll + 1:
            recent_lows = df["low"].iloc[-(hll + 1):-1]
            min_recent_low = float(pd.to_numeric(recent_lows, errors="coerce").min())
            today_low = float(today["low"]) if pd.notna(today["low"]) else 0
            if today_low <= min_recent_low:
                return _no_entry(
                    f"B2 X: 未形成 higher low (今日 low {today_low:.2f} <= "
                    f"近{hll}日最低 {min_recent_low:.2f})",
                    close, None, None,
                )
            reasons.append(f"B2 OK: higher low (今 {today_low:.2f} > 近 {min_recent_low:.2f})")
        if cfg.pullback_b2_close_above_ma_short:
            ma_s = today.get("ma_short")
            if pd.isna(ma_s) or close <= float(ma_s):
                return _no_entry(
                    f"B2 X: close({close:.2f}) <= MA{cfg.ma_short}({ma_s})",
                    close, None, None,
                )
            reasons.append(f"B2 OK: close > MA{cfg.ma_short}")

    # ── Plan B3: 相对强度过滤 (个股 20d 跑赢指数) ──────────────────────────
    if cfg.pullback_b3_relative_strength_min is not None:
        rsl = max(2, int(cfg.pullback_b3_lookback))
        if len(df) >= rsl + 1 and regime_ctx is not None and regime_ctx.index_return_20d is not None:
            p_now = close
            p_n = float(pd.to_numeric(df["close"].iloc[-(rsl + 1)], errors="coerce"))
            if p_n > 0:
                stock_ret = p_now / p_n - 1.0
                excess = stock_ret - float(regime_ctx.index_return_20d)
                if excess < cfg.pullback_b3_relative_strength_min:
                    return _no_entry(
                        f"B3 X: 个股20d超额 {excess*100:+.1f}% < "
                        f"{cfg.pullback_b3_relative_strength_min*100:.1f}%",
                        close, None, None,
                    )
                reasons.append(f"B3 OK: 个股20d超额 {excess*100:+.1f}%")

    if a is None:
        return _no_entry("ATR 缺失", close, None, None)

    # 通过所有 pullback 检查 → 信号成立
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
    if cfg.m2_pullback_mode and cfg.pullback_require_long_trend:
        min_rows = max(min_rows, int(cfg.pullback_long_trend_ma) + 5)
    if len(enriched) < min_rows:
        return _no_entry("数据不足", None, None, None)
    df = enriched
    today = df.iloc[-1]
    close = float(today["close"])
    a = float(today["atr"]) if pd.notna(today["atr"]) else None
    reasons: list[str] = []

    # ── Pullback 模式（L7 低位识别）— 与突破/金叉模式互斥 ────────────────────
    if cfg.m2_pullback_mode:
        return _pullback_entry_check(df, cfg, a, close, reasons, regime_ctx)

    # ── Level 3 突破模式 / 原金叉模式 分支 ──────────────────────────────────
    if cfg.m2_breakout_mode:
        # --- 突破模式: 收盘创 N 日新高 + MA60 趋势确认 ---
        n_high = int(cfg.m2_structure_lookback) if cfg.m2_structure_lookback > 0 else 20
        if len(df) < n_high + 2:
            return _no_entry("数据不足(突破窗口)", close, None, None)
        # MA60 趋势确认（替代金叉）
        if cfg.m2_breakout_ma_trend:
            if not (pd.notna(today["ma_long"]) and close > float(today["ma_long"])):
                return _no_entry(
                    f"趋势 X: close({close:.2f}) < MA{cfg.ma_long}({today['ma_long']:.2f})",
                    close, None, None,
                )
            reasons.append(f"趋势 OK: close({close:.2f}) > MA{cfg.ma_long}({today['ma_long']:.2f})")
        # 收盘突破 N 日新高（包含缓冲 eps）
        prev_closes = df["close"].iloc[-(n_high + 1):-1]
        prev_high = float(prev_closes.max())
        thr = prev_high * (1.0 - cfg.m2_structure_eps)
        if close < thr:
            return _no_entry(
                f"突破 X: close({close:.2f}) < 前{n_high}日最高收盘{prev_high:.2f}×(1-ε)={thr:.2f}",
                close, None, None,
            )
        reasons.append(f"突破 OK: close({close:.2f}) 创前{n_high}日新高(前高={prev_high:.2f})")
    else:
        # --- 原金叉模式 ---
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
    vol_thr = _effective_vol_breakout_mult(cfg, regime_ctx)
    if vol_mult < vol_thr:
        reasons.append(f"量能 X: 量比={vol_mult:.2f} < {vol_thr:.2f}")
        return {"signal": False, "reasons": reasons,
                "entry_price": close, "stop_loss": None, "take_profit": None}
    reasons.append(f"量能 OK: 量比={vol_mult:.2f} (阈={vol_thr:.2f})")

    if _m2_volume_quality_fail(df, today, cfg, reasons):
        return {"signal": False, "reasons": reasons,
                "entry_price": close, "stop_loss": None, "take_profit": None}
    # 突破模式：收盘新高已是主逻辑，无需二次 structure_fail 过滤
    if not cfg.m2_breakout_mode:
        if _m2_structure_fail(df, today, cfg, reasons):
            return {"signal": False, "reasons": reasons,
                    "entry_price": close, "stop_loss": None, "take_profit": None}

    if a is None:
        return _no_entry("ATR 缺失", close, None, None)

    # 不追高：突破模式下跳过（突破本身就是创新高，chase_max 会误杀信号）
    if not cfg.m2_breakout_mode:
        if pd.notna(today["ma_short"]) and today["ma_short"] > 0:
            chase = float(close / float(today["ma_short"]) - 1.0)
            if chase > cfg.chase_max:
                return _no_entry(
                    f"追高 X: close 相对 MA{cfg.ma_short} 偏离 {chase*100:.1f}% > {cfg.chase_max*100:.0f}%",
                    close, None, None,
                )

    # 价格位置过滤（L6 防追高）：拒绝价格在近 N 日区间高位入场
    # entry_price_position_max < 1.0 时启用；默认 1.0 = 不过滤
    if cfg.entry_price_position_max < 1.0:
        lb = max(2, int(cfg.entry_price_position_lookback))
        if len(df) >= lb:
            tail = df.iloc[-lb:]
            lo = float(pd.to_numeric(tail["low"], errors="coerce").min())
            hi = float(pd.to_numeric(tail["high"], errors="coerce").max())
            if hi > lo:
                pos = (close - lo) / (hi - lo)
                if pos > cfg.entry_price_position_max:
                    return _no_entry(
                        f"价格位置 X: pos={pos:.2f} > {cfg.entry_price_position_max:.2f} "
                        f"(近{lb}日区间 [{lo:.2f}, {hi:.2f}])",
                        close, None, None,
                    )
                reasons.append(f"价格位置 OK: pos={pos:.2f} <= {cfg.entry_price_position_max:.2f}")

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
    partial_exit_done: bool = False,
    runner_active: bool = False,
    regime_above_ma: Optional[bool] = None,
) -> dict:
    """与 exit_signal 同, 但接收已 enrich 的 df.

    partial_exit_done (main): 已完成 partial_exit_enabled 路径的部分卖出（不再重复）。
    runner_active (worktree HK): tp_runner_enabled 路径已 promote 为 runner（跳过 TP 与 RSI overbought）。
    promote 返回字典含 promote_runner=True / new_stop 时，调用方应锁 stop 并置 pos.runner_active=True，不卖。
    regime_above_ma (L9-A): 调用方算好的"基准指数 > MA(partial_exit_regime_ma_days)" 结果。
        仅在 cfg.partial_exit_regime_filter=True 时被消费——True 时 TP 命中改走全平（吃趋势），
        而不进入 partial_exit。None / cfg.partial_exit_regime_filter=False 时退化为原 partial 行为。
    """
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
            # 优先级 1：partial_exit_enabled (main) — 卖一部分，剩余切宽 trail
            # L9-A: 若启用 regime filter 且当前 regime 在 MA 上方（牛市），跳过 partial 走全平 TP 吃趋势
            _partial_skipped_by_regime = (
                cfg.partial_exit_enabled
                and cfg.partial_exit_regime_filter
                and regime_above_ma is True
            )
            if cfg.partial_exit_enabled and not partial_exit_done and not _partial_skipped_by_regime:
                wide_mult = cfg.atr_stop_mult * cfg.partial_exit_trail_mult
                new_stop_wide = close - wide_mult * a
                rs = (
                    f"take_profit_partial: close={close:.2f} >= target={target:.2f} "
                    f"(出场{cfg.partial_exit_pct*100:.0f}%，剩余切换{wide_mult:.1f}×ATR trailing)"
                )
                return {
                    "signal": True, "reason": rs, "exit_price": close,
                    "exit_layer": exit_layer_from_reason(rs),
                    "partial": True,
                    "partial_exit_pct": cfg.partial_exit_pct,
                    "new_stop_wide": new_stop_wide,
                    "new_trail_mult": wide_mult,
                }
            # 优先级 2：tp_runner_enabled (worktree HK) — 不卖，锁 stop 标 runner
            if cfg.tp_runner_enabled:
                if not runner_active:
                    lock_stop = target - cfg.tp_runner_lock_atr_mult * a
                    if trailing_stop_price is not None:
                        lock_stop = max(lock_stop, trailing_stop_price)
                    return {
                        "signal": False,
                        "promote_runner": True,
                        "new_stop": float(lock_stop),
                        "reason": f"promote_runner: close={close:.2f} >= target={target:.2f}",
                        "exit_price": close,
                        "exit_layer": "",
                    }
                # runner_active 后 TP 永久解除（trail / break_ma / time_stop 兜底）
            else:
                # 默认：全平 TP
                rs = f"take_profit: close={close:.2f} >= target={target:.2f}"
                return {"signal": True, "reason": rs, "exit_price": close, "exit_layer": exit_layer_from_reason(rs)}
    r = today["rsi"]
    # runner 模式下跳过 overbought 出场：trail / break_ma 已是 runner 的兜底，RSI 不再强制砍
    if not runner_active and pd.notna(r) and r >= cfg.rsi_overbought:
        # 若 runner 已配置 + 已有浮盈 + ATR 可用：RSI 超买改为 promote（强动量股不砍，锁利后让其奔跑）
        if cfg.tp_runner_enabled and a is not None and close > entry_price:
            lock_stop = close - cfg.tp_runner_lock_atr_mult * a
            if trailing_stop_price is not None:
                lock_stop = max(lock_stop, trailing_stop_price)
            return {
                "signal": False,
                "promote_runner": True,
                "new_stop": float(lock_stop),
                "reason": f"promote_runner_rsi: RSI={r:.1f} >= {cfg.rsi_overbought}, lock@{close:.2f}",
                "exit_price": close,
                "exit_layer": "",
            }
        rs = f"overbought: RSI={r:.1f} >= {cfg.rsi_overbought}"
        return {"signal": True, "reason": rs, "exit_price": close, "exit_layer": exit_layer_from_reason(rs)}
    if hold_days >= cfg.max_hold_days:
        rs = f"time_stop: 持有 {hold_days} 天 >= {cfg.max_hold_days}"
        return {"signal": True, "reason": rs, "exit_price": close, "exit_layer": exit_layer_from_reason(rs)}
    return {"signal": False, "reason": "持有", "exit_price": close, "exit_layer": ""}


def trailing_stop_from_enriched(
    enriched: pd.DataFrame, entry_price: float,
    prev_stop: Optional[float] = None, cfg: Optional[TimingConfig] = None,
    trail_mult_override: Optional[float] = None,
) -> float:
    """trail_mult_override：partial_exit 或 runner 模式后传入扩展倍数，让剩余/继续仓位有不同呼吸空间。"""
    cfg = cfg or TimingConfig()
    mult = float(trail_mult_override) if (trail_mult_override is not None and trail_mult_override > 0) else cfg.atr_stop_mult
    today = enriched.iloc[-1]
    a = float(today["atr"]) if pd.notna(today["atr"]) else 0.0
    candidate = float(today["close"]) - mult * a
    base = prev_stop if prev_stop is not None else (entry_price - mult * a)
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
    vol_thr = _effective_vol_breakout_mult(cfg, regime_ctx)
    if vol_mult < vol_thr:
        reasons.append(f"量能 X: 量比={vol_mult:.2f} < {vol_thr:.2f}")
        return {"signal": False, "reasons": reasons,
                "entry_price": close, "stop_loss": None, "take_profit": None}
    reasons.append(f"量能 OK: 量比={vol_mult:.2f} (阈={vol_thr:.2f})")

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
    partial_exit_done: bool = False,
    runner_active: bool = False,
) -> dict:
    """非 enriched 版 wrapper — enrich 后直接委托给 exit_signal_from_enriched。"""
    cfg = cfg or TimingConfig()
    df = enrich(price_df, cfg)
    return exit_signal_from_enriched(
        df, entry_price, entry_date, trailing_stop_price, cfg,
        partial_exit_done=partial_exit_done, runner_active=runner_active,
    )


# ---------- Trailing stop ----------

def trailing_stop(
    price_df: pd.DataFrame,
    entry_price: float,
    prev_stop: Optional[float] = None,
    cfg: Optional[TimingConfig] = None,
    trail_mult_override: Optional[float] = None,
) -> float:
    """当前应设的浮动止损 = max(prev_stop, close - ATR * mult). 只上调, 不下调.
    partial_exit / runner 模式下传入 trail_mult_override 覆盖 cfg.atr_stop_mult。"""
    cfg = cfg or TimingConfig()
    df = enrich(price_df, cfg)
    return trailing_stop_from_enriched(df, entry_price, prev_stop, cfg, trail_mult_override=trail_mult_override)


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
