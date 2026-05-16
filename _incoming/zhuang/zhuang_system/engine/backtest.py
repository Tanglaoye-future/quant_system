"""
庄股策略回测引擎.

流程：
  逐日遍历交易日历 →
    Step 1: 执行昨日待卖出（以今日开盘价成交）
    Step 2: 检查现有持仓出场信号（以今日收盘为基准）
    Step 3: 扫描 universe 入场信号
    Step 4: 执行入场（以明日开盘价，此处用今日收盘近似，回测中标准做法）
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from zhuang_system.data.loader import ZhuangDataLoader
from zhuang_system.engine.metrics import compute_metrics
from zhuang_system.engine.position import ClosedTrade, Position
from zhuang_system.signals.accumulation import accumulation_score
from zhuang_system.signals.entry import BuySignal, check_entry_signal
from zhuang_system.signals.exit import check_exit_signal


class ZhuangBacktester:
    """庄股跟庄策略回测引擎."""

    def __init__(self, config: dict, loader: ZhuangDataLoader) -> None:
        self.config = config
        self.loader = loader

        bt = config.get("backtest", {})
        self.initial_capital = float(bt.get("initial_capital", 1_000_000))
        self.commission = float(bt.get("commission", 0.0003))
        self.stamp_tax = float(bt.get("stamp_tax", 0.001))
        self.slippage = float(bt.get("slippage", 0.002))
        self.output_dir = Path(bt.get("output_dir", "./data/backtest"))

        strat = config.get("strategy", {})
        self.max_hold_days = int(strat.get("max_hold_days", 15))
        self.single_pos_pct_max = float(strat.get("single_position_pct_max", 0.05))
        self.pos_max_count = int(strat.get("position_max_count", 6))
        self.acc_score_entry = float(strat.get("accumulation_score_entry", 65.0))
        self.vol_spike_ratio = float(strat.get("volume_spike_ratio_min", 2.0))
        self.stop_loss_atr_mult = float(strat.get("stop_loss_atr_mult", 2.0))
        self.max_stop_loss_pct = float(strat.get("max_stop_loss_pct", 0.06))
        self.momentum_stop_pct = float(strat.get("momentum_stop_pct", 0.05))
        self.take_profit_pct = float(strat.get("take_profit_pct", 0.15))
        self.dist_turnover_thresh = float(strat.get("distribution_turnover_thresh", 8.0))
        self.extend_hold_days = int(strat.get("extend_hold_days", 25))
        self.extend_profit_pct = float(strat.get("extend_profit_pct", 0.05))
        self.entry_price_position_min = float(strat.get("entry_price_position_min", 0.5))
        # L2: 相对强度过滤（个股 20d 超额收益 vs 基准）。None=关闭
        rs_min = strat.get("entry_relative_strength_min", None)
        self.entry_rs_min: float | None = (
            float(rs_min) if rs_min is not None else None
        )
        # L3: 基准波动 regime 过滤。vol_regime_filter=true 时启用
        self.vol_regime_filter = bool(strat.get("vol_regime_filter", False))
        self.vol_regime_lookback = int(strat.get("vol_regime_lookback", 20))
        self.vol_regime_window = int(strat.get("vol_regime_window", 252))
        self.vol_regime_pct_max = float(strat.get("vol_regime_pct_max", 0.80))

        # 市场趋势过滤
        self.market_trend_filter = bool(strat.get("market_trend_filter", False))
        self.market_trend_index = strat.get("market_trend_index", "sh.000905")
        self.market_trend_ma = int(strat.get("market_trend_ma", 60))

        acc_w_cfg = config.get("accumulation_weights", {})
        self.acc_weights = acc_w_cfg if acc_w_cfg else None

    # ── 主入口 ────────────────────────────────────────────────────────────────

    def run(
        self,
        start: str,
        end: str,
        universe: Optional[list[str]] = None,
        verbose: bool = True,
    ) -> dict:
        """
        运行回测，返回绩效指标字典.

        Parameters
        ----------
        start, end : str
            yyyy-mm-dd
        universe : list[str] | None
            股票代码列表；None 时调用 loader.get_universe(start)
        """
        if universe is None:
            if verbose:
                print(f"[backtest] 获取 universe (asof={start})...", flush=True)
            universe = self.loader.get_universe(start)
        if verbose:
            print(f"[backtest] universe size={len(universe)}", flush=True)

        # 加载基准指数（用于市场趋势过滤 + L2 相对强度 + L3 vol regime）
        benchmark_ma: dict[str, bool] = {}   # date → 是否处于上升趋势
        bench_close: dict[str, float] = {}   # date → close（L2 用）
        bench_vol_high: dict[str, bool] = {} # date → 是否处于高 vol regime（L3 用）
        need_bench = (
            self.market_trend_filter
            or self.entry_rs_min is not None
            or self.vol_regime_filter
        )
        if need_bench:
            idx_code = self.market_trend_index.split(".")[-1]   # "000905"
            if verbose:
                print(f"[backtest] 加载基准指数 {self.market_trend_index} 计算 MA{self.market_trend_ma}/RS/Vol regime...", flush=True)
            # 多取一年历史（vol regime percentile 需要 252 天）
            idx_start = (pd.Timestamp(start) - pd.Timedelta(days=420)).strftime("%Y-%m-%d")
            idx_df = self.loader.get_daily(idx_code, idx_start, end)
            if not idx_df.empty:
                idx_df = idx_df.sort_values("date").reset_index(drop=True)
                idx_df["ma60"] = idx_df["close"].rolling(self.market_trend_ma).mean()
                idx_df["ma20"] = idx_df["close"].rolling(20).mean()
                # L3 vol regime：基准 N 日收益标准差的滚动 percentile
                idx_df["ret"] = idx_df["close"].pct_change()
                idx_df["realized_vol"] = idx_df["ret"].rolling(self.vol_regime_lookback).std()
                idx_df["vol_rank"] = idx_df["realized_vol"].rolling(
                    self.vol_regime_window, min_periods=60
                ).rank(pct=True)
                for _, row in idx_df.iterrows():
                    d = str(row["date"])[:10]
                    if d >= start:
                        ma60 = row["ma60"]
                        ma20 = row["ma20"]
                        close_idx = float(row["close"])
                        bench_close[d] = close_idx
                        if self.market_trend_filter:
                            benchmark_ma[d] = (
                                not pd.isna(ma60) and not pd.isna(ma20)
                                and close_idx > float(ma60)
                                and float(ma20) > float(ma60)
                            )
                        if self.vol_regime_filter:
                            vol_rank = row["vol_rank"]
                            bench_vol_high[d] = (
                                not pd.isna(vol_rank)
                                and float(vol_rank) > self.vol_regime_pct_max
                            )

        # 预加载所有股票日线
        if verbose:
            print(f"[backtest] 预加载行情 {start}–{end}...", flush=True)
        px_cache: dict[str, pd.DataFrame] = {}
        for i, code in enumerate(universe, 1):
            df = self.loader.get_daily(code, start, end)
            if not df.empty:
                px_cache[code] = df
            if verbose and i % 100 == 0:
                print(f"  loaded {i}/{len(universe)}", flush=True)

        # 生成交易日历（取所有股票日线的日期并集）
        all_dates: list[str] = sorted(
            set(
                d for df in px_cache.values()
                for d in df["date"].astype(str).str[:10].tolist()
            )
        )
        all_dates = [d for d in all_dates if start <= d <= end]
        if verbose:
            print(f"[backtest] 交易日 {len(all_dates)} 天", flush=True)

        # 状态
        cash = self.initial_capital
        positions: dict[str, Position] = {}      # code → Position
        closed_trades: list[ClosedTrade] = []
        equity_curve: list[tuple[str, float]] = []
        pending_exits: list[tuple[str, str]] = []   # (code, reason)

        for date_idx, date in enumerate(all_dates):
            # ── Step 1: 执行昨日待出场 ───────────────────────────────────────
            new_pending: list[tuple[str, str]] = []
            for code, reason in pending_exits:
                if code not in positions:
                    continue
                pos = positions[code]
                # 以今日开盘价成交（近似：用今日日线）
                if code in px_cache:
                    today_df = px_cache[code]
                    today_row = today_df[today_df["date"].astype(str).str[:10] == date]
                    if not today_row.empty:
                        sell_px = float(today_row.iloc[0]["open"]) * (1 - self.slippage)
                    else:
                        sell_px = pos.entry_price  # fallback
                else:
                    sell_px = pos.entry_price

                pnl_gross = (sell_px - pos.entry_price) * pos.size
                sell_cost = sell_px * pos.size * (self.commission + self.stamp_tax)
                buy_cost = pos.entry_price * pos.size * self.commission
                pnl_net = pnl_gross - sell_cost - buy_cost
                pnl_pct = pnl_net / (pos.entry_price * pos.size)

                # 计算持有天数
                entry_idx = next(
                    (i for i, d in enumerate(all_dates) if d >= pos.entry_date), 0
                )
                hold_days = date_idx - entry_idx

                closed_trades.append(ClosedTrade(
                    code=code,
                    entry_date=pos.entry_date,
                    exit_date=date,
                    entry_price=pos.entry_price,
                    exit_price=sell_px,
                    size=pos.size,
                    pnl=pnl_net,
                    pnl_pct=pnl_pct,
                    hold_days=hold_days,
                    exit_reason=reason,
                    accumulation_score=pos.accumulation_score,
                    phase=pos.phase,
                ))
                cash += sell_px * pos.size - sell_cost
                del positions[code]

            # ── 计算今日持仓市值 → 权益曲线 ─────────────────────────────────
            pos_value = 0.0
            for code, pos in positions.items():
                if code in px_cache:
                    today_df = px_cache[code]
                    today_row = today_df[today_df["date"].astype(str).str[:10] == date]
                    if not today_row.empty:
                        pos_value += float(today_row.iloc[0]["close"]) * pos.size
                    else:
                        pos_value += pos.entry_price * pos.size
                else:
                    pos_value += pos.entry_price * pos.size
            equity_curve.append((date, cash + pos_value))

            # ── Step 2: 检查现有持仓出场 ─────────────────────────────────────
            for code in list(positions.keys()):
                pos = positions[code]
                if code not in px_cache:
                    continue
                full_df = px_cache[code]
                df_since_entry = full_df[
                    full_df["date"].astype(str).str[:10] >= pos.entry_date
                ]
                df_since_entry = df_since_entry[
                    df_since_entry["date"].astype(str).str[:10] <= date
                ]
                sig = check_exit_signal(
                    code=code,
                    df_since_entry=df_since_entry,
                    entry_price=pos.entry_price,
                    entry_date=pos.entry_date,
                    atr_at_entry=pos.atr_at_entry,
                    stop_loss_atr_mult=self.stop_loss_atr_mult,
                    max_stop_loss_pct=self.max_stop_loss_pct,
                    momentum_stop_pct=self.momentum_stop_pct,
                    take_profit_pct=self.take_profit_pct,
                    max_hold_days=self.max_hold_days,
                    extend_hold_days=self.extend_hold_days,
                    extend_profit_pct=self.extend_profit_pct,
                    distribution_turnover_thresh=self.dist_turnover_thresh,
                )
                if sig.action == "EXIT":
                    pending_exits.append((code, sig.reason))

            # ── Step 3 & 4: 扫描入场信号 ────────────────────────────────────
            if len(positions) >= self.pos_max_count:
                continue

            # 市场趋势过滤：指数在MA60以下时不开新仓
            if self.market_trend_filter and benchmark_ma:
                if not benchmark_ma.get(date, True):
                    continue

            # L3: vol regime gate — 基准 vol percentile > 阈值时停手
            if self.vol_regime_filter and bench_vol_high.get(date, False):
                continue

            # L2: 计算当日基准 20d 收益（供下方 relative strength 过滤）
            bench_20d_ret: float | None = None
            if self.entry_rs_min is not None and bench_close:
                bench_dates_sorted = sorted(d for d in bench_close if d <= date)
                if len(bench_dates_sorted) >= 21:
                    p_now = bench_close[bench_dates_sorted[-1]]
                    p_20 = bench_close[bench_dates_sorted[-21]]
                    if p_20 > 0:
                        bench_20d_ret = (p_now - p_20) / p_20

            already_in = set(positions.keys()) | {c for c, _ in pending_exits}
            candidates: list[BuySignal] = []
            for code in universe:
                if code in already_in:
                    continue
                if code not in px_cache:
                    continue
                full_df = px_cache[code]
                df_up_to = full_df[full_df["date"].astype(str).str[:10] <= date]

                # L2: 相对强度过滤 — 个股 20d 超额收益 vs 基准 ≥ 阈值
                if self.entry_rs_min is not None and bench_20d_ret is not None and len(df_up_to) >= 21:
                    p_now = float(df_up_to["close"].iloc[-1])
                    p_20 = float(df_up_to["close"].iloc[-21])
                    if p_20 > 0:
                        stock_20d_ret = (p_now - p_20) / p_20
                        if (stock_20d_ret - bench_20d_ret) < self.entry_rs_min:
                            continue

                sig = check_entry_signal(
                    code=code,
                    df=df_up_to,
                    asof_date=date,
                    score_threshold=self.acc_score_entry,
                    volume_spike_ratio=self.vol_spike_ratio,
                    phase="A",
                    acc_weights=self.acc_weights,
                    price_position_min=self.entry_price_position_min,
                )
                if sig is not None:
                    candidates.append(sig)

            # 按吃货期评分降序选取
            candidates.sort(key=lambda s: s.accumulation_score, reverse=True)
            for sig in candidates:
                if len(positions) >= self.pos_max_count:
                    break
                code = sig.code
                # 入场价用当日收盘（回测近似；实盘改用次日开盘）
                entry_px = sig.price * (1 + self.slippage)
                max_value = self.initial_capital * self.single_pos_pct_max
                raw_size = int(max_value / entry_px / 100) * 100
                if raw_size < 100:
                    continue
                cost = entry_px * raw_size * (1 + self.commission)
                if cash < cost:
                    continue

                # ATR
                full_df = px_cache[code]
                df_up_to = full_df[full_df["date"].astype(str).str[:10] <= date]
                atr_series = self.loader.compute_atr(df_up_to)
                atr_val = float(atr_series.iloc[-1]) if not atr_series.empty else entry_px * 0.03
                if np.isnan(atr_val):
                    atr_val = entry_px * 0.03

                stop_loss_px = entry_px - self.stop_loss_atr_mult * atr_val
                take_profit_px = entry_px * (1.0 + self.take_profit_pct)

                positions[code] = Position(
                    code=code,
                    entry_date=date,
                    entry_price=entry_px,
                    size=raw_size,
                    atr_at_entry=atr_val,
                    stop_loss_price=stop_loss_px,
                    take_profit_price=take_profit_px,
                    accumulation_score=sig.accumulation_score,
                    phase=sig.phase,
                    entry_reason=sig.reason,
                )
                cash -= cost

        # ── 强平剩余持仓 ──────────────────────────────────────────────────────
        last_date = all_dates[-1] if all_dates else end
        for code, pos in list(positions.items()):
            if code in px_cache:
                df = px_cache[code]
                last_row = df[df["date"].astype(str).str[:10] <= last_date]
                if not last_row.empty:
                    sell_px = float(last_row.iloc[-1]["close"]) * (1 - self.slippage)
                else:
                    sell_px = pos.entry_price
            else:
                sell_px = pos.entry_price

            pnl_gross = (sell_px - pos.entry_price) * pos.size
            sell_cost = sell_px * pos.size * (self.commission + self.stamp_tax)
            buy_cost = pos.entry_price * pos.size * self.commission
            pnl_net = pnl_gross - sell_cost - buy_cost
            pnl_pct = pnl_net / (pos.entry_price * pos.size)

            entry_idx = next(
                (i for i, d in enumerate(all_dates) if d >= pos.entry_date), 0
            )
            hold_days = len(all_dates) - 1 - entry_idx

            closed_trades.append(ClosedTrade(
                code=code, entry_date=pos.entry_date, exit_date=last_date,
                entry_price=pos.entry_price, exit_price=sell_px, size=pos.size,
                pnl=pnl_net, pnl_pct=pnl_pct, hold_days=hold_days,
                exit_reason="backtest_end_close",
                accumulation_score=pos.accumulation_score, phase=pos.phase,
            ))
            cash += sell_px * pos.size - sell_cost

        # ── 绩效计算 ──────────────────────────────────────────────────────────
        equity_series = pd.Series(
            [v for _, v in equity_curve],
            index=pd.to_datetime([d for d, _ in equity_curve]),
            name="equity",
        )
        metrics = compute_metrics(closed_trades, equity_series, self.initial_capital)
        metrics["start"] = start
        metrics["end"] = end

        # ── 保存结果 ──────────────────────────────────────────────────────────
        tag = f"zhuang_a_share_{start}_{end}"
        out_dir = self.output_dir / tag
        out_dir.mkdir(parents=True, exist_ok=True)

        trades_df = pd.DataFrame([t.__dict__ for t in closed_trades])
        trades_df.to_csv(out_dir / "trades.csv", index=False)
        equity_series.to_csv(out_dir / "equity_curve.csv", header=True)
        pd.Series(metrics).to_csv(out_dir / "metrics.csv", header=False)

        if verbose:
            self._print_summary(metrics, out_dir)

        return metrics

    def _print_summary(self, m: dict, out_dir: Path) -> None:
        print("\n" + "=" * 55)
        print("庄股策略回测结果")
        print("=" * 55)
        print(f"  总收益率   : {m['total_return']*100:+.2f}%")
        print(f"  年化收益率 : {m['annualized_return']*100:+.2f}%")
        print(f"  夏普比率   : {m['sharpe_ratio']:.4f}")
        print(f"  最大回撤   : {m['max_drawdown']*100:.2f}%")
        print(f"  胜率       : {m['win_rate']*100:.1f}%")
        print(f"  盈亏比     : {m['profit_factor']:.2f}")
        print(f"  总交易数   : {m['total_trades']}")
        print(f"  平均持有天 : {m['hold_days_avg']:.1f}")
        print(f"  输出目录   : {out_dir}")
        print("=" * 55)
