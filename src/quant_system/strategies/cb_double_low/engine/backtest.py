"""CB Backtester (PR5) — 月度再平衡 + 双低 §3 出场判定 + M0 artifact contract.

设计:
- 月度再平衡: 每月第一个 trading day 调 compute_target_portfolio
- 月内 buy & hold + 强制出场监控 (强赎/止损/score 越线)
- 全市场 panel 一次性 DuckDB cache, backtest 仅扫 cache (秒级)

3 个 nuance (PR4 smoke 实测, 见 [[cb_data_probe_2026-06]] v1.1) 已内化:
1. asof 当日 panel 覆盖率不齐 → best-effort + 输出 daily_panel_coverage.csv 审计
2. exit_dual_low_threshold=150 已过时 → 默认 180 (yaml/Config 可调)
3. 负溢价债污染入场 → UniverseFilterConfig.min_conversion_premium=-5% 软底

M0 artifact (data/backtest/cb_double_low_<market>_<start>_<end>/):
- metrics.json
- equity.csv: date, portfolio_value
- positions.csv: date, n_positions, market_value, cash, equity
- closed_trades.csv: bond_code/entry/exit/pnl_pct/exit_reason/hold_days
- daily_panel_coverage.csv: date, asked_n, available_n, pct  (nuance 1)
- rebalance_funnel.csv: date, initial, dropped_*, passed
- entry_candidates.csv: rebalance_date, rank, bond_code, close, premium, score
- exit_events.csv: decision_date, bond_code, exit_reason
- exit_reason_summary.json
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

from quant_system.strategies.cb_double_low.data.loader import CBDataLoader
from quant_system.strategies.cb_double_low.engine.strategy import (
    CBDoubleLowConfig,
    compute_target_portfolio,
)


@dataclass
class CBPosition:
    bond_code: str
    entry_date: date
    entry_close: float
    entry_score: float
    size: int  # 张 (CB 标准 10 张/手, 100 元面值)

    def market_value(self, close: float) -> float:
        return float(close) * self.size


@dataclass
class CBClosedTrade:
    bond_code: str
    entry_date: date
    entry_close: float
    entry_score: float
    exit_date: date
    exit_close: float
    exit_reason: str
    hold_days: int
    pnl_pct: float
    size: int


@dataclass
class CBBacktestResult:
    equity_curve: pd.Series                  # date -> portfolio_value
    closed_trades: list[CBClosedTrade]
    daily_positions: pd.DataFrame            # date, n_positions, market_value, cash, equity
    daily_panel_coverage: pd.DataFrame       # date, asked_n, available_n, pct (nuance 1)
    rebalance_funnel: pd.DataFrame           # date + filter_stats
    entry_candidates: pd.DataFrame           # rebalance_date, rank, bond_code, close, premium, score
    exit_events: pd.DataFrame                # decision_date, bond_code, exit_reason


class CBBacktester:
    """Monthly rebalance, equal-weight CB double-low backtester."""

    REBALANCE_CHOICES = ("monthly", "weekly", "daily")

    def __init__(
        self,
        loader: CBDataLoader,
        config: CBDoubleLowConfig,
        initial_capital: float = 1_000_000.0,
        commission: float = 0.0001,    # CB 万分之 1 (券商低标准)
        slippage: float = 0.0005,      # 单边 5bp
        rebalance_freq: str = "monthly",
    ):
        if rebalance_freq not in self.REBALANCE_CHOICES:
            raise ValueError(
                f"rebalance_freq 非法 {rebalance_freq!r}, 需 {self.REBALANCE_CHOICES}"
            )
        self.loader = loader
        self.config = config
        self.initial_capital = float(initial_capital)
        self.commission = float(commission)
        self.slippage = float(slippage)
        self.rebalance_freq = rebalance_freq

    # ── public API ─────────────────────────────────────────────────────

    def run(self, start: str, end: str, verbose: bool = True) -> CBBacktestResult:
        start_dt = date.fromisoformat(start)
        end_dt = date.fromisoformat(end)

        # 1. universe (asof=end). 已公告/要强赎排除. 仍含 look-ahead
        #    (asof=end 的 universe 反映"未来"状态), PR6+ 可改成滚动 asof.
        universe = self.loader.load_universe(asof=end_dt)
        active = universe[
            ~universe["exit_status"].isin(
                self.config.filter_config.exclude_exit_statuses
            )
        ].copy()
        codes = active["bond_code"].tolist()
        if verbose:
            print(f"universe: {len(universe)}, active: {len(active)}")

        # 2. panel cache hit (一次性扫全 universe)
        if verbose:
            print(f"loading panel {len(codes)} codes [{start} → {end}]...")
        panel = self.loader.load_panel(start=start_dt, end=end_dt, codes=codes)
        if len(panel) == 0:
            raise RuntimeError("panel empty — 检查 cache / date range")
        if verbose:
            print(f"panel: {panel.shape}")

        # 3. redemption events (used for forced exit + filter_universe)
        redemption = self.loader.load_redemption_events(asof=end_dt)

        # 4. trading days (用 panel 自己的日期; CB 市场用)
        trading_days = sorted({d.date() for d in panel["date"]})
        if verbose:
            print(f"trading days in [{start}, {end}]: {len(trading_days)}")

        # 5. 再平衡日期
        rebalance_dates = self._compute_rebalance_dates(trading_days)
        if verbose:
            print(f"rebalance days: {len(rebalance_dates)}")

        # 6. 主循环
        panel = panel.copy()
        panel["_date_only"] = panel["date"].dt.date
        panel_by_date = {d: g for d, g in panel.groupby("_date_only")}

        cash = self.initial_capital
        positions: dict[str, CBPosition] = {}
        closed: list[CBClosedTrade] = []
        equity_history: list[tuple[date, float]] = []
        position_history: list[dict] = []
        coverage_history: list[dict] = []
        funnel_history: list[dict] = []
        entries_history: list[dict] = []
        exits_history: list[dict] = []

        for d in trading_days:
            panel_today = panel_by_date.get(
                d, pd.DataFrame(columns=panel.columns)
            )

            # 7. coverage stats (nuance 1)
            available_n = (
                panel_today["bond_code"].nunique() if len(panel_today) else 0
            )
            coverage_history.append(
                {
                    "date": d,
                    "asked_n": len(codes),
                    "available_n": available_n,
                    "pct": (available_n / len(codes)) if codes else 0.0,
                }
            )

            close_map: dict[str, float] = (
                dict(zip(panel_today["bond_code"], panel_today["close"]))
                if len(panel_today)
                else {}
            )
            prem_map: dict[str, float] = (
                dict(
                    zip(
                        panel_today["bond_code"],
                        panel_today["conversion_premium_rate"],
                    )
                )
                if len(panel_today)
                else {}
            )

            # 8. 强制出场检查 (每天, 不只是 rebalance 日)
            redeem_today_codes = self._redeem_active_on(redemption, d)
            force_exits: list[tuple[str, str]] = []
            for code in list(positions.keys()):
                if code in redeem_today_codes:
                    force_exits.append((code, "redeem_announced"))
                    continue
                close_today = close_map.get(code)
                if close_today is None or pd.isna(close_today):
                    continue  # 当日 panel 缺数据, 等下一日
                if close_today < self.config.stop_loss_close:
                    force_exits.append((code, "stop_loss"))
                    continue
                prem_today = prem_map.get(code, 0.0)
                score_today = float(close_today) + float(prem_today)
                if score_today > self.config.exit_dual_low_threshold:
                    force_exits.append((code, "dual_low_too_high"))
                    continue
            for code, reason in force_exits:
                cash = self._execute_exit(
                    d, code, reason, positions, close_map,
                    closed, exits_history, cash,
                )

            # 9. 月度再平衡
            if d in rebalance_dates and len(panel_today) > 0:
                current_holdings = list(positions.keys())
                out = compute_target_portfolio(
                    universe=active,
                    panel_today=panel_today.rename(columns={"_date_only": "_date"}),
                    redemption=redemption,
                    current_holdings=current_holdings,
                    asof=d,
                    config=self.config,
                )
                stats = dict(out["filter_stats"])
                stats["date"] = d
                funnel_history.append(stats)

                # 记 entry candidates (从 filtered top N 取)
                filtered = active[["bond_code"]].merge(
                    panel_today[
                        ["bond_code", "close", "conversion_premium_rate"]
                    ],
                    on="bond_code",
                    how="inner",
                ).copy()
                filtered["dual_low_score"] = (
                    filtered["close"] + filtered["conversion_premium_rate"]
                )
                ranked = (
                    filtered.dropna(subset=["dual_low_score"])
                    .nsmallest(self.config.n_entry, "dual_low_score")
                    .reset_index(drop=True)
                )
                for i, row in ranked.iterrows():
                    entries_history.append(
                        {
                            "rebalance_date": d,
                            "rank": i + 1,
                            "bond_code": row["bond_code"],
                            "close": float(row["close"]),
                            "conversion_premium_rate": float(
                                row["conversion_premium_rate"]
                            ),
                            "dual_low_score": float(row["dual_low_score"]),
                        }
                    )

                # 出场: out["exited"] (out_of_top_band etc, 已在 strategy 评估)
                for code, reason in out["exited"]:
                    if code in positions:
                        cash = self._execute_exit(
                            d, code, reason, positions, close_map,
                            closed, exits_history, cash,
                        )

                # 进场: out["entered"]
                for code in out["entered"]:
                    close_today = close_map.get(code)
                    if close_today is None or pd.isna(close_today):
                        continue
                    cash = self._execute_entry(
                        d, code, float(close_today),
                        float(prem_map.get(code, 0.0)),
                        positions, close_map, cash,
                    )

            # 10. equity snapshot
            mv = sum(
                p.market_value(close_map.get(p.bond_code, p.entry_close))
                for p in positions.values()
            )
            equity = cash + mv
            equity_history.append((d, equity))
            position_history.append(
                {
                    "date": d,
                    "n_positions": len(positions),
                    "market_value": mv,
                    "cash": cash,
                    "equity": equity,
                }
            )

        eq_idx = pd.to_datetime([d for d, _ in equity_history])
        eq_series = pd.Series(
            [v for _, v in equity_history], index=eq_idx, name="portfolio_value"
        )
        eq_series.index.name = "date"

        return CBBacktestResult(
            equity_curve=eq_series,
            closed_trades=closed,
            daily_positions=pd.DataFrame(position_history),
            daily_panel_coverage=pd.DataFrame(coverage_history),
            rebalance_funnel=pd.DataFrame(funnel_history),
            entry_candidates=pd.DataFrame(entries_history),
            exit_events=pd.DataFrame(exits_history),
        )

    # ── helpers ────────────────────────────────────────────────────────

    def _execute_exit(
        self, d: date, code: str, reason: str,
        positions: dict, close_map: dict,
        closed: list, exits_history: list, cash: float,
    ) -> float:
        pos = positions.pop(code)
        close_today = close_map.get(code, pos.entry_close)
        if pd.isna(close_today):
            close_today = pos.entry_close
        exec_price = float(close_today) * (1 - self.slippage)
        gross = exec_price * pos.size
        fees = gross * self.commission
        cash += gross - fees
        pnl_pct = (exec_price - pos.entry_close) / pos.entry_close
        closed.append(
            CBClosedTrade(
                bond_code=code,
                entry_date=pos.entry_date,
                entry_close=pos.entry_close,
                entry_score=pos.entry_score,
                exit_date=d,
                exit_close=exec_price,
                exit_reason=reason,
                hold_days=(d - pos.entry_date).days,
                pnl_pct=pnl_pct,
                size=pos.size,
            )
        )
        exits_history.append(
            {"decision_date": d, "bond_code": code, "exit_reason": reason}
        )
        return cash

    def _execute_entry(
        self, d: date, code: str, close_today: float, prem_today: float,
        positions: dict, close_map: dict, cash: float,
    ) -> float:
        total_equity = cash + sum(
            p.market_value(close_map.get(p.bond_code, p.entry_close))
            for p in positions.values()
        )
        target_value = total_equity / self.config.n_entry
        exec_price = close_today * (1 + self.slippage)
        if exec_price <= 0:
            return cash
        n_units = int(target_value / exec_price / 10) * 10  # 10 张/手
        if n_units < 10:
            return cash
        cost = exec_price * n_units * (1 + self.commission)
        if cost > cash:
            n_units = max(
                int(cash / (exec_price * (1 + self.commission)) / 10) * 10, 0
            )
            if n_units < 10:
                return cash
            cost = exec_price * n_units * (1 + self.commission)
        cash -= cost
        positions[code] = CBPosition(
            bond_code=code, entry_date=d, entry_close=close_today,
            entry_score=close_today + prem_today, size=n_units,
        )
        return cash

    def _redeem_active_on(self, redemption: pd.DataFrame, d: date) -> set:
        """asof 当日已触发 last_trading_date 的强赎 bond_code 集合.

        近似: last_trading_date <= asof 视为强赎已生效 (实际公告通常在 last_trading 前 1-2 月).
        backtest 阶段用 last_trading_date 作 proxy 避免 announcement_date 的 NaT 占位 (PR3 limitation).
        """
        if redemption.empty or "last_trading_date" not in redemption.columns:
            return set()
        ts = pd.Timestamp(d)
        mask = redemption["last_trading_date"].notna() & (
            redemption["last_trading_date"] <= ts
        )
        return set(redemption.loc[mask, "bond_code"].astype(str))

    def _compute_rebalance_dates(self, trading_days: list[date]) -> set[date]:
        if not trading_days:
            return set()
        if self.rebalance_freq == "daily":
            return set(trading_days)
        rebalances: set[date] = set()
        seen: set = set()
        for d in sorted(trading_days):
            if self.rebalance_freq == "monthly":
                key = (d.year, d.month)
            else:  # weekly
                iso = d.isocalendar()
                key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key)
                rebalances.add(d)
        return rebalances


# ── M0 artifact ────────────────────────────────────────────────────────


def write_m0_artifact(
    result: CBBacktestResult,
    out_dir: Path,
    *,
    strategy: str = "cb_double_low",
    market: str = "a_share",
    start: str = "",
    end: str = "",
    config: Optional[CBDoubleLowConfig] = None,
) -> dict:
    """落盘 M0 artifact contract (data/backtest/<strategy>_<market>_<start>_<end>/)."""
    out_dir.mkdir(parents=True, exist_ok=True)

    eq = result.equity_curve.reset_index()
    eq.columns = ["date", "portfolio_value"]
    eq.to_csv(out_dir / "equity.csv", index=False)

    result.daily_positions.to_csv(out_dir / "positions.csv", index=False)

    closed_rows = [t.__dict__ for t in result.closed_trades]
    pd.DataFrame(closed_rows).to_csv(out_dir / "closed_trades.csv", index=False)

    result.daily_panel_coverage.to_csv(
        out_dir / "daily_panel_coverage.csv", index=False
    )
    result.rebalance_funnel.to_csv(out_dir / "rebalance_funnel.csv", index=False)
    result.entry_candidates.to_csv(out_dir / "entry_candidates.csv", index=False)
    result.exit_events.to_csv(out_dir / "exit_events.csv", index=False)

    metrics = _compute_metrics(result, strategy, market, start, end, config)
    (out_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    exit_summary = _summarize_exit_reasons(result)
    (out_dir / "exit_reason_summary.json").write_text(
        json.dumps(exit_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return metrics


def _compute_metrics(
    result: CBBacktestResult,
    strategy: str, market: str, start: str, end: str,
    config: Optional[CBDoubleLowConfig],
) -> dict:
    eq = result.equity_curve
    if len(eq) < 2:
        return {
            "strategy": strategy, "market": market,
            "error": "equity series too short",
        }
    initial = float(eq.iloc[0])
    final = float(eq.iloc[-1])
    total_return = final / initial - 1
    n_days = len(eq)
    years = n_days / 252.0
    cagr = (final / initial) ** (1 / years) - 1 if years > 0 else 0.0

    rets = eq.pct_change().dropna()
    if rets.std() > 0:
        sharpe = float(rets.mean() / rets.std() * (252 ** 0.5))
    else:
        sharpe = 0.0

    running_max = eq.cummax()
    drawdowns = eq / running_max - 1
    max_dd = float(drawdowns.min())

    closed = result.closed_trades
    n_trades = len(closed)
    if n_trades > 0:
        wins = sum(1 for t in closed if t.pnl_pct > 0)
        hit_rate = wins / n_trades
        avg_pnl_pct = sum(t.pnl_pct for t in closed) / n_trades
    else:
        hit_rate = 0.0
        avg_pnl_pct = 0.0

    return {
        "strategy": strategy,
        "market": market,
        "start": start,
        "end": end,
        "initial_capital": initial,
        "final_equity": final,
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "n_closed_trades": n_trades,
        "hit_rate": hit_rate,
        "avg_pnl_pct": avg_pnl_pct,
        "config": {
            "n_entry": config.n_entry if config else None,
            "n_hold_buffer": config.n_hold_buffer if config else None,
            "exit_dual_low_threshold":
                config.exit_dual_low_threshold if config else None,
            "stop_loss_close": config.stop_loss_close if config else None,
        },
    }


def _summarize_exit_reasons(result: CBBacktestResult) -> dict:
    closed_by_reason: dict = {}
    for t in result.closed_trades:
        closed_by_reason[t.exit_reason] = (
            closed_by_reason.get(t.exit_reason, 0) + 1
        )
    events_by_reason: dict = {}
    if not result.exit_events.empty:
        for reason, n in (
            result.exit_events["exit_reason"].value_counts().items()
        ):
            events_by_reason[reason] = int(n)
    return {
        "closed_trades_by_exit_reason": closed_by_reason,
        "exit_events_by_reason": events_by_reason,
    }
