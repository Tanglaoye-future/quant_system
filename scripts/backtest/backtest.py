"""
回测主入口.

用法:
  python scripts/backtest.py                    # 默认: bottomup_timing 策略, 全段, HS300
  python scripts/backtest.py --start 2025-01-01 --end 2026-04-27
  python scripts/backtest.py --capital 500000

输出:
  data/backtest/<strategy>_<market>_<start>_<end>/
    （固定目录；每次运行会先清空再写入，不累积 run_id）
    equity.csv                   每日净值 + 基准
    trades.csv                     所有交易明细
    positions.csv                  每日持仓数 / 市值 / 现金
    report.txt                     指标 + 准入判定
    metrics.json
    universe_filtered_sample.csv   (A 股) start 日 universe 过滤明细
    universe_filter_stats_sample.json
    entry_candidates.csv           每日 timing 命中 + 因子排序 + 是否入队待买
    ranking.csv                    同上精简列 (screen_date, rank, symbol, score)
    exit_events.csv                卖出决策日 + 计划执行日 + 原因 (+ 末日强平)
    exit_reason_summary.json       成交/决策事件按 reason 与 exit_layer 分布

择时参数: config.yaml -> strategy.timing（含 M2 字段）
"""
from __future__ import annotations

import argparse
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd

from quant_system.strategies.equity_factor.bottomup.factors import FactorWeights
from quant_system.strategies.equity_factor.bottomup.portfolio import m4_config_from_yaml
from quant_system.config import load_config, resolve_strategy, resolve_strategy_params
from quant_system.market import load_market_context
from quant_system.strategies.equity_factor.data.loader import DataLoader
from quant_system.strategies.equity_factor.engine.backtest import BacktestDiagnostics, Backtester
from quant_system.strategies.equity_factor.engine.metrics import check_admission, compute_metrics
from quant_system.strategies.equity_factor.engine.strategy import BottomupTimingStrategy
from quant_system.strategies.equity_factor.timing.exit_taxonomy import exit_layer_from_reason
from quant_system.strategies.equity_factor.timing.signals import timing_config_from_yaml_node
from quant_system.strategies.equity_factor.universe.filter import UniverseFilter, UniverseFilterConfig


def build_strategy(kind: str, loader: DataLoader, cfg, market: str,
                   strategy_name: str | None = None) -> object:
    """策略工厂. 入参 kind 是工厂键 (bottomup_timing / mean_reversion).
    参数从 resolve_strategy_params(cfg, market, strategy_name) 拿 — Phase 1-B 后
    支持一市多策略，传入 strategy_name 用二维 deployments 索引精确取参.
    """
    # Phase 1-B: 优先用 deployments[strategy_name][market]；缺失时回退 markets[market]
    deployments = cfg.get("deployments") or {}
    dep_entry = (deployments.get(strategy_name) or {}).get(market) if strategy_name else None
    market_cfg = dep_entry or cfg.get("markets", market) or {}
    universe = loader.get_universe(market, market_cfg["universe"])
    params = resolve_strategy_params(cfg, market, strategy_name=strategy_name)
    market_ctx = load_market_context(cfg, market)

    if kind == "mean_reversion":
        from quant_system.strategies.equity_factor.engine.strategy import MeanReversionStrategy, MeanReversionConfig
        mr_node = (market_cfg.get("mean_reversion") or {}) if isinstance(market_cfg, dict) else {}
        return MeanReversionStrategy(
            loader=loader, market=market,
            universe_codes=universe["code"].tolist(),
            cfg=MeanReversionConfig(**mr_node),
            market_ctx=market_ctx,
        )

    if kind == "bottomup_timing":
        tcfg = timing_config_from_yaml_node(params["timing"])
        m4_cfg = m4_config_from_yaml(params["m4"])
        return BottomupTimingStrategy(
            loader=loader, market=market,
            universe_codes=universe["code"].tolist(),
            timing_cfg=tcfg,
            weights=FactorWeights(**params["weights"]),
            regime_benchmark_symbol=str(params["benchmark"]),
            m4_cfg=m4_cfg,
            market_ctx=market_ctx,
        )
    raise ValueError(f"未注册策略 kind: {kind}")


def _write_json(path: Path, obj) -> None:
    import json
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _benchmark_report_label(benchmark_symbol: str) -> str:
    s = str(benchmark_symbol)
    if s.upper() == "HSCHK100":
        return "HSCHK100 同期"
    if s in ("sh000300",):
        return "沪深300 同期"
    return f"{s} 同期"


def write_report(out_dir: Path, strategy_name: str, args, metrics, admission_pass, fails, benchmark_label: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append("=" * 78)
    lines.append(f"  回测报告  策略: {strategy_name}  {args.start} -> {args.end}")
    lines.append("=" * 78)
    lines.append("")
    lines.append("【收益与风险】")
    lines.append(f"  总收益:        {metrics.total_return*100:>+8.2f}%")
    lines.append(f"  年化收益:      {metrics.annual_return*100:>+8.2f}%")
    lines.append(f"  年化波动:      {metrics.annual_volatility*100:>8.2f}%")
    lines.append(f"  Sharpe:        {metrics.sharpe_ratio:>+8.2f}")
    lines.append(f"  Sortino:       {metrics.sortino_ratio:>+8.2f}  (仅惩罚下行波动)")
    lines.append(f"  最大回撤:      {metrics.max_drawdown*100:>+8.2f}%")
    lines.append(f"  Calmar:        {metrics.calmar_ratio:>+8.2f}")
    lines.append("")
    lines.append("【交易统计】")
    lines.append(f"  交易笔数:      {metrics.n_trades}")
    lines.append(f"  胜率:          {metrics.win_rate*100:>8.2f}%")
    lines.append(f"  平均盈利:      {metrics.avg_win_pct*100:>+8.2f}%")
    lines.append(f"  平均亏损:      {metrics.avg_loss_pct*100:>+8.2f}%")
    lines.append(f"  盈亏比:        1:{metrics.win_loss_ratio:.2f}")
    lines.append(f"  平均持有天数:  {metrics.avg_hold_days:>8.1f}")
    lines.append("")
    lines.append("【基准对比】")
    lines.append(f"  HS300 同期:    {metrics.benchmark_total_return*100:>+8.2f}%")
    lines.append(f"  超额收益:      {metrics.excess_return*100:>+8.2f}%")
    lines.append("")
    lines.append("【准入判定】")
    if admission_pass:
        lines.append("  >>>>>>  PASS  <<<<<<   策略可进入实盘 daily_run rotation")
    else:
        lines.append("  >>>>>>  FAIL  <<<<<<   禁止上实盘, 原因:")
        for f in fails:
            lines.append(f"    - {f}")
    lines.append("")
    report = "\n".join(lines)
    print(report)
    (out_dir / "report.txt").write_text(report, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "回测主入口 (Phase 1b CLI 主索引翻转后).\n"
            "  新用法: --strategy equity_momentum   # 自动从 deployments 推导 market\n"
            "  旧用法: --strategy bottomup_timing --market a_share  # 仍兼容"
        ),
    )
    parser.add_argument("--strategy", default="equity_momentum",
                        help="策略名 (equity_momentum / equity_hk_momentum) 或工厂 kind (bottomup_timing / mean_reversion)")
    parser.add_argument("--market", default=None,
                        choices=["a_share", "hk_share", "us_share"],
                        help="可选；策略只部署到单一市场时自动推导")
    parser.add_argument("--start", default="2024-04-01")
    parser.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--capital", type=float, default=None,
                        help="初始资金, 默认走 config.yaml")
    parser.add_argument("--refresh-days", type=int, default=999,
                        help="cache 刷新天数; 回测默认 999 (永远用旧 cache, 避免被限流)")
    args = parser.parse_args()

    cfg = load_config()

    # Phase 1b: --strategy 主索引解析
    resolved_market, kind, strategy_name = resolve_strategy(cfg, args.strategy, args.market)
    args.market = resolved_market
    args.kind = kind
    args.strategy_name = strategy_name      # 显示用；None 表示走 kind 兼容模式
    hsi = cfg.get("data", "hang_seng_indexes", default=None) or {}
    us_mkt = cfg.get("data", "us_market", default=None) or {}
    # 预读 deployment 拿到 universe 名，影响 us_share 多 universe (nasdaq100 / sp500) 路径选择
    _deps_for_uni = cfg.get("deployments") or {}
    _market_cfg_for_uni = ((_deps_for_uni.get(args.strategy_name) or {}).get(args.market)
                           if args.strategy_name else None) or cfg.get("markets", args.market) or {}
    loader = DataLoader(
        cfg.cache_dir,
        refresh_days=args.refresh_days,
        price_adjust=cfg.get("data", "price_adjust", default="qfq"),
        hang_seng_indexes=hsi,
        us_market=us_mkt,
        us_universe=_market_cfg_for_uni.get("universe"),
    )
    bt_cfg = cfg.get("backtest") or {}
    # Phase 1-B: 优先用 deployments[strategy_name][market] 精确 entry；让一市多策略时也能选对策略的 benchmark/hedge
    _deps = cfg.get("deployments") or {}
    market_cfg_bt = ((_deps.get(args.strategy_name) or {}).get(args.market)
                     if args.strategy_name else None) or cfg.get("markets", args.market) or {}
    benchmark_symbol = market_cfg_bt.get("benchmark") or bt_cfg.get("benchmark_symbol", "sh000300")
    benchmark_label = _benchmark_report_label(benchmark_symbol)

    strategy = build_strategy(args.kind, loader, cfg, args.market, strategy_name=args.strategy_name)
    market_ctx = load_market_context(cfg, args.market)

    # L3：基准对冲 overlay（从 markets.<market>.hedge 读，关闭默认）
    hedge_cfg = (market_cfg_bt.get("hedge") or {}) if isinstance(market_cfg_bt, dict) else {}
    # Phase 2b: stamp_tax 优先从 markets/<m>.yaml.fees 读，回退到入口 backtest.stamp_tax
    market_fees = (market_cfg_bt.get("fees") or {}) if isinstance(market_cfg_bt, dict) else {}
    stamp_tax = market_fees.get("stamp_tax", bt_cfg.get("stamp_tax", 0.001))
    bt = Backtester(
        loader=loader,
        initial_capital=args.capital or bt_cfg.get("initial_capital", 1_000_000),
        max_positions=cfg.get("strategy", "position_max_count", default=10),
        single_position_pct=cfg.get("strategy", "single_position_pct_max", default=0.15),
        commission=bt_cfg.get("commission", 0.0003),
        stamp_tax=stamp_tax,
        slippage=bt_cfg.get("slippage", 0.001),
        cash_buffer_pct=bt_cfg.get("cash_buffer_pct", 0.05),
        benchmark_hedge_ratio=float(hedge_cfg.get("ratio", 0.0)),
        benchmark_hedge_ma_days=int(hedge_cfg.get("ma_days", 200)),
        benchmark_hedge_borrow_cost=float(hedge_cfg.get("borrow_cost", 0.03)),
    )

    # ---------- 固定输出目录（同策略+市场+区间覆盖写入，不产生历史 run_id 子目录） ----------
    out_root = Path(bt_cfg.get("output_dir", "./data/backtest"))
    if not out_root.is_absolute():
        # scripts/backtest/backtest.py → parents[2] 是 repo root
        out_root = Path(__file__).resolve().parents[2] / out_root
    out_dir = out_root / f"{args.strategy}_{args.market}_{args.start}_{args.end}"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---------- Universe 过滤样例输出（无黑盒；按 start 截断，避免未来信息） ----------
    # Phase 2b: 由 market_ctx.universe_filter 驱动，而非字符串硬比 a_share
    if market_ctx.universe_filter == "a_share":
        try:
            market_cfg = cfg.get("markets", args.market)
            universe = loader.get_universe(args.market, market_cfg["universe"])
            uf = UniverseFilter(loader, UniverseFilterConfig())
            filt_df, stats = uf.filter_a_share(universe[["code", "name"]], args.start)
            filt_df.to_csv(out_dir / "universe_filtered_sample.csv", index=False, encoding="utf-8-sig")
            _write_json(out_dir / "universe_filter_stats_sample.json", stats)
        except Exception as e:
            _write_json(out_dir / "universe_filter_stats_sample.json", {"error": str(e)})

    _label = args.strategy if args.strategy_name else f"{args.kind}({args.market})"
    print(f"启动回测: {_label}  {args.start} -> {args.end}", flush=True)
    print(f"  初始资金 {bt.initial_capital:,.0f}, 最多持仓 {bt.max_positions}, 单只 {bt.single_position_pct*100:.0f}%", flush=True)
    print(f"  手续费 {bt.commission*100:.2f}%, 印花税 {bt.stamp_tax*100:.2f}%, 滑点 {bt.slippage*100:.2f}%", flush=True)
    print()

    diagnostics = BacktestDiagnostics()
    result = bt.run(
        strategy, args.start, args.end, market=args.market,
        benchmark_symbol=benchmark_symbol,
        diagnostics=diagnostics,
    )

    metrics = compute_metrics(result.equity_curve, result.closed_trades, result.benchmark_curve)
    adm = bt_cfg.get("admission", {}) or {}
    admission_pass, fails = check_admission(
        metrics,
        min_sharpe=adm.get("min_sharpe", 0.5),
        max_drawdown=adm.get("max_drawdown", 0.25),
        min_win_rate=adm.get("min_win_rate", 0.40),
        min_sortino=adm.get("min_sortino", 0.0),
    )

    # CSV 输出
    pd.concat([result.equity_curve, result.benchmark_curve], axis=1).to_csv(out_dir / "equity.csv")
    result.daily_positions.to_csv(out_dir / "positions.csv")
    if result.closed_trades:
        trades_df = pd.DataFrame([
            {"symbol": t.symbol, "entry_date": t.entry_date, "entry_price": t.entry_price,
             "exit_date": t.exit_date, "exit_price": t.exit_price, "size": t.size,
             "pnl": t.pnl, "pnl_pct": t.pnl_pct, "hold_days": t.hold_days,
             "exit_reason": t.exit_reason}
            for t in result.closed_trades
        ])
        trades_df.to_csv(out_dir / "trades.csv", index=False)

    # ---------- M0: 选股排序 / 退出决策 可追溯输出 ----------
    entry_cols = [
        "screen_date", "factor_rank", "symbol", "factor_score", "signal_entry_price",
        "stop_loss", "take_profit", "timing_reason", "already_held", "queued_for_buy",
    ]
    if diagnostics.entry_rows:
        ent = pd.DataFrame(diagnostics.entry_rows)
        ent.to_csv(out_dir / "entry_candidates.csv", index=False, encoding="utf-8-sig")
        ent[["screen_date", "factor_rank", "symbol", "factor_score"]].rename(
            columns={"factor_rank": "rank", "factor_score": "score"},
        ).to_csv(out_dir / "ranking.csv", index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame(columns=entry_cols).to_csv(
            out_dir / "entry_candidates.csv", index=False, encoding="utf-8-sig",
        )
        pd.DataFrame(columns=["screen_date", "rank", "symbol", "score"]).to_csv(
            out_dir / "ranking.csv", index=False, encoding="utf-8-sig",
        )

    exit_cols = ["decision_date", "planned_exec_date", "symbol", "reason", "event", "exit_layer"]
    if diagnostics.exit_rows:
        pd.DataFrame(diagnostics.exit_rows).to_csv(
            out_dir / "exit_events.csv", index=False, encoding="utf-8-sig",
        )
    else:
        pd.DataFrame(columns=exit_cols).to_csv(
            out_dir / "exit_events.csv", index=False, encoding="utf-8-sig",
        )

    closed_by_reason = Counter(t.exit_reason for t in result.closed_trades)
    events_by_reason = Counter(r.get("reason", "") for r in diagnostics.exit_rows)
    closed_by_layer = Counter(
        exit_layer_from_reason(t.exit_reason) for t in result.closed_trades
    )
    events_by_layer = Counter(
        (r.get("exit_layer") or exit_layer_from_reason(r.get("reason", "")))
        for r in diagnostics.exit_rows
    )
    _write_json(
        out_dir / "exit_reason_summary.json",
        {
            "closed_trades_by_exit_reason": dict(closed_by_reason),
            "exit_events_by_reason": dict(events_by_reason),
            "closed_trades_by_exit_layer": {k: v for k, v in closed_by_layer.items() if k},
            "exit_events_by_exit_layer": {k: v for k, v in events_by_layer.items() if k},
            "n_exit_events": len(diagnostics.exit_rows),
            "n_closed_trades": len(result.closed_trades),
        },
    )

    write_report(out_dir, args.strategy, args, metrics, admission_pass, fails, benchmark_label)
    _write_json(
        out_dir / "metrics.json",
        {
            "strategy": args.strategy,
            "strategy_kind": args.kind,
            "strategy_name": args.strategy_name,
            "market": args.market,
            "benchmark_symbol": benchmark_symbol,
            "start": args.start,
            "end": args.end,
            "price_adjust": cfg.get("data", "price_adjust", default="qfq"),
            "metrics": metrics.__dict__,
            "admission_pass": admission_pass,
            "fails": fails,
        },
    )
    print(f"\n输出目录: {out_dir}")


if __name__ == "__main__":
    main()
