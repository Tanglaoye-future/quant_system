"""
持仓动态风控: 每日盘后跑一次, 对所有未平仓 trade 评估并产生 HOLD/EXIT 建议.

流程:
  1. 取所有 open trades
  2. 对每只:
     - 拉最新日线
     - timing.trailing_stop 计算新止损 (只上调)
     - timing.exit_signal 判断是否要卖
     - 写一条 snapshot (price + risk_flag)
     - 若 trailing stop 上调, 同步 trade.stop_loss_price
  3. 组合层面: 总市值 / 总成本 / 总浮盈 / 单只最大权重 / EXIT 笔数 / 最差浮亏

行业集中度 / VaR / Beta 暂不实现 -- 当前持仓数少 (1-10 只),
等持仓上规模或催化剂模块到位后再补.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from quant_system.strategies.equity_factor.data.loader import DataLoader
from quant_system.strategies.equity_factor.journal.journal import Journal
from quant_system.strategies.equity_factor.timing.exit_taxonomy import exit_layer_from_reason
from quant_system.strategies.equity_factor.timing.signals import (
    TimingConfig,
    enrich,
    exit_signal,
    trailing_stop,
)


@dataclass
class PositionRisk:
    trade_id: int
    symbol: str
    market: str
    entry_date: str
    entry_price: float
    entry_size: int
    current_date: str
    current_price: float
    pnl_pct: float
    pnl_amount: float
    hold_days: int
    prev_stop: Optional[float]
    new_stop: float
    action: str       # HOLD / EXIT
    reason: str
    exit_layer: str = ""
    # safety margin 视图：当前价相对触发线的剩余空间（HOLD 时给操盘人"还有多远到止损/MA60"）
    ma_long: Optional[float] = None
    dist_to_stop_pct: Optional[float] = None       # (close - new_stop) / close；None=无止损
    dist_to_ma_long_pct: Optional[float] = None    # (close - MA60) / close；None=MA60 数据不足
    # 止盈目标：entry + atr_target_mult × ATR (默认 4×ATR)，与 exit_signal 的 take_profit 路径同公式
    take_profit: Optional[float] = None
    dist_to_target_pct: Optional[float] = None     # (take_profit - close) / close；None=ATR 数据不足


@dataclass
class PortfolioRiskConfig:
    """组合层风控阈值（仅 alert，不自动平仓）—— 任一字段为 None 即禁用该项。

    顶层 enabled=False 时整个评估跳过，PortfolioRisk.alerts 永远是空 list；
    个股层 RiskMonitor.daily_check 的 EXIT/HOLD 决策完全不受本 config 影响。
    """
    enabled: bool = False
    max_single_weight_pct: Optional[float] = None      # max_single_weight > X
    unrealized_pnl_floor_pct: Optional[float] = None   # unrealized_pnl_pct < X (X 为负值)
    exit_signal_ratio_max: Optional[float] = None      # n_at_risk / n_positions > X
    # PR2: 真历史 peak drawdown（数据源 portfolio_history 表，PR1 落地）
    portfolio_drawdown_pct: Optional[float] = None     # drawdown_from_peak_pct < X (X 为负值)
    drawdown_lookback_days: int = 60                   # peak 计算窗口（默认 60 个交易日）


@dataclass
class PortfolioRisk:
    n_positions: int
    cost_basis: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    max_single_weight: float       # 单只最大市值权重
    n_at_risk: int                 # 触发 EXIT 的笔数
    worst_drawdown_pct: float      # 单只最差浮亏（保留 v1 字段语义不变）
    alerts: list[str] = None       # PortfolioRiskConfig 触发的告警文案列表（未配置时为空）
    # PR2 新增：组合层真历史 peak DD（持仓市值 proxy，账户层 cash 未跟踪）
    peak_market_value: Optional[float] = None        # 历史窗口内峰值 market_value
    drawdown_from_peak_pct: Optional[float] = None   # (current_mv - peak_mv) / peak_mv ≤ 0

    def __post_init__(self):
        if self.alerts is None:
            self.alerts = []


def compute_peak_drawdown(
    history_market_values: Optional[list[float]],
    current_market_value: float,
) -> tuple[Optional[float], Optional[float]]:
    """返回 (peak_mv, drawdown_from_peak_pct)。

    Equity proxy: 系统不跟踪 cash 余额（manual execution），peak DD 用 market_value
    作为持仓 equity proxy。已知失真：开/平仓阶跃会污染 series；纯价格波动数学正确。
    Spec: docs/specs/position_v2_harness.md §3.4.

    空 history 返 (None, None)。当前值若 > 历史峰则成为新峰，dd = 0。
    """
    if not history_market_values:
        return None, None
    peak = max(history_market_values)
    peak = max(peak, current_market_value)
    if peak <= 0:
        return None, None
    dd = (current_market_value - peak) / peak     # ≤ 0
    return peak, dd


class RiskMonitor:
    def __init__(
        self,
        loader: DataLoader,
        journal: Journal,
        timing_cfg: Optional[TimingConfig] = None,
        market: Optional[str] = None,
        strategy: Optional[str] = None,
        portfolio_risk_cfg: Optional[PortfolioRiskConfig] = None,
    ):
        self.loader = loader
        self.journal = journal
        self.cfg = timing_cfg or TimingConfig()
        # 限定本次 run 只评估自己 (market, strategy) 的持仓，避免串台 + 误自动平仓
        self.market = market
        self.strategy = strategy
        self.portfolio_risk_cfg = portfolio_risk_cfg or PortfolioRiskConfig()

    def daily_check(
        self, asof: Optional[str] = None, write_snapshots: bool = True
    ) -> tuple[list[PositionRisk], PortfolioRisk]:
        asof = asof or datetime.now().strftime("%Y-%m-%d")
        # 拉一段够 MA60 + RSI 热身的窗口
        start = "2024-01-01"

        positions: list[PositionRisk] = []
        for trade in self.journal.list_open(market=self.market, strategy=self.strategy):
            try:
                px = self.loader.get_daily(trade["market"], trade["symbol"], start, asof)
            except Exception:
                continue
            if len(px) < self.cfg.ma_long + 5:
                continue

            current_price = float(px["close"].iloc[-1])
            current_date = str(px["date"].iloc[-1])

            new_stop = trailing_stop(
                px, trade["entry_price"], trade["stop_loss_price"], self.cfg
            )
            ex = exit_signal(
                px,
                entry_price=trade["entry_price"],
                entry_date=trade["entry_date"],
                trailing_stop_price=new_stop,
                cfg=self.cfg,
            )

            hold_days = (
                datetime.fromisoformat(current_date)
                - datetime.fromisoformat(trade["entry_date"])
            ).days
            pnl_pct = current_price / trade["entry_price"] - 1.0
            pnl_amount = (current_price - trade["entry_price"]) * trade["entry_size"]
            action = "EXIT" if ex["signal"] else "HOLD"
            ex_layer = str(ex.get("exit_layer") or exit_layer_from_reason(str(ex.get("reason", ""))))

            if ex["signal"]:
                risk_flag = "exit"
                # 自动平仓结算
                exit_price_use = ex.get("exit_price", current_price)
                self.journal.close_trade(
                    trade["id"], current_date, exit_price_use,
                    str(ex.get("reason", "自动退出"))
                )
            elif pnl_pct < -0.05:
                risk_flag = "drawdown"
            else:
                risk_flag = "normal"

            if write_snapshots:
                self.journal.add_snapshot(
                    trade["id"], current_date, current_price,
                    risk_flag=risk_flag,
                    note=ex["reason"] if ex["signal"] else None,
                )
                prev = trade["stop_loss_price"] or 0.0
                if new_stop > prev:
                    self.journal.update_stop_loss(trade["id"], new_stop)

            # MA60 与 safety margin —— 仅展示用，不参与决策（决策仍在 exit_signal）
            ma_long_val: Optional[float] = None
            if len(px) >= self.cfg.ma_long:
                m = px["close"].tail(self.cfg.ma_long).mean()
                if m == m:  # not NaN
                    ma_long_val = float(m)
            dist_stop = (
                (current_price - new_stop) / current_price
                if current_price > 0 and new_stop and new_stop > 0
                else None
            )
            dist_ma = (
                (current_price - ma_long_val) / current_price
                if current_price > 0 and ma_long_val is not None
                else None
            )
            # 止盈目标：与 exit_signal 公式同步（entry + atr_target_mult × ATR）
            # 注：partial_exit / runner / regime filter 的状态当前不在 PG snapshots 里追踪，
            # monitor 沿用 base TP 路径展示；策略层走 partial 后的实际剩余目标不在本视图内
            atr_today: Optional[float] = None
            try:
                last_enriched = enrich(px, self.cfg).iloc[-1]
                a = last_enriched["atr"]
                if a == a:  # not NaN
                    atr_today = float(a)
            except Exception:
                pass
            take_profit_val: Optional[float] = (
                trade["entry_price"] + self.cfg.atr_target_mult * atr_today
                if atr_today is not None else None
            )
            dist_target = (
                (take_profit_val - current_price) / current_price
                if take_profit_val is not None and current_price > 0
                else None
            )

            positions.append(PositionRisk(
                trade_id=trade["id"], symbol=trade["symbol"], market=trade["market"],
                entry_date=trade["entry_date"], entry_price=trade["entry_price"],
                entry_size=trade["entry_size"],
                current_date=current_date, current_price=current_price,
                pnl_pct=pnl_pct, pnl_amount=pnl_amount, hold_days=hold_days,
                prev_stop=trade["stop_loss_price"], new_stop=new_stop,
                action=action, reason=ex["reason"], exit_layer=ex_layer,
                ma_long=ma_long_val,
                dist_to_stop_pct=dist_stop,
                dist_to_ma_long_pct=dist_ma,
                take_profit=take_profit_val,
                dist_to_target_pct=dist_target,
            ))

        # PR2: 查 portfolio_history 近 N 天 market_value 序列；cfg.enabled=false 时跳过
        history_mvs = self._fetch_history_market_values(asof)
        port = self._aggregate(positions, self.portfolio_risk_cfg, history_market_values=history_mvs)
        return positions, port

    def _fetch_history_market_values(self, asof: str) -> Optional[list[float]]:
        """读 portfolio_history 近 drawdown_lookback_days 天的 market_value。

        失败/未启用 → 返 None（_aggregate 会跳过 peak DD 计算）。
        DB 不可达不抛错（与 maybe_upsert_portfolio_history 容错对称）。
        """
        cfg = self.portfolio_risk_cfg
        if cfg is None or not cfg.enabled:
            return None
        try:
            from quant_system.db.ingest import list_recent_portfolio_history_mvs
            return list_recent_portfolio_history_mvs(
                strategy_name=self.strategy or "",
                market=self.market or "",
                asof=asof,
                lookback_days=cfg.drawdown_lookback_days,
            )
        except Exception:
            return None

    @staticmethod
    def _aggregate(
        positions: list[PositionRisk],
        portfolio_risk_cfg: Optional[PortfolioRiskConfig] = None,
        history_market_values: Optional[list[float]] = None,
    ) -> PortfolioRisk:
        """聚合个股层 PositionRisk → PortfolioRisk。

        history_market_values: PR2 新增。如非 None，调用 compute_peak_drawdown 算
        peak / drawdown_from_peak_pct 并按 cfg.portfolio_drawdown_pct 判 alert。
        为 None 时（如未启 enabled 或 DB 不可达）peak/dd 字段保持 None。
        """
        if not positions:
            return PortfolioRisk(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0)
        cost = sum(p.entry_price * p.entry_size for p in positions)
        mvs = [p.current_price * p.entry_size for p in positions]
        mv = sum(mvs)
        port = PortfolioRisk(
            n_positions=len(positions),
            cost_basis=cost,
            market_value=mv,
            unrealized_pnl=mv - cost,
            unrealized_pnl_pct=(mv / cost - 1.0) if cost else 0.0,
            max_single_weight=(max(mvs) / mv) if mv > 0 else 0.0,
            n_at_risk=sum(1 for p in positions if p.action == "EXIT"),
            worst_drawdown_pct=min(p.pnl_pct for p in positions),
        )
        # PR2: peak DD 计算（cfg.enabled 才查 history；否则 history_market_values 调用方传 None）
        if history_market_values is not None:
            peak, dd = compute_peak_drawdown(history_market_values, mv)
            port.peak_market_value = peak
            port.drawdown_from_peak_pct = dd
        # 组合层 alerts —— 仅 alert，不自动平仓（个股层 EXIT 决策已在 daily_check 中独立完成）
        if portfolio_risk_cfg and portfolio_risk_cfg.enabled:
            thr = portfolio_risk_cfg
            if (
                thr.max_single_weight_pct is not None
                and port.max_single_weight > thr.max_single_weight_pct
            ):
                port.alerts.append(
                    f"单只权重 {port.max_single_weight*100:.1f}% > 上限 "
                    f"{thr.max_single_weight_pct*100:.1f}%"
                )
            if (
                thr.unrealized_pnl_floor_pct is not None
                and port.unrealized_pnl_pct < thr.unrealized_pnl_floor_pct
            ):
                port.alerts.append(
                    f"组合浮盈 {port.unrealized_pnl_pct*100:+.2f}% < 下限 "
                    f"{thr.unrealized_pnl_floor_pct*100:+.2f}%"
                )
            if (
                thr.exit_signal_ratio_max is not None
                and port.n_positions > 0
                and (port.n_at_risk / port.n_positions) > thr.exit_signal_ratio_max
            ):
                ratio = port.n_at_risk / port.n_positions
                port.alerts.append(
                    f"EXIT 信号占比 {ratio*100:.0f}% ({port.n_at_risk}/{port.n_positions}) "
                    f"> 上限 {thr.exit_signal_ratio_max*100:.0f}%"
                )
            # PR2: 真历史 peak DD 阈值告警
            if (
                thr.portfolio_drawdown_pct is not None
                and port.drawdown_from_peak_pct is not None
                and port.drawdown_from_peak_pct < thr.portfolio_drawdown_pct
            ):
                port.alerts.append(
                    f"组合层回撤 {port.drawdown_from_peak_pct*100:+.2f}% < 阈值 "
                    f"{thr.portfolio_drawdown_pct*100:+.2f}% "
                    f"(peak {port.peak_market_value:,.0f})"
                )
        return port
