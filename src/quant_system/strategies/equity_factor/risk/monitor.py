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


@dataclass
class PortfolioRisk:
    n_positions: int
    cost_basis: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    max_single_weight: float       # 单只最大市值权重
    n_at_risk: int                 # 触发 EXIT 的笔数
    worst_drawdown_pct: float      # 单只最差浮亏


class RiskMonitor:
    def __init__(
        self,
        loader: DataLoader,
        journal: Journal,
        timing_cfg: Optional[TimingConfig] = None,
    ):
        self.loader = loader
        self.journal = journal
        self.cfg = timing_cfg or TimingConfig()

    def daily_check(
        self, asof: Optional[str] = None, write_snapshots: bool = True
    ) -> tuple[list[PositionRisk], PortfolioRisk]:
        asof = asof or datetime.now().strftime("%Y-%m-%d")
        # 拉一段够 MA60 + RSI 热身的窗口
        start = "2024-01-01"

        positions: list[PositionRisk] = []
        for trade in self.journal.list_open():
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

            positions.append(PositionRisk(
                trade_id=trade["id"], symbol=trade["symbol"], market=trade["market"],
                entry_date=trade["entry_date"], entry_price=trade["entry_price"],
                entry_size=trade["entry_size"],
                current_date=current_date, current_price=current_price,
                pnl_pct=pnl_pct, pnl_amount=pnl_amount, hold_days=hold_days,
                prev_stop=trade["stop_loss_price"], new_stop=new_stop,
                action=action, reason=ex["reason"], exit_layer=ex_layer,
            ))

        port = self._aggregate(positions)
        return positions, port

    @staticmethod
    def _aggregate(positions: list[PositionRisk]) -> PortfolioRisk:
        if not positions:
            return PortfolioRisk(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0)
        cost = sum(p.entry_price * p.entry_size for p in positions)
        mvs = [p.current_price * p.entry_size for p in positions]
        mv = sum(mvs)
        return PortfolioRisk(
            n_positions=len(positions),
            cost_basis=cost,
            market_value=mv,
            unrealized_pnl=mv - cost,
            unrealized_pnl_pct=(mv / cost - 1.0) if cost else 0.0,
            max_single_weight=(max(mvs) / mv) if mv > 0 else 0.0,
            n_at_risk=sum(1 for p in positions if p.action == "EXIT"),
            worst_drawdown_pct=min(p.pnl_pct for p in positions),
        )
