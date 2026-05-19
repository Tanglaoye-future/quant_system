"""
M2 — 市况门（指数层）：仅影响「是否允许开新仓」，不改变单票 enrich 语义。

M3 — 市况观测（供单票 RSI 入场带显式联动）：
- `TimingRegimeContext` 仅含截至 asof 的指数截面指标，由 `build_timing_regime_context` 计算。
- `build_timing_regime_context` 内惰性 `import signals.atr`，避免与 `signals` 顶层循环依赖。

设计约束：
- 只使用 asof 当日及以前的指数日线（与回测一致，避免未来函数）。
- 失败时返回可读 reason，供日志 / 后续诊断扩展。
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quant_system.strategies.equity_factor.data.loader import DataLoader


@dataclass(frozen=True)
class TimingRegimeContext:
    """
    截至 asof 的指数侧上下文（M3 RSI 带联动）。
    index_close_vs_ma: (收盘/SMA(ma_days)-1)，在均线之上为正。
    index_atr_pct: 指数当日 ATR/收盘。
    index_atr_pct_rel: ATR%/近端 median(ATR%)-1，>0 表示相对近期偏波动。
    southbound_strength: (net_buy_today / MA(net_buy, 20) - 1)，>0 表示南向今日活跃于近 20 日均值。
    字段为 None 表示样本不足，单票侧跳过对应 M3 调节。
    """

    index_close_vs_ma: float | None
    index_atr_pct: float | None
    index_atr_pct_rel: float | None
    southbound_strength: float | None = None
    # Plan B (L7-B): 强势 regime gate + 相对强度过滤所需
    index_close_vs_ma200: float | None = None  # (close/MA200 - 1)，>0 = 大牛
    index_drawdown_from_20d_high: float | None = None  # (close/max_close_20d - 1)，≤0
    index_return_20d: float | None = None  # 20 日累计收益



class MarketRegimeGate:
    """基准指数收盘是否在长期均线之上（默认 MA60）。"""

    def __init__(self, loader: DataLoader, benchmark_symbol: str, ma_days: int = 60):
        self.loader = loader
        self.benchmark_symbol = benchmark_symbol
        self.ma_days = int(ma_days)

    def allows_long_entries(self, asof_str: str) -> tuple[bool, str]:
        df = self.loader.get_index_daily(self.benchmark_symbol)
        if df is None or df.empty:
            return False, "市况X: 无指数日线"
        sub = df[df["date"] <= asof_str].copy()
        if len(sub) < self.ma_days + 1:
            return False, f"市况X: 指数样本不足 (需要>={self.ma_days + 1} 根, 实际 {len(sub)})"
        sub["close"] = pd.to_numeric(sub["close"], errors="coerce")
        sub = sub.dropna(subset=["close"])
        if len(sub) < self.ma_days + 1:
            return False, "市况X: 指数 close 有效样本不足"
        ma = sub["close"].rolling(self.ma_days, min_periods=self.ma_days).mean()
        last_close = float(sub["close"].iloc[-1])
        last_ma = float(ma.iloc[-1])
        if pd.isna(last_ma):
            return False, "市况X: MA 未就绪"
        if last_close > last_ma:
            return True, f"市况OK: 收盘 {last_close:.2f} > MA{self.ma_days} {last_ma:.2f}"
        return False, f"市况X: 收盘 {last_close:.2f} <= MA{self.ma_days} {last_ma:.2f}"


def build_timing_regime_context(
    loader: DataLoader,
    benchmark_symbol: str,
    asof_str: str,
    ma_days: int,
    *,
    atr_period: int = 14,
    atr_pct_median_window: int = 20,
    southbound_enabled: bool = False,
    southbound_ma_window: int = 20,
    marginal_flow_market: str | None = None,   # "hk_share" / "a_share"，None 时禁用
) -> TimingRegimeContext:
    """
    为 M3 单票 RSI 入场带提供指数侧上下文（仅用 date <= asof 的指数日线）。
    ma_days 建议与 `m2_regime_ma_days` 一致，使「市况门」与「RSI 带联动」同一标尺。
    """
    from quant_system.strategies.equity_factor.timing.signals import atr as index_atr_series

    df = loader.get_index_daily(benchmark_symbol)
    if df is None or df.empty:
        return TimingRegimeContext(None, None, None)
    sub = df[df["date"] <= asof_str].copy()
    # 至少需要 200 + 余量来计算 MA200（Plan B 强势 regime gate 用）
    need = max(int(ma_days) + 2, int(atr_period) + int(atr_pct_median_window) + 2, 205)
    if len(sub) < need:
        return TimingRegimeContext(None, None, None)
    for col in ("open", "high", "low", "close", "volume"):
        if col in sub.columns:
            sub[col] = pd.to_numeric(sub[col], errors="coerce")
    sub = sub.dropna(subset=["close"])
    if len(sub) < need:
        return TimingRegimeContext(None, None, None)

    ma = sub["close"].rolling(int(ma_days), min_periods=int(ma_days)).mean()
    last_close = float(sub["close"].iloc[-1])
    last_ma = float(ma.iloc[-1])
    if pd.isna(last_ma) or last_ma <= 0:
        vs_ma: float | None = None
    else:
        vs_ma = last_close / last_ma - 1.0

    sub = sub.copy()
    sub["atr"] = index_atr_series(sub, int(atr_period))
    c = pd.to_numeric(sub["close"], errors="coerce")
    atr_pct_s = sub["atr"] / c.replace(0, float("nan"))
    last_atr_pct = float(atr_pct_s.iloc[-1]) if pd.notna(atr_pct_s.iloc[-1]) else None
    rel: float | None = None
    if last_atr_pct is not None and atr_pct_median_window >= 2:
        med = atr_pct_s.rolling(int(atr_pct_median_window), min_periods=int(atr_pct_median_window)).median()
        m0 = float(med.iloc[-1])
        if m0 and m0 > 0 and not pd.isna(m0):
            rel = last_atr_pct / m0 - 1.0

    # Plan B 字段: MA200 / 20d drawdown / 20d return
    vs_ma200: float | None = None
    if len(sub) >= 201:
        ma200 = sub["close"].rolling(200, min_periods=200).mean()
        last_ma200 = float(ma200.iloc[-1])
        if not pd.isna(last_ma200) and last_ma200 > 0:
            vs_ma200 = last_close / last_ma200 - 1.0
    dd_20d: float | None = None
    ret_20d: float | None = None
    if len(sub) >= 21:
        last20_high = float(sub["close"].iloc[-21:-1].max())
        if last20_high > 0:
            dd_20d = last_close / last20_high - 1.0
        c_20 = float(sub["close"].iloc[-21])
        if c_20 > 0:
            ret_20d = last_close / c_20 - 1.0

    # 边际资金强度信号（按市场分发：HK→南向，A 股→北向）
    sb_strength: float | None = None
    if southbound_enabled and marginal_flow_market:
        try:
            sb_df = loader.get_marginal_flow(marginal_flow_market)
            if sb_df is not None and not sb_df.empty:
                sb_sub = sb_df[sb_df["date"] <= asof_str].copy()
                w = max(2, int(southbound_ma_window))
                if len(sb_sub) >= w + 1:
                    nb = pd.to_numeric(sb_sub["net_buy"], errors="coerce")
                    ma = nb.rolling(w, min_periods=w).mean()
                    last_nb = float(nb.iloc[-1])
                    last_ma = float(ma.iloc[-1])
                    if pd.notna(last_ma) and abs(last_ma) > 1e-9:
                        # 标准化偏差：(today - MA20) / |MA20|，>0 = 强于近期均值
                        sb_strength = (last_nb - last_ma) / abs(last_ma)
        except Exception:
            sb_strength = None

    return TimingRegimeContext(
        index_close_vs_ma=vs_ma,
        index_atr_pct=last_atr_pct,
        index_atr_pct_rel=rel,
        southbound_strength=sb_strength,
        index_close_vs_ma200=vs_ma200,
        index_drawdown_from_20d_high=dd_20d,
        index_return_20d=ret_20d,
    )
