"""
回测引擎.

模拟 A 股真实交易:
  - 信号 D 日盘后产生, D+1 开盘价成交
  - A 股 T+1: 当日买入的不能当日卖
  - 单边滑点 (买高卖低)
  - 佣金双边收, 印花税仅卖出收
  - 单只仓位上限 (按初始资金的百分比)
  - 同时持仓上限
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import pandas as pd

from quant_system.strategies.equity_factor.bottomup.portfolio import m4_prioritize_signals
from quant_system.strategies.equity_factor.data.loader import DataLoader
from quant_system.strategies.equity_factor.timing.exit_taxonomy import exit_layer_from_reason
from quant_system.strategies.equity_factor.engine.strategy import BuySignal, ExitSignal, Position, Strategy


@dataclass
class ClosedTrade:
    symbol: str
    market: str
    entry_date: date
    entry_price: float
    size: int
    exit_date: date
    exit_price: float
    pnl: float
    pnl_pct: float
    hold_days: int
    exit_reason: str
    entry_reasons: dict = field(default_factory=dict)


@dataclass
class BacktestResult:
    equity_curve: pd.Series              # date -> portfolio value
    closed_trades: list[ClosedTrade]
    benchmark_curve: pd.Series           # date -> benchmark value (rebased to initial_capital)
    daily_positions: pd.DataFrame        # date, n_positions, market_value, cash


@dataclass
class BacktestDiagnostics:
    """M0 可追溯诊断：由 Backtester.run 写入 list[dict]，脚本层落盘 CSV/JSON。"""

    entry_rows: list[dict] = field(default_factory=list)
    exit_rows: list[dict] = field(default_factory=list)


class Backtester:
    def __init__(
        self,
        loader: DataLoader,
        initial_capital: float = 1_000_000.0,
        max_positions: int = 10,
        single_position_pct: float = 0.15,
        commission: float = 0.0003,        # 双边
        stamp_tax: float = 0.001,          # 卖出
        slippage: float = 0.001,           # 单边
        cash_buffer_pct: float = 0.05,     # 留 5% 现金不动
        # --- L3：基准做空对冲 overlay（仅在 regime ON 时做空基准，隔离 alpha）---
        benchmark_hedge_ratio: float = 0.0,        # 0=关闭；建议 0.3-0.5
        benchmark_hedge_ma_days: int = 200,         # regime 判别 MA 窗口
        benchmark_hedge_borrow_cost: float = 0.03,  # 年化借券成本
    ):
        self.loader = loader
        self.initial_capital = initial_capital
        self.max_positions = max_positions
        self.single_position_pct = single_position_pct
        self.commission = commission
        self.stamp_tax = stamp_tax
        self.slippage = slippage
        self.cash_buffer_pct = cash_buffer_pct
        self.benchmark_hedge_ratio = benchmark_hedge_ratio
        self.benchmark_hedge_ma_days = benchmark_hedge_ma_days
        self.benchmark_hedge_borrow_cost = benchmark_hedge_borrow_cost

    def run(
        self,
        strategy: Strategy,
        start: str,
        end: str,
        market: str = "a_share",
        benchmark_symbol: str = "sh000300",
        verbose: bool = True,
        diagnostics: Optional[BacktestDiagnostics] = None,
    ) -> BacktestResult:
        # 交易日历: 用基准指数的日期
        idx = self.loader.get_index_daily(benchmark_symbol)
        idx = idx[(idx["date"] >= start) & (idx["date"] <= end)].reset_index(drop=True)
        if len(idx) < 30:
            raise ValueError(f"基准 {benchmark_symbol} 在 [{start}, {end}] 数据不足")
        trading_days = idx["date"].tolist()
        bench_close = idx.set_index("date")["close"]
        bench_ma = bench_close.rolling(
            self.benchmark_hedge_ma_days, min_periods=self.benchmark_hedge_ma_days
        ).mean() if self.benchmark_hedge_ratio > 0 else None

        # 状态
        cash = self.initial_capital
        positions: dict[str, Position] = {}
        pending_buys: list[BuySignal] = []
        # pending_sells: (pos, reason, sell_fraction)
        # sell_fraction=1.0 表示全量出场，0<sell_fraction<1.0 表示部分出场
        pending_sells: list[tuple[Position, str, float]] = []
        closed: list[ClosedTrade] = []
        equity_history: list[tuple[str, float]] = []
        position_history: list[dict] = []
        # L3 hedge state
        hedge_short: Optional[dict] = None   # {entry_price, size, entry_date_str}
        hedge_trades: list[dict] = []        # 历史 short 交易记录
        hedge_borrow_cost_accum: float = 0.0

        # 缓存当日 OHLC, 避免反复 fetch (引擎只查每日开盘 + 收盘)
        # 不预读全部 universe (可能上千只), 按需缓存
        ohlc_cache: dict[str, pd.DataFrame] = {}

        def get_today(sym: str, mkt: str, day: str) -> Optional[pd.Series]:
            if sym not in ohlc_cache:
                try:
                    ohlc_cache[sym] = self.loader.get_daily(mkt, sym, start, end)
                except Exception:
                    ohlc_cache[sym] = pd.DataFrame()
            df = ohlc_cache[sym]
            if df.empty:
                return None
            row = df[df["date"] == day]
            return row.iloc[0] if not row.empty else None

        for i, day_str in enumerate(trading_days):
            day_dt = datetime.strptime(day_str, "%Y-%m-%d").date()

            # ===== Step 1: 执行 T+1 卖单 (今日开盘) =====
            still_pending_sells: list[tuple[Position, str, float]] = []
            for pos, reason, sell_fraction in pending_sells:
                # 防御: 该 symbol 可能已被前一笔 pending_sells 卖掉 (重复加入), 跳过避免双扣
                if pos.symbol not in positions:
                    continue
                bar = get_today(pos.symbol, pos.market, day_str)
                if bar is None:
                    still_pending_sells.append((pos, reason, sell_fraction))   # 停牌, 留到明天
                    continue
                exec_price = float(bar["open"]) * (1.0 - self.slippage)

                if sell_fraction < 1.0:
                    # ---- 部分出场（M5 partial exit）----
                    sell_size = int(pos.size * sell_fraction / 100) * 100
                    if sell_size <= 0:
                        sell_size = pos.size   # 仓位太小无法按手拆分时，退化为全出
                    sell_size = min(sell_size, pos.size)
                    gross = exec_price * sell_size
                    fees = gross * (self.commission + self.stamp_tax)
                    cash += gross - fees
                    pnl = (exec_price - pos.entry_price) * sell_size - fees
                    pnl_pct = exec_price / pos.entry_price - 1.0
                    hold_days = (day_dt - pos.entry_date).days
                    closed.append(ClosedTrade(
                        symbol=pos.symbol, market=pos.market,
                        entry_date=pos.entry_date, entry_price=pos.entry_price,
                        size=sell_size, exit_date=day_dt, exit_price=exec_price,
                        pnl=pnl, pnl_pct=pnl_pct, hold_days=hold_days,
                        exit_reason=reason,
                    ))
                    remaining = pos.size - sell_size
                    if remaining <= 0:
                        positions.pop(pos.symbol, None)
                    else:
                        pos.size = remaining
                        pos.partial_exit_done = True
                        # stop_loss 和 atr_stop_mult_override 已在 Step 3 (信号日) 由 evaluate() 写入
                else:
                    # ---- 全量出场 ----
                    gross = exec_price * pos.size
                    fees = gross * (self.commission + self.stamp_tax)
                    cash += gross - fees
                    pnl = (exec_price - pos.entry_price) * pos.size - fees
                    pnl_pct = exec_price / pos.entry_price - 1.0
                    hold_days = (day_dt - pos.entry_date).days
                    closed.append(ClosedTrade(
                        symbol=pos.symbol, market=pos.market,
                        entry_date=pos.entry_date, entry_price=pos.entry_price,
                        size=pos.size, exit_date=day_dt, exit_price=exec_price,
                        pnl=pnl, pnl_pct=pnl_pct, hold_days=hold_days,
                        exit_reason=reason,
                    ))
                    positions.pop(pos.symbol, None)
            pending_sells = still_pending_sells

            # ===== Step 2: 执行 T+1 买单 (今日开盘) =====
            still_pending_buys: list[BuySignal] = []
            for sig in pending_buys:
                if sig.symbol in positions:
                    continue   # 已经持有, 不重复买
                if len(positions) >= self.max_positions:
                    break
                bar = get_today(sig.symbol, sig.market, day_str)
                if bar is None:
                    still_pending_buys.append(sig)
                    continue
                exec_price = float(bar["open"]) * (1.0 + self.slippage)
                if exec_price <= 0:
                    # 美股 universe 含退市/OTC 脏数据 open=0；跳过避免 ZeroDivisionError
                    continue
                # 仓位 sizing
                max_value = self.initial_capital * self.single_position_pct
                avail_cash = cash * (1.0 - self.cash_buffer_pct)
                budget = min(max_value, avail_cash)
                size = int(budget / exec_price / 100) * 100   # A 股 100 股一手
                if size <= 0:
                    continue
                cost = exec_price * size
                fees = cost * self.commission
                if cost + fees > cash:
                    continue
                cash -= cost + fees
                positions[sig.symbol] = Position(
                    symbol=sig.symbol, market=sig.market,
                    entry_date=day_dt, entry_price=exec_price, size=size,
                    stop_loss=sig.stop_loss, take_profit=sig.take_profit,
                )
            pending_buys = still_pending_buys

            # ===== Step 2.5: L3 基准对冲 overlay（仅 ratio > 0 启用）=====
            # 决策：用「昨日 close vs MA」（无未来信息）；执行：今日 close（基准没有 open/high/low）
            if self.benchmark_hedge_ratio > 0 and bench_ma is not None and i >= 1:
                prev_day = trading_days[i - 1]
                prev_c = bench_close.get(prev_day)
                prev_m = bench_ma.get(prev_day) if bench_ma is not None else None
                today_c = bench_close.get(day_str)
                if (prev_c is not None and prev_m is not None and not pd.isna(prev_m)
                        and today_c is not None and not pd.isna(today_c)):
                    regime_on_yest = float(prev_c) > float(prev_m)
                    if regime_on_yest and hedge_short is None:
                        # 开空（按今日 close 成交）
                        ep = float(today_c)
                        size = self.initial_capital * self.benchmark_hedge_ratio / ep
                        hedge_short = {"entry_price": ep, "size": size, "entry_date_str": day_str}
                    elif (not regime_on_yest) and hedge_short is not None:
                        # 平空
                        cp = float(today_c)
                        size = hedge_short["size"]
                        ep = hedge_short["entry_price"]
                        pnl = (ep - cp) * size
                        # 借券成本（按持有天数线性扣）
                        entry_dt = datetime.strptime(hedge_short["entry_date_str"], "%Y-%m-%d").date()
                        days_held = max(0, (day_dt - entry_dt).days)
                        cost = ep * size * self.benchmark_hedge_borrow_cost * (days_held / 365.0)
                        cash += pnl - cost
                        hedge_borrow_cost_accum += cost
                        hedge_trades.append({
                            "entry_date": hedge_short["entry_date_str"],
                            "exit_date": day_str,
                            "entry_price": ep, "exit_price": cp,
                            "size": size, "pnl": pnl - cost, "days_held": days_held,
                        })
                        hedge_short = None

            # ===== Step 3: 评估持仓 (今日盘后) =====
            already_pending = {p.symbol for p, _, _f in pending_sells}
            for sym, pos in list(positions.items()):
                # A 股 T+1: 当日买的不能当日卖
                if pos.entry_date == day_dt:
                    continue
                if sym in already_pending:
                    continue   # 已在卖出队列, 不重复评估 / append
                ex = strategy.evaluate(pos, day_dt)
                nxt = trading_days[i + 1] if (i + 1) < len(trading_days) else ""
                if ex.action == "EXIT":
                    if diagnostics is not None:
                        diagnostics.exit_rows.append({
                            "decision_date": day_str,
                            "planned_exec_date": nxt,
                            "symbol": sym,
                            "reason": ex.reason,
                            "event": "exit_signal",
                            "exit_layer": getattr(ex, "exit_layer", None)
                            or exit_layer_from_reason(ex.reason),
                        })
                    pending_sells.append((pos, ex.reason, 1.0))
                elif ex.action == "PARTIAL_EXIT":
                    if diagnostics is not None:
                        diagnostics.exit_rows.append({
                            "decision_date": day_str,
                            "planned_exec_date": nxt,
                            "symbol": sym,
                            "reason": ex.reason,
                            "event": "partial_exit",
                            "exit_layer": getattr(ex, "exit_layer", None)
                            or exit_layer_from_reason(ex.reason),
                        })
                    # 立即写入宽松止损和 trail_mult（T+1 执行时 partial_exit_done 才置 True）
                    if ex.new_stop is not None:
                        pos.stop_loss = ex.new_stop
                    if ex.new_trail_mult is not None:
                        pos.atr_stop_mult_override = ex.new_trail_mult
                    pending_sells.append((pos, ex.reason, float(ex.partial_exit_pct)))
                elif ex.action == "PROMOTE_RUNNER":
                    # HK L1 优化：TP 命中时不卖，仅锁 stop + 标记 runner（非 3-tuple，不入 pending_sells）
                    if ex.new_stop is not None:
                        pos.stop_loss = ex.new_stop
                    pos.runner_active = True
                elif ex.new_stop is not None:
                    pos.stop_loss = ex.new_stop

            # ===== Step 4: 选股 (今日盘后) =====
            slots = self.max_positions - len(positions) - len(pending_buys)
            if slots > 0:
                signals = strategy.screen(day_dt)
                m4_cfg = getattr(strategy, "m4_cfg", None)
                if m4_cfg is not None and m4_cfg.m4_enabled:
                    signals = m4_prioritize_signals(
                        signals, positions, pending_buys, slots,
                        self.loader, market, day_str, m4_cfg,
                        market_ctx=getattr(strategy, "market_ctx", None),
                    )
                if diagnostics is not None and signals:
                    picked: list[str] = []
                    for sig in signals:
                        if sig.symbol in positions:
                            continue
                        if len(picked) < slots:
                            picked.append(sig.symbol)
                    picked_set = set(picked)
                    timing_reason = lambda s: (s.reasons or {}).get("timing", "")
                    for rank_idx, sig in enumerate(signals, start=1):
                        diagnostics.entry_rows.append({
                            "screen_date": day_str,
                            "factor_rank": rank_idx,
                            "symbol": sig.symbol,
                            "factor_score": sig.score,
                            "signal_entry_price": sig.entry_price,
                            "stop_loss": sig.stop_loss,
                            "take_profit": sig.take_profit,
                            "timing_reason": timing_reason(sig),
                            "already_held": sig.symbol in positions,
                            "queued_for_buy": sig.symbol in picked_set,
                        })
                taken = 0
                for sig in signals:
                    if sig.symbol in positions:
                        continue
                    pending_buys.append(sig)
                    taken += 1
                    if taken >= slots:
                        break

            # ===== Step 5: 净值 =====
            mv = cash
            for pos in positions.values():
                bar = get_today(pos.symbol, pos.market, day_str)
                if bar is not None:
                    mv += pos.size * float(bar["close"])
                else:
                    mv += pos.size * pos.entry_price   # 停牌按成本估
            # L3 short overlay MTM（短仓未实现盈亏，扣已累计借券成本估算）
            if hedge_short is not None:
                today_c = bench_close.get(day_str)
                if today_c is not None and not pd.isna(today_c):
                    ep = hedge_short["entry_price"]; size = hedge_short["size"]
                    mv += (ep - float(today_c)) * size
                    # 实时减去借券成本（持有期内估算，不入 cash 直到平仓）
                    entry_dt = datetime.strptime(hedge_short["entry_date_str"], "%Y-%m-%d").date()
                    days_held = max(0, (day_dt - entry_dt).days)
                    mv -= ep * size * self.benchmark_hedge_borrow_cost * (days_held / 365.0)
            equity_history.append((day_str, mv))
            position_history.append({
                "date": day_str, "n_positions": len(positions),
                "market_value": mv - cash, "cash": cash,
            })

            if verbose and (i + 1) % 5 == 0:
                print(f"  [{i+1:>3}/{len(trading_days)}] {day_str}  净值 {mv:>12,.0f}  "
                      f"持仓 {len(positions):>2}  累计交易 {len(closed):>3}", flush=True)

        # 强制平仓 (回测末日按收盘价). bar=None 时回退到 cache 里 <= last_day 的最近收盘.
        last_day_str = trading_days[-1]
        last_day_dt = datetime.strptime(last_day_str, "%Y-%m-%d").date()
        for pos in list(positions.values()):
            if diagnostics is not None:
                diagnostics.exit_rows.append({
                    "decision_date": last_day_str,
                    "planned_exec_date": last_day_str,
                    "symbol": pos.symbol,
                    "reason": "backtest_end_close",
                    "event": "forced_close",
                    "exit_layer": exit_layer_from_reason("backtest_end_close"),
                })
            bar = get_today(pos.symbol, pos.market, last_day_str)
            if bar is None:
                df = ohlc_cache.get(pos.symbol)
                if df is None or df.empty:
                    last_close = pos.entry_price
                else:
                    sub = df[df["date"] <= last_day_str]
                    last_close = float(sub["close"].iloc[-1]) if not sub.empty else pos.entry_price
                exec_price = last_close * (1.0 - self.slippage)
            else:
                exec_price = float(bar["close"]) * (1.0 - self.slippage)
            gross = exec_price * pos.size
            fees = gross * (self.commission + self.stamp_tax)
            cash += gross - fees
            pnl = (exec_price - pos.entry_price) * pos.size - fees
            pnl_pct = exec_price / pos.entry_price - 1.0
            hold_days = (last_day_dt - pos.entry_date).days
            closed.append(ClosedTrade(
                symbol=pos.symbol, market=pos.market,
                entry_date=pos.entry_date, entry_price=pos.entry_price,
                size=pos.size, exit_date=last_day_dt, exit_price=exec_price,
                pnl=pnl, pnl_pct=pnl_pct, hold_days=hold_days,
                exit_reason="backtest_end_close",
            ))
            positions.pop(pos.symbol, None)

        # L3：末日强平 short
        if hedge_short is not None:
            cp = bench_close.get(last_day_str)
            if cp is not None and not pd.isna(cp):
                cp_f = float(cp); ep = hedge_short["entry_price"]; size = hedge_short["size"]
                pnl = (ep - cp_f) * size
                entry_dt = datetime.strptime(hedge_short["entry_date_str"], "%Y-%m-%d").date()
                days_held = max(0, (last_day_dt - entry_dt).days)
                cost = ep * size * self.benchmark_hedge_borrow_cost * (days_held / 365.0)
                cash += pnl - cost
                hedge_borrow_cost_accum += cost
                hedge_trades.append({
                    "entry_date": hedge_short["entry_date_str"],
                    "exit_date": last_day_str,
                    "entry_price": ep, "exit_price": cp_f,
                    "size": size, "pnl": pnl - cost, "days_held": days_held,
                })
                hedge_short = None

        # 末值
        equity_history[-1] = (last_day_str, cash)

        equity_curve = pd.Series(
            dict(equity_history),
            name="equity",
        )
        equity_curve.index.name = "date"

        # 基准重定基到初始资金
        bench = bench_close.reindex(equity_curve.index)
        bench_curve = bench / bench.iloc[0] * self.initial_capital
        bench_curve.name = "benchmark"

        positions_df = pd.DataFrame(position_history).set_index("date")

        return BacktestResult(
            equity_curve=equity_curve,
            closed_trades=closed,
            benchmark_curve=bench_curve,
            daily_positions=positions_df,
        )
