"""盘中实时风控核心 —— 纯函数，便于单测 mock 网络/DB。

数据流：
  scripts/intraday/intraday_risk_check.py:
    1. journal.list_open() → open_trades
    2. fetch_realtime_prices(codes) → {code: current_price}
    3. fetch_ma_long_a_share(codes, asof) → {code: ma60}
    4. 拼 PositionSnapshot + PortfolioSnapshot 喂 evaluate_alerts
    5. AlertEvent list → 按 (asof_date, strategy_name, symbol, alert_type)
       去重（DB alerts_sent unique index 兜底）→ Telegram.send
    6. 写 alerts_sent 表（delivered + error）

7 阈值 + 1 候选股突破（spec §6 + PR1/PR2/PR3 扩展）：
- stop_loss_proximity: 0 ≤ dist_to_stop_pct < proximity_to_stop_loss_pct
- take_profit_proximity: 0 ≤ dist_to_target_pct < proximity_to_take_profit_pct
- break_stop_loss: current_price < stop_loss        (PR1 新增, critical)
- break_ma60:     current_price < ma_long           (PR1 新增, critical)
- zhuang_distribution_warning: 庄股 day_change ≥ 4% + 量比 ≥ 2 (PR3 新增, warning)
- portfolio_unrealized_floor: unrealized_pnl_pct < portfolio_unrealized_floor_pct
- portfolio_peak_drawdown: drawdown_from_peak_pct < portfolio_drawdown_pct
- daily_screen_breakout: 候选股 current_price > T 日 high × (1+margin) +
                          量比 ≥ vol_ratio_min (PR2 新增, warning, 入场提示)

break_* 与 *_proximity 物理互斥（一旦穿越，proximity 的 dist 转负，不再触发 proximity）。
zhuang_distribution_warning 仅对 strategy in cfg.zhuang_strategies 的持仓评估;
独立于 break_/proximity, 可叠加（同股一天最多 4 个 alert: break_stop + break_ma60 +
zhuang_distribution + take_profit_proximity）。
daily_screen_breakout 用 BreakoutCandidateQuote + BreakoutConfig 走独立纯函数
evaluate_breakout_alerts，与持仓告警 evaluate_alerts 解耦（输入/输出分离）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Optional


@dataclass
class PositionSnapshot:
    """喂给 evaluate_alerts 的最小持仓形态。

    与 RiskMonitor.PositionRisk 字段子集重合，但不依赖 RiskMonitor 模块（intraday
    不走 daily_check）；从 journal_trades + realtime price 直接构造。
    """
    strategy_name: str
    symbol: str
    market: str
    entry_price: float
    current_price: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    ma_long: Optional[float] = None      # MA60 from T-1 daily closes (PR1); None=数据不足
    volume_ratio: Optional[float] = None  # spot_em '量比' (PR3); None=缺失
    day_change_pct: Optional[float] = None  # spot_em '涨跌幅' / 100 (PR3); None=缺失
    vwap_today: Optional[float] = None    # spot_em 5min 累计 VWAP (T 信号用); None=缺失


@dataclass
class PortfolioSnapshot:
    """组合层快照 —— 直接从最近 portfolio_history 行 + 当前 mv 计算。

    drawdown_from_peak_pct 由调用方算好（intraday_risk_check.py 调
    compute_peak_drawdown），core 不再 query DB（保持纯函数）。
    """
    strategy_name: str
    unrealized_pnl_pct: float
    drawdown_from_peak_pct: Optional[float] = None


@dataclass
class IntradayConfig:
    enabled: bool = False
    poll_interval_minutes: int = 5
    proximity_to_stop_loss_pct: float = 0.005
    proximity_to_take_profit_pct: float = 0.005
    portfolio_unrealized_floor_pct: float = -0.05
    portfolio_drawdown_pct: float = -0.07
    strategies: list[str] = field(default_factory=list)  # 空 list = 全部
    # PR3: zhuang_distribution_warning 阈值
    zhuang_change_pct_min: float = 0.04
    zhuang_vol_ratio_min: float = 2.0
    zhuang_strategies: list[str] = field(default_factory=lambda: ["zhuang"])
    zhuang_distribution_enabled: bool = False
    # 交易时段（A 股缺省；HK / US 后续可扩 per-market）
    trading_start: time = time(9, 30)
    trading_lunch_start: time = time(11, 30)
    trading_lunch_end: time = time(13, 0)
    trading_end: time = time(15, 0)

    @classmethod
    def from_yaml_dict(cls, raw: dict, zhuang_raw: Optional[dict] = None) -> "IntradayConfig":
        """从 config/intraday.yaml 的 intraday_alerts 节构造.
        PR3: zhuang_distribution 节 通过 zhuang_raw 单独传入 (与 intraday_alerts 并列)."""
        triggers = (raw.get("triggers") or {})
        tw = (raw.get("trading_window") or {}).get("a_share") or {}
        zh = zhuang_raw or {}

        def _parse_time(s: str, fallback: time) -> time:
            try:
                hh, mm = s.split(":")
                return time(int(hh), int(mm))
            except Exception:
                return fallback

        return cls(
            enabled=bool(raw.get("enabled", False)),
            poll_interval_minutes=int(raw.get("poll_interval_minutes", 5)),
            proximity_to_stop_loss_pct=float(triggers.get("proximity_to_stop_loss_pct", 0.005)),
            proximity_to_take_profit_pct=float(triggers.get("proximity_to_take_profit_pct", 0.005)),
            portfolio_unrealized_floor_pct=float(triggers.get("portfolio_unrealized_floor_pct", -0.05)),
            portfolio_drawdown_pct=float(triggers.get("portfolio_drawdown_pct", -0.07)),
            strategies=list(triggers.get("strategies") or []),
            zhuang_distribution_enabled=bool(zh.get("enabled", False)),
            zhuang_change_pct_min=float(zh.get("change_pct_min", 0.04)),
            zhuang_vol_ratio_min=float(zh.get("vol_ratio_min", 2.0)),
            zhuang_strategies=list(zh.get("strategies") or ["zhuang"]),
            trading_start=_parse_time(tw.get("start", "09:30"), time(9, 30)),
            trading_lunch_start=_parse_time(tw.get("lunch_start", "11:30"), time(11, 30)),
            trading_lunch_end=_parse_time(tw.get("lunch_end", "13:00"), time(13, 0)),
            trading_end=_parse_time(tw.get("end", "15:00"), time(15, 0)),
        )


@dataclass
class AlertEvent:
    """评估出的告警事件 —— 主脚本据此拼 Telegram 消息 + 写 alerts_sent。"""
    strategy_name: str
    symbol: Optional[str]   # 组合层 = None
    alert_type: str         # spec §6 4 种之一
    severity: str           # "warning" / "critical"
    payload: dict           # 数字 + 消息正文等
    message: str            # 推送正文（Telegram HTML safe）


def is_in_trading_window(now: datetime, cfg: IntradayConfig) -> bool:
    """是否在 A 股交易时段（9:30-11:30 / 13:00-15:00）。
    周六周日永远 False；节假日由 akshare 调用层（拉不到数据自然 noop）兜底。
    """
    if now.weekday() >= 5:
        return False
    t = now.time()
    if cfg.trading_start <= t < cfg.trading_lunch_start:
        return True
    if cfg.trading_lunch_end <= t < cfg.trading_end:
        return True
    return False


def evaluate_alerts(
    positions: list[PositionSnapshot],
    portfolios: list[PortfolioSnapshot],
    cfg: IntradayConfig,
) -> list[AlertEvent]:
    """纯评估 → AlertEvent list。不做去重 / DB / 推送（主脚本职责）。"""
    events: list[AlertEvent] = []
    if not cfg.enabled:
        return events

    # 个股层
    for p in positions:
        if cfg.strategies and p.strategy_name not in cfg.strategies:
            continue
        if p.current_price <= 0:
            continue
        # PR1 — break_stop_loss: 已跌破止损（critical, 优先级高于 proximity）
        if p.stop_loss and p.stop_loss > 0 and p.current_price < p.stop_loss:
            breach_pct = (p.stop_loss - p.current_price) / p.stop_loss
            events.append(AlertEvent(
                strategy_name=p.strategy_name,
                symbol=p.symbol,
                alert_type="break_stop_loss",
                severity="critical",
                payload={
                    "current_price": p.current_price,
                    "stop_loss": p.stop_loss,
                    "breach_pct": breach_pct,
                },
                message=(
                    f"🛑 <b>{p.symbol}</b> 已跌破止损 "
                    f"{breach_pct*100:.2f}%\n"
                    f"现价 {p.current_price:.2f} &lt; 止损 {p.stop_loss:.2f} "
                    f"({p.strategy_name}/{p.market})"
                ),
            ))
        # PR1 — break_ma60: 已跌破 MA60（critical 长期趋势支撑失守）
        if p.ma_long and p.ma_long > 0 and p.current_price < p.ma_long:
            breach_ma_pct = (p.ma_long - p.current_price) / p.ma_long
            events.append(AlertEvent(
                strategy_name=p.strategy_name,
                symbol=p.symbol,
                alert_type="break_ma60",
                severity="critical",
                payload={
                    "current_price": p.current_price,
                    "ma_long": p.ma_long,
                    "breach_pct": breach_ma_pct,
                },
                message=(
                    f"📉 <b>{p.symbol}</b> 跌破 MA60 "
                    f"{breach_ma_pct*100:.2f}%\n"
                    f"现价 {p.current_price:.2f} &lt; MA60 {p.ma_long:.2f} "
                    f"({p.strategy_name}/{p.market})"
                ),
            ))
        if p.stop_loss and p.stop_loss > 0:
            dist_to_stop_pct = (p.current_price - p.stop_loss) / p.current_price
            if 0 <= dist_to_stop_pct < cfg.proximity_to_stop_loss_pct:
                events.append(AlertEvent(
                    strategy_name=p.strategy_name,
                    symbol=p.symbol,
                    alert_type="stop_loss_proximity",
                    severity="critical",
                    payload={
                        "current_price": p.current_price,
                        "stop_loss": p.stop_loss,
                        "dist_to_stop_pct": dist_to_stop_pct,
                        "threshold_pct": cfg.proximity_to_stop_loss_pct,
                    },
                    message=(
                        f"⚠ <b>{p.symbol}</b> 贴近止损 "
                        f"{dist_to_stop_pct*100:.2f}% &lt; {cfg.proximity_to_stop_loss_pct*100:.2f}%\n"
                        f"现价 {p.current_price:.2f} / 止损 {p.stop_loss:.2f} "
                        f"({p.strategy_name}/{p.market})"
                    ),
                ))
        if p.take_profit and p.take_profit > 0:
            dist_to_target_pct = (p.take_profit - p.current_price) / p.current_price
            if 0 <= dist_to_target_pct < cfg.proximity_to_take_profit_pct:
                events.append(AlertEvent(
                    strategy_name=p.strategy_name,
                    symbol=p.symbol,
                    alert_type="take_profit_proximity",
                    severity="warning",
                    payload={
                        "current_price": p.current_price,
                        "take_profit": p.take_profit,
                        "dist_to_target_pct": dist_to_target_pct,
                        "threshold_pct": cfg.proximity_to_take_profit_pct,
                    },
                    message=(
                        f"🎯 <b>{p.symbol}</b> 接近止盈 "
                        f"距 {dist_to_target_pct*100:.2f}% &lt; {cfg.proximity_to_take_profit_pct*100:.2f}%\n"
                        f"现价 {p.current_price:.2f} / 止盈 {p.take_profit:.2f} "
                        f"({p.strategy_name}/{p.market})"
                    ),
                ))
        # PR3 — zhuang_distribution_warning: 庄股盘中派发预警
        if (
            cfg.zhuang_distribution_enabled
            and p.strategy_name in cfg.zhuang_strategies
            and p.day_change_pct is not None
            and p.day_change_pct >= cfg.zhuang_change_pct_min
        ):
            # 量比缺失 (None) → 保守降级仍发 alert; 有值则必须达标
            vol_ok = (p.volume_ratio is None) or (p.volume_ratio >= cfg.zhuang_vol_ratio_min)
            if vol_ok:
                vr_str = f"{p.volume_ratio:.2f}" if p.volume_ratio is not None else "N/A"
                events.append(AlertEvent(
                    strategy_name=p.strategy_name,
                    symbol=p.symbol,
                    alert_type="zhuang_distribution_warning",
                    severity="warning",
                    payload={
                        "current_price": p.current_price,
                        "day_change_pct": p.day_change_pct,
                        "volume_ratio": p.volume_ratio,
                        "change_pct_min": cfg.zhuang_change_pct_min,
                        "vol_ratio_min": cfg.zhuang_vol_ratio_min,
                    },
                    message=(
                        f"🚨 [庄股派发预警] <b>{p.symbol}</b> "
                        f"今日 {p.day_change_pct*100:+.2f}% / 量比 {vr_str}\n"
                        f"现价 {p.current_price:.2f} ({p.strategy_name}/{p.market})\n"
                        f"⚠ 可能进入派发期, 考虑减仓 (非自动平仓)"
                    ),
                ))

    # 组合层
    for port in portfolios:
        if cfg.strategies and port.strategy_name not in cfg.strategies:
            continue
        if port.unrealized_pnl_pct < cfg.portfolio_unrealized_floor_pct:
            events.append(AlertEvent(
                strategy_name=port.strategy_name,
                symbol=None,
                alert_type="portfolio_unrealized_floor",
                severity="critical",
                payload={
                    "unrealized_pnl_pct": port.unrealized_pnl_pct,
                    "threshold_pct": cfg.portfolio_unrealized_floor_pct,
                },
                message=(
                    f"🔻 <b>{port.strategy_name}</b> 组合浮亏 "
                    f"{port.unrealized_pnl_pct*100:+.2f}% &lt; "
                    f"{cfg.portfolio_unrealized_floor_pct*100:+.2f}%"
                ),
            ))
        if (
            port.drawdown_from_peak_pct is not None
            and port.drawdown_from_peak_pct < cfg.portfolio_drawdown_pct
        ):
            events.append(AlertEvent(
                strategy_name=port.strategy_name,
                symbol=None,
                alert_type="portfolio_peak_drawdown",
                severity="critical",
                payload={
                    "drawdown_from_peak_pct": port.drawdown_from_peak_pct,
                    "threshold_pct": cfg.portfolio_drawdown_pct,
                },
                message=(
                    f"📉 <b>{port.strategy_name}</b> 组合 peak DD "
                    f"{port.drawdown_from_peak_pct*100:+.2f}% &lt; "
                    f"{cfg.portfolio_drawdown_pct*100:+.2f}%"
                ),
            ))

    return events


# ── PR2: daily_screen_breakout (候选股盘中突破入场提示) ───────────────────

@dataclass
class BreakoutConfig:
    """daily_screen_breakout 触发参数 (config/intraday.yaml breakout 节)."""
    enabled: bool = False
    breakout_margin: float = 0.005     # current_price > ref_high × (1 + margin)
    vol_ratio_min: float = 1.2          # 量比下限; None / 缺失字段降级 skip 该 filter
    watchlist_max_age_days: int = 5
    strategies: list[str] = field(default_factory=lambda: ["equity_factor"])

    @classmethod
    def from_yaml_dict(cls, raw: dict) -> "BreakoutConfig":
        return cls(
            enabled=bool(raw.get("enabled", False)),
            breakout_margin=float(raw.get("breakout_margin", 0.005)),
            vol_ratio_min=float(raw.get("vol_ratio_min", 1.2)),
            watchlist_max_age_days=int(raw.get("watchlist_max_age_days", 5)),
            strategies=list(raw.get("strategies") or ["equity_factor"]),
        )


@dataclass
class BreakoutCandidateQuote:
    """评估 daily_screen_breakout 时单只候选股的盘中实时输入.

    daily watchlist 给 reference_high / 建议 entry/sl/tp; spot_em 给 current_price /
    volume_ratio. 主脚本合并后喂 evaluate_breakout_alerts.
    """
    symbol: str
    name: str
    strategy_name: str
    market: str
    current_price: float
    reference_high: float           # T 日 high
    volume_ratio: Optional[float]   # akshare spot_em '量比'; None=缺失
    entry_price_suggested: float
    stop_loss_suggested: Optional[float] = None
    take_profit_suggested: Optional[float] = None
    factor_score: float = 0.0


def evaluate_breakout_alerts(
    quotes: list[BreakoutCandidateQuote],
    cfg: BreakoutConfig,
) -> list[AlertEvent]:
    """纯评估 daily_screen_breakout. 已在主脚本过滤 持仓 / stale watchlist.

    触发条件全部满足:
      1. current > reference_high × (1 + breakout_margin)
      2. volume_ratio is None OR volume_ratio ≥ vol_ratio_min
    """
    events: list[AlertEvent] = []
    if not cfg.enabled:
        return events
    for q in quotes:
        if cfg.strategies and q.strategy_name not in cfg.strategies:
            continue
        if q.current_price <= 0 or q.reference_high <= 0:
            continue
        threshold_price = q.reference_high * (1.0 + cfg.breakout_margin)
        if q.current_price <= threshold_price:
            continue
        # 量比降级: None 仍发 alert (akshare 字段缺失保守不挡)
        if q.volume_ratio is not None and q.volume_ratio < cfg.vol_ratio_min:
            continue
        breakout_pct = (q.current_price - q.reference_high) / q.reference_high
        vol_str = f"{q.volume_ratio:.2f}" if q.volume_ratio is not None else "N/A"
        sl_str = f"{q.stop_loss_suggested:.2f}" if q.stop_loss_suggested else "N/A"
        tp_str = f"{q.take_profit_suggested:.2f}" if q.take_profit_suggested else "N/A"
        events.append(AlertEvent(
            strategy_name=q.strategy_name,
            symbol=q.symbol,
            alert_type="daily_screen_breakout",
            severity="warning",
            payload={
                "current_price": q.current_price,
                "reference_high": q.reference_high,
                "breakout_pct": breakout_pct,
                "volume_ratio": q.volume_ratio,
                "entry_price_suggested": q.entry_price_suggested,
                "stop_loss_suggested": q.stop_loss_suggested,
                "take_profit_suggested": q.take_profit_suggested,
                "factor_score": q.factor_score,
                "threshold_pct": cfg.breakout_margin,
                "vol_ratio_min": cfg.vol_ratio_min,
            },
            message=(
                f"📈 [候选] <b>{q.symbol}</b>({q.name}) 突破 T 日 high "
                f"{breakout_pct*100:+.2f}% / 量比 {vol_str}\n"
                f"现价 {q.current_price:.2f} &gt; ref_high {q.reference_high:.2f}; "
                f"建议入场 {q.entry_price_suggested:.2f} / 止损 {sl_str} / 止盈 {tp_str}\n"
                f"⚠ 可考虑次日开盘建仓 (非自动下单)"
            ),
        ))
    return events


# ── 持仓中日内做 T 信号 (spec docs/specs/intraday_t_execution_a_share.md) ───────
#
# advisory only - 不下单. evaluate_t_signals 是纯函数, 与 evaluate_alerts 平行.
# 3 层综合: 价格网格(base) + VWAP 偏离(boost) + 量价 anti-distribution(抑制/加强).
# 6 不变量(spec §14) 在代码层强制:
#   1. 当日净持仓量永不变 (BUY 必须当日已有 SELL)
#   2. qty_ratio ∈ [0.2, 0.7]
#   3. 不改 stop_loss / take_profit
#   4. break_stop_loss 触发后 T 全面禁用
#   5. advisory only (函数只返事件, 不写库不下单)
#   6. strategy 白名单 - zhuang / mean_reversion / HK / US 直接 skip


@dataclass
class TSignalConfig:
    enabled: bool = False
    strategies: list[str] = field(default_factory=lambda: ["equity_factor"])
    markets: list[str] = field(default_factory=lambda: ["a_share"])
    # 交易时段
    trading_start: time = time(9, 30)
    trading_lunch_start: time = time(11, 30)
    trading_lunch_end: time = time(13, 0)
    trading_end: time = time(15, 0)
    skip_first_minutes: int = 5
    # 价格网格 base
    sell_unrealized_pct_min: float = 0.05
    buy_unrealized_pct_min: float = 0.02
    no_t_unrealized_pct_max: float = -0.03
    qty_ratio_base: float = 0.5
    # VWAP 偏离 boost
    vwap_enabled: bool = True
    vwap_sell_premium_pct: float = 0.02
    vwap_buy_discount_pct: float = 0.015
    vwap_qty_ratio_boost: float = 0.2
    # 量价 anti-distribution
    vol_price_enabled: bool = True
    vol_price_sell_suppress_change_pct: float = 0.04
    vol_price_sell_suppress_vol_ratio: float = 2.0
    vol_price_sell_suppress_factor: float = 0.7
    vol_price_buy_boost_change_pct: float = -0.02
    vol_price_buy_boost_vol_ratio: float = 0.7
    vol_price_buy_boost_factor: float = 1.3
    # qty clamp
    qty_ratio_min: float = 0.2
    qty_ratio_max: float = 0.7
    # 频率上限
    max_sells_per_day: int = 1
    max_buys_per_day: int = 1

    @classmethod
    def from_yaml_dict(cls, raw: dict) -> "TSignalConfig":
        """从 config/intraday.yaml::t_signals 节构造."""
        tw = raw.get("trading_window") or {}
        grid = raw.get("grid") or {}
        vwap = raw.get("vwap") or {}
        vp = raw.get("vol_price") or {}
        clamp = raw.get("qty_ratio_clamp") or {}
        freq = raw.get("frequency") or {}

        def _t(s: str, fb: time) -> time:
            try:
                hh, mm = s.split(":")
                return time(int(hh), int(mm))
            except Exception:
                return fb

        return cls(
            enabled=bool(raw.get("enabled", False)),
            strategies=list(raw.get("strategies") or ["equity_factor"]),
            markets=list(raw.get("markets") or ["a_share"]),
            trading_start=_t(tw.get("start", "09:30"), time(9, 30)),
            trading_lunch_start=_t(tw.get("lunch_start", "11:30"), time(11, 30)),
            trading_lunch_end=_t(tw.get("lunch_end", "13:00"), time(13, 0)),
            trading_end=_t(tw.get("end", "15:00"), time(15, 0)),
            skip_first_minutes=int(tw.get("skip_first_minutes", 5)),
            sell_unrealized_pct_min=float(grid.get("sell_unrealized_pct_min", 0.05)),
            buy_unrealized_pct_min=float(grid.get("buy_unrealized_pct_min", 0.02)),
            no_t_unrealized_pct_max=float(grid.get("no_t_unrealized_pct_max", -0.03)),
            qty_ratio_base=float(grid.get("qty_ratio_base", 0.5)),
            vwap_enabled=bool(vwap.get("enabled", True)),
            vwap_sell_premium_pct=float(vwap.get("sell_premium_pct", 0.02)),
            vwap_buy_discount_pct=float(vwap.get("buy_discount_pct", 0.015)),
            vwap_qty_ratio_boost=float(vwap.get("qty_ratio_boost", 0.2)),
            vol_price_enabled=bool(vp.get("enabled", True)),
            vol_price_sell_suppress_change_pct=float(vp.get("sell_suppress_change_pct", 0.04)),
            vol_price_sell_suppress_vol_ratio=float(vp.get("sell_suppress_vol_ratio", 2.0)),
            vol_price_sell_suppress_factor=float(vp.get("sell_suppress_factor", 0.7)),
            vol_price_buy_boost_change_pct=float(vp.get("buy_boost_change_pct", -0.02)),
            vol_price_buy_boost_vol_ratio=float(vp.get("buy_boost_vol_ratio", 0.7)),
            vol_price_buy_boost_factor=float(vp.get("buy_boost_factor", 1.3)),
            qty_ratio_min=float(clamp.get("min", 0.2)),
            qty_ratio_max=float(clamp.get("max", 0.7)),
            max_sells_per_day=int(freq.get("max_sells_per_day", 1)),
            max_buys_per_day=int(freq.get("max_buys_per_day", 1)),
        )


@dataclass
class TSignalEvent:
    asof: str                # "YYYY-MM-DD HH:MM"
    strategy_name: str
    symbol: str
    market: str
    side: str                # "SELL" | "BUY"
    suggested_price: float
    qty_ratio: float         # 最终 clamp 后 ∈ [qty_ratio_min, qty_ratio_max]
    base_qty_ratio: float    # debug
    reason: str              # 三段拼接
    confidence: str          # "high" / "medium" / "low"


def _is_in_t_window(asof: datetime, cfg: TSignalConfig) -> bool:
    """T 信号时段过滤. 周末永远 False; 跳开盘 skip_first_minutes 分钟; 跳午休."""
    if asof.weekday() >= 5:
        return False
    t = asof.time()
    asof_sec = t.hour * 3600 + t.minute * 60 + t.second
    start_sec = cfg.trading_start.hour * 3600 + cfg.trading_start.minute * 60
    start_with_skip = start_sec + cfg.skip_first_minutes * 60
    end_sec = cfg.trading_end.hour * 3600 + cfg.trading_end.minute * 60
    lunch_start_sec = cfg.trading_lunch_start.hour * 3600 + cfg.trading_lunch_start.minute * 60
    lunch_end_sec = cfg.trading_lunch_end.hour * 3600 + cfg.trading_lunch_end.minute * 60
    if asof_sec < start_with_skip or asof_sec >= end_sec:
        return False
    if lunch_start_sec <= asof_sec < lunch_end_sec:
        return False
    return True


def evaluate_t_signals(
    positions: list[PositionSnapshot],
    cfg: TSignalConfig,
    asof: datetime,
    sent_today: dict[tuple[str, str], list[str]],
) -> list[TSignalEvent]:
    """纯评估 → TSignalEvent list. 与 evaluate_alerts 平行, 不去重 / 不写库 / 不推送.

    sent_today: {(symbol, market): [alert_type, ...]} 当日已发 alert 类型;
      - dedup max_sells/buys_per_day
      - BUY 前置 SELL 检查
      - break_stop_loss 已触发 → 禁用 T
    """
    events: list[TSignalEvent] = []
    if not cfg.enabled:
        return events
    if not _is_in_t_window(asof, cfg):
        return events

    for p in positions:
        # §3.4 step 1 — 白名单 + 跳过非 a_share
        if p.strategy_name not in cfg.strategies:
            continue
        if p.market not in cfg.markets:
            continue
        if p.current_price <= 0 or p.entry_price <= 0:
            continue

        sent = sent_today.get((p.symbol, p.market), [])

        # 不变量 #4 — break_stop_loss 后禁用
        if "break_stop_loss" in sent:
            continue

        unrealized_pct = (p.current_price - p.entry_price) / p.entry_price

        # 浮亏区禁用 (no_t_unrealized_pct_max 是负数, 浮亏 <= 阈值 → skip)
        if unrealized_pct <= cfg.no_t_unrealized_pct_max:
            continue

        # §3.1 价格网格 — candidate side
        side: Optional[str] = None
        if unrealized_pct >= cfg.sell_unrealized_pct_min:
            side = "SELL"
        elif unrealized_pct >= cfg.buy_unrealized_pct_min:
            # 不变量 #1 — BUY 必须当日已有 SELL
            if "t_signal_sell" in sent:
                side = "BUY"
        if side is None:
            continue

        # §3.4 step 3 — 频率上限
        if side == "SELL" and sent.count("t_signal_sell") >= cfg.max_sells_per_day:
            continue
        if side == "BUY" and sent.count("t_signal_buy") >= cfg.max_buys_per_day:
            continue

        # qty 计算 + reason 拼接 + layer 计数 (confidence)
        qty_ratio = cfg.qty_ratio_base
        reason_parts = [f"grid: unrealized {unrealized_pct*100:+.1f}%"]
        layers_active = 1  # grid 总算 1

        # §3.2 VWAP 偏离
        if cfg.vwap_enabled and p.vwap_today is not None and p.vwap_today > 0:
            layers_active += 1
            deviation = (p.current_price - p.vwap_today) / p.vwap_today
            boosted = False
            if side == "SELL" and deviation >= cfg.vwap_sell_premium_pct:
                qty_ratio += cfg.vwap_qty_ratio_boost
                reason_parts.append(f"vwap: +{deviation*100:.1f}% premium")
                boosted = True
            elif side == "BUY" and deviation <= -cfg.vwap_buy_discount_pct:
                qty_ratio += cfg.vwap_qty_ratio_boost
                reason_parts.append(f"vwap: {deviation*100:.1f}% discount")
                boosted = True
            if not boosted:
                reason_parts.append(f"vwap: normal ({deviation*100:+.1f}%)")
        else:
            reason_parts.append("vwap: n/a")

        # §3.3 量价 anti-distribution
        if (cfg.vol_price_enabled
                and p.day_change_pct is not None
                and p.volume_ratio is not None):
            layers_active += 1
            adjusted = False
            if (side == "SELL"
                    and p.day_change_pct >= cfg.vol_price_sell_suppress_change_pct
                    and p.volume_ratio >= cfg.vol_price_sell_suppress_vol_ratio):
                qty_ratio *= cfg.vol_price_sell_suppress_factor
                reason_parts.append(
                    f"volprice: suppress (dchg {p.day_change_pct*100:+.1f}%, "
                    f"vr {p.volume_ratio:.1f})"
                )
                adjusted = True
            elif (side == "BUY"
                    and p.day_change_pct <= cfg.vol_price_buy_boost_change_pct
                    and p.volume_ratio <= cfg.vol_price_buy_boost_vol_ratio):
                qty_ratio *= cfg.vol_price_buy_boost_factor
                reason_parts.append(
                    f"volprice: boost (dchg {p.day_change_pct*100:+.1f}%, "
                    f"vr {p.volume_ratio:.1f})"
                )
                adjusted = True
            if not adjusted:
                reason_parts.append("volprice: normal")
        else:
            reason_parts.append("volprice: n/a")

        # 不变量 #2 — qty 必 ∈ [min, max]
        qty_ratio = max(cfg.qty_ratio_min, min(cfg.qty_ratio_max, qty_ratio))

        # confidence: 3 / 2 / 1 active layer
        if layers_active >= 3:
            confidence = "high"
        elif layers_active == 2:
            confidence = "medium"
        else:
            confidence = "low"

        events.append(TSignalEvent(
            asof=asof.strftime("%Y-%m-%d %H:%M"),
            strategy_name=p.strategy_name,
            symbol=p.symbol,
            market=p.market,
            side=side,
            suggested_price=p.current_price,
            qty_ratio=qty_ratio,
            base_qty_ratio=cfg.qty_ratio_base,
            reason=" | ".join(reason_parts),
            confidence=confidence,
        ))

    return events
