"""
策略接口 + 第一个具体实现 (bottomup + timing).

新策略只需实现 Strategy Protocol 的 screen() + evaluate() 两个方法,
就能直接进 backtest.py 跑回测.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Protocol

import pandas as pd

from quant_system.market import MarketContext
from quant_system.strategies.equity_factor.bottomup.factors import FactorWeights, score_universe
from quant_system.strategies.equity_factor.bottomup.portfolio import M4Config
from quant_system.strategies.equity_factor.data.loader import DataLoader
from quant_system.strategies.equity_factor.timing.exit_taxonomy import exit_layer_from_reason
from quant_system.strategies.equity_factor.timing.regime import MarketRegimeGate, build_timing_regime_context
from quant_system.strategies.equity_factor.timing.signals import (
    TimingConfig, enrich,
    entry_signal_from_enriched, exit_signal_from_enriched, trailing_stop_from_enriched,
)
from quant_system.strategies.equity_factor.universe.filter import UniverseFilter, UniverseFilterConfig


def _market_ctx_or_default(market: str, market_ctx: Optional[MarketContext]) -> MarketContext:
    """向下兼容辅助：旧调用未传 market_ctx 时按市场名给默认能力（与 Phase 2a 之前硬编码等价）."""
    if market_ctx is not None:
        return market_ctx
    return MarketContext(
        name=market,
        universe_filter="a_share" if market == "a_share" else None,
        industry_concentration=(market == "a_share"),
    )


@dataclass
class BuySignal:
    symbol: str
    market: str
    score: float = 0.0
    entry_price: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reasons: dict[str, str] = field(default_factory=dict)


@dataclass
class ExitSignal:
    action: str                    # "HOLD" / "EXIT" / "PARTIAL_EXIT"
    new_stop: Optional[float] = None
    reason: str = ""
    exit_layer: str = ""           # M5：与 exit_taxonomy / exit_events 对齐
    partial_exit_pct: float = 0.0  # PARTIAL_EXIT 时出场比例（如 0.5）
    new_trail_mult: Optional[float] = None  # PARTIAL_EXIT 后剩余仓位使用的 trailing stop ATR 倍数


@dataclass
class Position:
    symbol: str
    market: str
    entry_date: date
    entry_price: float
    size: int
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    partial_exit_done: bool = False          # main: 已完成过一次部分出场 (PARTIAL_EXIT 后)
    atr_stop_mult_override: Optional[float] = None  # main: 部分出场后使用的宽松 ATR 倍数
    runner_active: bool = False              # worktree HK L1: TP 命中后 promote 为 runner（无卖出）


class Strategy(Protocol):
    name: str
    def screen(self, asof: date) -> list[BuySignal]: ...
    def evaluate(self, position: Position, asof: date) -> ExitSignal: ...


# ---------- 多策略叠加：mean-reversion 策略（与 momentum 正交）----------

@dataclass
class MeanReversionConfig:
    rsi_period: int = 14
    rsi_entry_max: float = 30.0       # 入场上限：RSI < 30（深度超卖）
    rsi_exit_min: float = 55.0        # 出场下限：RSI > 55（回归到均值之上）
    ma_long: int = 200                # 长期趋势门：close > MA200
    max_hold_days: int = 10           # 时间止损：10 个交易日
    stop_loss_pct: float = 0.05       # 价格止损：跌破入场价 5%
    vol_ma_period: int = 20
    vol_mult: float = 1.0             # 量能确认（量 >= MA20）


class MeanReversionStrategy:
    """超卖反弹策略 — 与 momentum 策略互补。
    入场：RSI<30 + 收盘>MA200（长期趋势正常的深度回调）
    出场：RSI>55（mean-reverted）/ 持有>10 日 / 5% 止损 / MA200 跌破
    """
    name = "mean_reversion"

    def __init__(
        self,
        loader: DataLoader,
        market: str,
        universe_codes: list[str],
        cfg: Optional[MeanReversionConfig] = None,
        history_start: str = "2018-01-01",
        market_ctx: Optional[MarketContext] = None,
    ):
        self.loader = loader
        self.market = market                                    # 仍保留供 loader.get_daily 数据源 dispatch
        self.market_ctx = _market_ctx_or_default(market, market_ctx)
        self.universe_codes = universe_codes
        self.cfg = cfg or MeanReversionConfig()
        self.history_start = history_start
        self._enriched: dict[str, pd.DataFrame] = {}
        self._universe_filter = UniverseFilter(loader, UniverseFilterConfig())
        self._filtered_cache: dict[str, list[str]] = {}
        # m4_cfg dummy for backtester compat
        self.m4_cfg: M4Config = M4Config(m4_enabled=False)

    def _filtered_universe_codes(self, asof_str: str) -> list[str]:
        if asof_str in self._filtered_cache:
            return self._filtered_cache[asof_str]
        if self.market_ctx.universe_filter != "a_share":
            self._filtered_cache[asof_str] = self.universe_codes
            return self.universe_codes
        uni_df = pd.DataFrame({"code": self.universe_codes})
        uni_df["name"] = ""
        filtered_df, _ = self._universe_filter.filter_a_share(uni_df, asof_str)
        codes = filtered_df["code"].astype(str).tolist()
        self._filtered_cache[asof_str] = codes
        return codes

    def _ensure_enriched(self, codes: list[str]) -> None:
        # 复用 momentum 用的 TimingConfig 来 enrich（共享 RSI / ATR / MA 计算）
        tmp_tcfg = TimingConfig(
            rsi_period=self.cfg.rsi_period,
            ma_long=self.cfg.ma_long,
            vol_ma_period=self.cfg.vol_ma_period,
        )
        for code in codes:
            if code in self._enriched:
                continue
            try:
                px = self.loader.get_daily(self.market, code, self.history_start, "2030-01-01")
            except Exception:
                continue
            if len(px) < self.cfg.ma_long + 5:
                continue
            self._enriched[code] = enrich(px, tmp_tcfg)

    def screen(self, asof: date) -> list[BuySignal]:
        asof_str = asof.strftime("%Y-%m-%d") if isinstance(asof, date) else asof
        codes = self._filtered_universe_codes(asof_str)
        self._ensure_enriched(codes)
        hits: list[BuySignal] = []
        for code in codes:
            enr = self._enriched.get(code)
            if enr is None:
                continue
            sub = enr[enr["date"] <= asof_str]
            if len(sub) < self.cfg.ma_long + 1:
                continue
            today = sub.iloc[-1]
            close = float(today["close"])
            rsi_v = today["rsi"]
            ma_l = today["ma_long"]
            vol = today["volume"]
            vol_ma = today["vol_ma"]
            if pd.isna(rsi_v) or pd.isna(ma_l) or pd.isna(vol_ma) or vol_ma <= 0:
                continue
            if float(rsi_v) >= self.cfg.rsi_entry_max:
                continue
            if close <= float(ma_l):
                continue
            if float(vol) < float(vol_ma) * self.cfg.vol_mult:
                continue
            # 用 RSI 越低越优先（更深超卖）作排序信号
            hits.append(BuySignal(
                symbol=code, market=self.market,
                score=-float(rsi_v),                       # 负数：RSI 越小 score 越大
                entry_price=close,
                stop_loss=close * (1.0 - self.cfg.stop_loss_pct),
                take_profit=None,
                reasons={"timing": f"oversold-bounce: RSI={float(rsi_v):.1f}, close>{float(ma_l):.2f}"},
            ))
        hits.sort(key=lambda s: -s.score)
        return hits

    def evaluate(self, position: Position, asof: date) -> ExitSignal:
        asof_str = asof.strftime("%Y-%m-%d") if isinstance(asof, date) else asof
        enr = self._enriched.get(position.symbol)
        if enr is None:
            self._ensure_enriched([position.symbol])
            enr = self._enriched.get(position.symbol)
        if enr is None:
            return ExitSignal(action="HOLD", reason="not in cache", exit_layer="")
        sub = enr[enr["date"] <= asof_str]
        if len(sub) < self.cfg.ma_long + 1:
            return ExitSignal(action="HOLD", reason="insufficient history", exit_layer="")
        today = sub.iloc[-1]
        close = float(today["close"])
        rsi_v = today["rsi"]
        ma_l = today["ma_long"]
        hold_days = (asof - position.entry_date).days if isinstance(asof, date) else 0

        # 价格止损
        if position.stop_loss is not None and close <= position.stop_loss:
            rs = f"stop_loss_5pct: close={close:.2f} <= stop={position.stop_loss:.2f}"
            return ExitSignal(action="EXIT", reason=rs, exit_layer=exit_layer_from_reason("trailing_stop:"))
        # MA200 跌破（趋势破坏）
        if pd.notna(ma_l) and close < float(ma_l):
            rs = f"break_ma{self.cfg.ma_long}: close={close:.2f} < MA={float(ma_l):.2f}"
            return ExitSignal(action="EXIT", reason=rs, exit_layer=exit_layer_from_reason("break_ma"))
        # RSI 回归（目标达成）
        if pd.notna(rsi_v) and float(rsi_v) >= self.cfg.rsi_exit_min:
            rs = f"rsi_revert: RSI={float(rsi_v):.1f} >= {self.cfg.rsi_exit_min}"
            return ExitSignal(action="EXIT", reason=rs, exit_layer=exit_layer_from_reason("overbought:"))
        # 时间止损
        if hold_days >= self.cfg.max_hold_days:
            rs = f"time_stop: 持有 {hold_days} 天 >= {self.cfg.max_hold_days}"
            return ExitSignal(action="EXIT", reason=rs, exit_layer=exit_layer_from_reason("time_stop"))
        return ExitSignal(action="HOLD", reason="持有", exit_layer="")


# ---------- A_mr-rebuild: swing-reversion 策略（dip+bounce 入场 + ATR target 出场）----------

@dataclass
class SwingReversionConfig:
    # 入场：dip + bounce 模式（不再要求今日 RSI < 30，等反弹起来再入场）
    rsi_period: int = 14
    rsi_dip_lookback: int = 5         # 过去 N 日 RSI 触底窗口
    rsi_dip_max: float = 32.0         # 窗口内 RSI 最低 ≤ 此（触底）
    rsi_bounce_min_today: float = 36.0  # 今日 RSI ≥ 此（已弹起）
    rsi_bounce_pts: float = 3.0       # 今日 RSI > 窗口最低 + N pts（确认 bounce）
    ma_long: int = 200                # close > MA200 长期趋势门
    vol_ma_period: int = 20
    vol_mult: float = 1.0             # 今日量 ≥ MA20

    # v2 入场新增：MA200 buffer + 斜率门
    ma_long_buffer_pct: float = 0.0       # close 必须 > MA200 × (1+buffer)，过滤瓶口反弹
    ma_long_slope_enabled: bool = False   # MA200 vs N 日前必须 > 0 (上升趋势)
    ma_long_slope_lookback: int = 20      # MA200 斜率回看天数

    # 出场
    atr_period: int = 14
    atr_stop_mult: float = 1.5        # 止损 = entry - 1.5×ATR
    atr_target_mult: float = 3.0      # take_profit = entry + 3.0×ATR
    rsi_exit_min: float = 70.0        # RSI ≥ 此出场（vs old MR 55，放走赢家）
    max_hold_days: int = 20           # vs old MR 10，给 mean-reversion 完整周期

    # v2 出场新增：break_ma200 grace period (连续 N 天 < MA 才砍)
    break_ma_grace_days: int = 0      # 0=立刻 (v1 行为); >=2=连续 N 天 close < MA 才出


class SwingReversionStrategy:
    """A 股 swing-reversion — 重写 MeanReversion 弱腿。

    设计动机（vs 旧 MeanReversion）：
      - 旧 RSI<30 实时入场抓刀，平均胜率 53% 信号噪音大
      - 改成"过去 N 日触底 + 今日反弹起来"等真反转确认
      - 出场：旧 RSI≥55 太早 + max_hold=10 砍断赢家 → 改 ATR target + RSI≥70 + 20d
    """
    name = "swing_reversion"

    def __init__(
        self,
        loader: DataLoader,
        market: str,
        universe_codes: list[str],
        cfg: Optional[SwingReversionConfig] = None,
        history_start: str = "2018-01-01",
        market_ctx: Optional[MarketContext] = None,
    ):
        self.loader = loader
        self.market = market
        self.market_ctx = _market_ctx_or_default(market, market_ctx)
        self.universe_codes = universe_codes
        self.cfg = cfg or SwingReversionConfig()
        self.history_start = history_start
        self._enriched: dict[str, pd.DataFrame] = {}
        self._universe_filter = UniverseFilter(loader, UniverseFilterConfig())
        self._filtered_cache: dict[str, list[str]] = {}
        self.m4_cfg: M4Config = M4Config(m4_enabled=False)

    def _filtered_universe_codes(self, asof_str: str) -> list[str]:
        if asof_str in self._filtered_cache:
            return self._filtered_cache[asof_str]
        if self.market_ctx.universe_filter != "a_share":
            self._filtered_cache[asof_str] = self.universe_codes
            return self.universe_codes
        uni_df = pd.DataFrame({"code": self.universe_codes})
        uni_df["name"] = ""
        filtered_df, _ = self._universe_filter.filter_a_share(uni_df, asof_str)
        codes = filtered_df["code"].astype(str).tolist()
        self._filtered_cache[asof_str] = codes
        return codes

    def _ensure_enriched(self, codes: list[str]) -> None:
        tmp_tcfg = TimingConfig(
            rsi_period=self.cfg.rsi_period,
            ma_long=self.cfg.ma_long,
            atr_period=self.cfg.atr_period,
            vol_ma_period=self.cfg.vol_ma_period,
        )
        for code in codes:
            if code in self._enriched:
                continue
            try:
                px = self.loader.get_daily(self.market, code, self.history_start, "2030-01-01")
            except Exception:
                continue
            if len(px) < self.cfg.ma_long + 5:
                continue
            self._enriched[code] = enrich(px, tmp_tcfg)

    def screen(self, asof: date) -> list[BuySignal]:
        asof_str = asof.strftime("%Y-%m-%d") if isinstance(asof, date) else asof
        codes = self._filtered_universe_codes(asof_str)
        self._ensure_enriched(codes)
        hits: list[BuySignal] = []
        for code in codes:
            enr = self._enriched.get(code)
            if enr is None:
                continue
            sub = enr[enr["date"] <= asof_str]
            min_history = max(self.cfg.ma_long, self.cfg.rsi_dip_lookback + self.cfg.rsi_period) + 1
            if len(sub) < min_history:
                continue
            today = sub.iloc[-1]
            close = float(today["close"])
            rsi_v = today["rsi"]
            ma_l = today["ma_long"]
            vol = today["volume"]
            vol_ma = today["vol_ma"]
            atr_v = today["atr"]
            if pd.isna(rsi_v) or pd.isna(ma_l) or pd.isna(vol_ma) or pd.isna(atr_v):
                continue
            if vol_ma <= 0 or atr_v <= 0:
                continue

            # 长期趋势门 (v2: 加 buffer，过滤瓶口反弹)
            ma_l_threshold = float(ma_l) * (1.0 + self.cfg.ma_long_buffer_pct)
            if close <= ma_l_threshold:
                continue
            # v2: MA200 斜率门 (要求 MA 上升才入场)
            if self.cfg.ma_long_slope_enabled:
                lb = int(self.cfg.ma_long_slope_lookback)
                if len(sub) > lb:
                    ma_past = sub.iloc[-1 - lb]["ma_long"]
                    if pd.isna(ma_past) or float(ma_l) <= float(ma_past):
                        continue
                else:
                    continue
            # 量能确认
            if float(vol) < float(vol_ma) * self.cfg.vol_mult:
                continue
            # 今日已反弹起来
            if float(rsi_v) < self.cfg.rsi_bounce_min_today:
                continue

            # dip + bounce：过去 N 日（不含今日）RSI 最低 ≤ dip_max，今日 > 窗口最低 + bounce_pts
            window = sub.iloc[-(self.cfg.rsi_dip_lookback + 1):-1]
            if len(window) < self.cfg.rsi_dip_lookback:
                continue
            window_rsi = pd.to_numeric(window["rsi"], errors="coerce").dropna()
            if len(window_rsi) < self.cfg.rsi_dip_lookback:
                continue
            dip_min = float(window_rsi.min())
            if dip_min > self.cfg.rsi_dip_max:
                continue
            if float(rsi_v) < dip_min + self.cfg.rsi_bounce_pts:
                continue

            atr_float = float(atr_v)
            stop = close - self.cfg.atr_stop_mult * atr_float
            target = close + self.cfg.atr_target_mult * atr_float
            # bounce 越强（dip 越深 + 弹幅越大）排序越优先
            bounce_strength = (float(rsi_v) - dip_min) + (self.cfg.rsi_dip_max - dip_min)
            hits.append(BuySignal(
                symbol=code, market=self.market,
                score=float(bounce_strength),
                entry_price=close,
                stop_loss=stop,
                take_profit=target,
                reasons={
                    "timing": f"swing-rev: dip={dip_min:.1f} bounce_today={float(rsi_v):.1f} "
                              f"stop={stop:.2f} target={target:.2f}",
                },
            ))
        hits.sort(key=lambda s: -s.score)
        return hits

    def evaluate(self, position: Position, asof: date) -> ExitSignal:
        asof_str = asof.strftime("%Y-%m-%d") if isinstance(asof, date) else asof
        enr = self._enriched.get(position.symbol)
        if enr is None:
            self._ensure_enriched([position.symbol])
            enr = self._enriched.get(position.symbol)
        if enr is None:
            return ExitSignal(action="HOLD", reason="not in cache", exit_layer="")
        sub = enr[enr["date"] <= asof_str]
        if len(sub) < self.cfg.ma_long + 1:
            return ExitSignal(action="HOLD", reason="insufficient history", exit_layer="")
        today = sub.iloc[-1]
        close = float(today["close"])
        rsi_v = today["rsi"]
        ma_l = today["ma_long"]
        hold_days = (asof - position.entry_date).days if isinstance(asof, date) else 0

        if position.stop_loss is not None and close <= position.stop_loss:
            rs = f"atr_stop: close={close:.2f} <= stop={position.stop_loss:.2f}"
            return ExitSignal(action="EXIT", reason=rs, exit_layer=exit_layer_from_reason("trailing_stop:"))
        if position.take_profit is not None and close >= position.take_profit:
            rs = f"atr_target: close={close:.2f} >= target={position.take_profit:.2f}"
            return ExitSignal(action="EXIT", reason=rs, exit_layer=exit_layer_from_reason("take_profit"))
        if pd.notna(ma_l) and close < float(ma_l):
            # v2: grace_days 要求连续 N 天 < MA 才出，避免单日抖动 churn
            grace = int(self.cfg.break_ma_grace_days)
            if grace <= 1:
                rs = f"break_ma{self.cfg.ma_long}: close={close:.2f} < MA={float(ma_l):.2f}"
                return ExitSignal(action="EXIT", reason=rs, exit_layer=exit_layer_from_reason("break_ma"))
            # 检查过去 grace-1 天 (含今日共 grace 天) 是否都 close < MA
            recent = sub.iloc[-grace:]
            if len(recent) >= grace:
                rec_close = pd.to_numeric(recent["close"], errors="coerce")
                rec_ma = pd.to_numeric(recent["ma_long"], errors="coerce")
                if (rec_close < rec_ma).all():
                    rs = (f"break_ma{self.cfg.ma_long}_grace{grace}: "
                          f"连续 {grace} 天 close < MA={float(ma_l):.2f}")
                    return ExitSignal(action="EXIT", reason=rs, exit_layer=exit_layer_from_reason("break_ma"))
            # 否则 HOLD，等满足 grace
        if pd.notna(rsi_v) and float(rsi_v) >= self.cfg.rsi_exit_min:
            rs = f"rsi_overbought: RSI={float(rsi_v):.1f} >= {self.cfg.rsi_exit_min}"
            return ExitSignal(action="EXIT", reason=rs, exit_layer=exit_layer_from_reason("overbought:"))
        if hold_days >= self.cfg.max_hold_days:
            rs = f"time_stop: 持有 {hold_days} 天 >= {self.cfg.max_hold_days}"
            return ExitSignal(action="EXIT", reason=rs, exit_layer=exit_layer_from_reason("time_stop"))
        return ExitSignal(action="HOLD", reason="持有", exit_layer="")


# ---------- 第一个具体实现 ----------

class BottomupTimingStrategy:
    """全市场扫 entry signal -> 因子排序. 与 daily_run 主流水线一致."""
    name = "bottomup_timing"

    def __init__(
        self,
        loader: DataLoader,
        market: str,
        universe_codes: list[str],
        timing_cfg: Optional[TimingConfig] = None,
        weights: Optional[FactorWeights] = None,
        history_start: str = "2018-01-01",
        regime_benchmark_symbol: Optional[str] = None,
        m4_cfg: Optional[M4Config] = None,
        market_ctx: Optional[MarketContext] = None,
        pure_pv: bool = False,
    ):
        self.loader = loader
        self.market = market                                    # 仍保留供 loader.get_daily 数据源 dispatch
        self.market_ctx = _market_ctx_or_default(market, market_ctx)
        self.universe_codes = universe_codes
        self.tcfg = timing_cfg or TimingConfig()
        self.weights = weights or FactorWeights()
        self.m4_cfg: M4Config = m4_cfg or M4Config()
        self._m4_prev_top: set[str] = set()
        self._pure_pv = pure_pv
        self.history_start = history_start
        self._regime_benchmark_symbol = regime_benchmark_symbol or "sh000300"
        self._regime_gate: MarketRegimeGate | None = None
        if self.tcfg.m2_regime_enabled:
            self._regime_gate = MarketRegimeGate(
                loader, self._regime_benchmark_symbol, self.tcfg.m2_regime_ma_days
            )
        # L9-A: regime-aware partial_exit 需要"基准 > MA(L9 ma_days)"判断；ma_days 与 m2 解耦
        # 仅 partial_exit_enabled + partial_exit_regime_filter 同开时使用
        self._partial_regime_gate: MarketRegimeGate | None = None
        if self.tcfg.partial_exit_enabled and self.tcfg.partial_exit_regime_filter:
            self._partial_regime_gate = MarketRegimeGate(
                loader, self._regime_benchmark_symbol,
                int(self.tcfg.partial_exit_regime_ma_days),
            )
        # enrich 缓存：按需构建（UniverseFilter 先缩小集合，再 enrich）
        self._enriched: dict[str, "object"] = {}
        # pure_pv 模式跳过 fundamentals gate（市值/ROE/负债率），仅留 liquidity / 价格 / 涨跌停 / 停牌
        self._universe_filter = UniverseFilter(
            loader, UniverseFilterConfig(skip_fundamentals=pure_pv)
        )
        self._filtered_cache: dict[str, list[str]] = {}   # asof_str -> codes

    def _filtered_universe_codes(self, asof_str: str) -> list[str]:
        if asof_str in self._filtered_cache:
            return self._filtered_cache[asof_str]
        # 当前只实现 A 股过滤；其他市场（universe_filter=none）跳过
        if self.market_ctx.universe_filter != "a_share":
            self._filtered_cache[asof_str] = self.universe_codes
            return self.universe_codes
        uni_df = pd.DataFrame({"code": self.universe_codes})
        uni_df["name"] = ""
        filtered_df, _stats = self._universe_filter.filter_a_share(uni_df, asof_str)
        codes = filtered_df["code"].astype(str).tolist()
        self._filtered_cache[asof_str] = codes
        return codes

    def _ensure_enriched(self, codes: list[str]) -> None:
        """对 codes 里尚未 enrich 的股票做 enrich 并写入缓存。"""
        for code in codes:
            if code in self._enriched:
                continue
            try:
                px = self.loader.get_daily(self.market, code, self.history_start, "2030-01-01")
            except Exception:
                continue
            if len(px) < self.tcfg.ma_long + 5:
                continue
            self._enriched[code] = enrich(px, self.tcfg)

    def screen(self, asof: date) -> list[BuySignal]:
        asof_str = asof.strftime("%Y-%m-%d") if isinstance(asof, date) else asof
        if self._regime_gate is not None:
            ok, _msg = self._regime_gate.allows_long_entries(asof_str)
            if not ok:
                return []
        codes = self._filtered_universe_codes(asof_str)
        self._ensure_enriched(codes)

        regime_ctx = None
        if (self.tcfg.m3_regime_rsi_band or self.tcfg.m3_reg_vol_tighten_hi
                or self.tcfg.m3_southbound_widen_enabled
                or self.tcfg.m3_southbound_gate_enabled):
            regime_ctx = build_timing_regime_context(
                self.loader,
                self._regime_benchmark_symbol,
                asof_str,
                self.tcfg.m2_regime_ma_days,
                atr_period=self.tcfg.atr_period,
                atr_pct_median_window=self.tcfg.m3_reg_index_atr_pct_median_window,
                southbound_enabled=self.tcfg.m3_southbound_widen_enabled,
                southbound_ma_window=self.tcfg.m3_southbound_ma_window,
                southbound_gate_lookback_days=(
                    self.tcfg.m3_southbound_gate_lookback_days
                    if self.tcfg.m3_southbound_gate_enabled else 0
                ),
                marginal_flow_market=self.market,
            )

        hits = []
        for code in codes:
            enr = self._enriched.get(code)
            if enr is None:
                continue
            sub = enr[enr["date"] <= asof_str]
            min_rows = self.tcfg.ma_long + 5
            if self.tcfg.m3_mtf_rsi_enabled:
                min_rows = max(min_rows, int(self.tcfg.m3_mtf_rsi_period) + 3)
            if len(sub) < min_rows:
                continue
            sig = entry_signal_from_enriched(sub, self.tcfg, regime_ctx=regime_ctx)
            if sig["signal"]:
                hits.append({"code": code, **sig})
        if not hits:
            return []

        # 因子排序 (score_universe 内部 fundamentals 已 cache, 秒回)
        hit_codes = [h["code"] for h in hits]
        m4_for_score = (
            self.m4_cfg
            if float(self.m4_cfg.m4_factor_dispersion_lambda) > 0
            else None
        )
        try:
            ranked = score_universe(
                self.loader, self.market, hit_codes, asof_str, self.weights,
                verbose=False, m4_cfg=m4_for_score, pure_pv=self._pure_pv,
            )
            for h in hits:
                h["_score"] = float(ranked.loc[h["code"], "score"]) if h["code"] in ranked.index else 0.0
        except Exception:
            for h in hits:
                h["_score"] = 0.0
        if float(self.m4_cfg.m4_turnover_penalty) > 0:
            pen = float(self.m4_cfg.m4_turnover_penalty)
            for h in hits:
                if h["code"] not in self._m4_prev_top:
                    h["_score"] -= pen
            hits.sort(key=lambda h: -h["_score"])
            ntop = max(1, int(self.m4_cfg.m4_turnover_top_n))
            self._m4_prev_top = {h["code"] for h in sorted(hits, key=lambda x: -x["_score"])[:ntop]}
        else:
            hits.sort(key=lambda h: -h["_score"])

        return [
            BuySignal(
                symbol=h["code"], market=self.market,
                score=h["_score"], entry_price=h["entry_price"],
                stop_loss=h["stop_loss"], take_profit=h["take_profit"],
                reasons={"timing": " | ".join(h["reasons"])},
            )
            for h in hits
        ]

    def evaluate(self, position: Position, asof: date) -> ExitSignal:
        asof_str = asof.strftime("%Y-%m-%d") if isinstance(asof, date) else asof
        enr = self._enriched.get(position.symbol)
        if enr is None:
            # 评估时若没缓存，补一次（避免因为 universe 过滤变化导致 hold 无法评估）
            self._ensure_enriched([position.symbol])
            enr = self._enriched.get(position.symbol)
        if enr is None:
            return ExitSignal(action="HOLD", reason="not in enriched cache", exit_layer="")
        sub = enr[enr["date"] <= asof_str]
        if len(sub) < self.tcfg.ma_long + 5:
            return ExitSignal(action="HOLD", reason="insufficient history", exit_layer="")

        # trail_mult 优先级：(1) PARTIAL_EXIT 后存在 pos.atr_stop_mult_override
        #                   (2) runner_active 且 cfg.atr_stop_mult_runner > 0
        #                   (3) cfg.atr_stop_mult 默认
        trail_override: Optional[float] = position.atr_stop_mult_override
        if trail_override is None and position.runner_active and self.tcfg.atr_stop_mult_runner > 0:
            trail_override = float(self.tcfg.atr_stop_mult_runner)
        new_stop = trailing_stop_from_enriched(
            sub, position.entry_price, position.stop_loss, self.tcfg,
            trail_mult_override=trail_override,
        )
        # L9-A: 若 partial_exit_regime_filter 启用，按 asof 计算"基准是否在 MA 上方"传给 exit
        regime_above_ma: Optional[bool] = None
        if self._partial_regime_gate is not None:
            try:
                ok_regime, _msg = self._partial_regime_gate.allows_long_entries(asof_str)
                regime_above_ma = bool(ok_regime)
            except Exception:
                regime_above_ma = None
        ex = exit_signal_from_enriched(
            sub,
            entry_price=position.entry_price,
            entry_date=position.entry_date.strftime("%Y-%m-%d"),
            trailing_stop_price=new_stop, cfg=self.tcfg,
            partial_exit_done=position.partial_exit_done,
            runner_active=position.runner_active,
            regime_above_ma=regime_above_ma,
        )
        if ex.get("promote_runner"):
            promote_stop = float(ex.get("new_stop") or new_stop)
            return ExitSignal(
                action="PROMOTE_RUNNER",
                new_stop=max(promote_stop, new_stop),
                reason=str(ex.get("reason", "promote_runner")),
                exit_layer="",
            )
        if ex["signal"]:
            layer = str(ex.get("exit_layer") or exit_layer_from_reason(str(ex.get("reason", ""))))
            if ex.get("partial"):
                return ExitSignal(
                    action="PARTIAL_EXIT",
                    new_stop=ex.get("new_stop_wide"),   # 宽松止损，由 backtest 写入 pos.stop_loss
                    reason=str(ex["reason"]),
                    exit_layer=layer,
                    partial_exit_pct=float(ex.get("partial_exit_pct", 0.5)),
                    new_trail_mult=ex.get("new_trail_mult"),
                )
            return ExitSignal(action="EXIT", new_stop=new_stop, reason=str(ex["reason"]), exit_layer=layer)
        if self.tcfg.m5_regime_exit_enabled:
            gate = self._regime_gate or MarketRegimeGate(
                self.loader, self._regime_benchmark_symbol, self.tcfg.m2_regime_ma_days
            )
            ok, msg = gate.allows_long_entries(asof_str)
            if not ok:
                rs = f"m5_regime_exit: {msg}"
                return ExitSignal(
                    action="EXIT",
                    new_stop=new_stop,
                    reason=rs,
                    exit_layer=exit_layer_from_reason(rs),
                )
        return ExitSignal(action="HOLD", new_stop=new_stop, reason="持有", exit_layer="")
