"""
回测主入口.

用法:
  python scripts/backtest.py                    # 默认: bottomup_timing 策略, 全段, HS300
  python scripts/backtest.py --start 2025-01-01 --end 2026-04-27
  python scripts/backtest.py --capital 500000

输出:
  data/backtest/<strategy>_<start>_<end>/
    equity.csv         每日净值 + 基准
    trades.csv         所有交易明细
    positions.csv      每日持仓数 / 市值 / 现金
    report.txt         指标 + 准入判定
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from quant_system.bottomup.factors import FactorWeights
from quant_system.config import load_config
from quant_system.data.loader import DataLoader
from quant_system.engine.backtest import Backtester
from quant_system.engine.metrics import check_admission, compute_metrics
from quant_system.engine.strategy import BottomupTimingStrategy
from quant_system.timing.signals import TimingConfig


def build_strategy(name: str, loader: DataLoader, cfg, market: str) -> object:
    """策略工厂. 后续新策略在这里注册."""
    market_cfg = cfg.get("markets", market)
    universe = loader.get_universe(market, market_cfg["universe"])
    if name == "bottomup_timing":
        w_cfg = cfg.get("factors", "weights", default={}) or {}
        return BottomupTimingStrategy(
            loader=loader, market=market,
            universe_codes=universe["code"].tolist(),
            timing_cfg=TimingConfig(),
            weights=FactorWeights(**w_cfg),
        )
    raise ValueError(f"未注册策略: {name}")


def write_report(out_dir: Path, strategy_name: str, args, metrics, admission_pass, fails):
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", default="bottomup_timing")
    parser.add_argument("--market", default="a_share", choices=["a_share", "hk_share"])
    parser.add_argument("--start", default="2024-04-01")
    parser.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--capital", type=float, default=None,
                        help="初始资金, 默认走 config.yaml")
    parser.add_argument("--refresh-days", type=int, default=999,
                        help="cache 刷新天数; 回测默认 999 (永远用旧 cache, 避免被限流)")
    args = parser.parse_args()

    cfg = load_config()
    loader = DataLoader(cfg.cache_dir, refresh_days=args.refresh_days)
    bt_cfg = cfg.get("backtest") or {}

    strategy = build_strategy(args.strategy, loader, cfg, args.market)

    bt = Backtester(
        loader=loader,
        initial_capital=args.capital or bt_cfg.get("initial_capital", 1_000_000),
        max_positions=cfg.get("strategy", "position_max_count", default=10),
        single_position_pct=cfg.get("strategy", "single_position_pct_max", default=0.15),
        commission=bt_cfg.get("commission", 0.0003),
        stamp_tax=bt_cfg.get("stamp_tax", 0.001),
        slippage=bt_cfg.get("slippage", 0.001),
        cash_buffer_pct=bt_cfg.get("cash_buffer_pct", 0.05),
    )

    print(f"启动回测: {args.strategy}  {args.start} -> {args.end}", flush=True)
    print(f"  初始资金 {bt.initial_capital:,.0f}, 最多持仓 {bt.max_positions}, 单只 {bt.single_position_pct*100:.0f}%", flush=True)
    print(f"  手续费 {bt.commission*100:.2f}%, 印花税 {bt.stamp_tax*100:.2f}%, 滑点 {bt.slippage*100:.2f}%", flush=True)
    print()

    result = bt.run(
        strategy, args.start, args.end, market=args.market,
        benchmark_symbol=bt_cfg.get("benchmark_symbol", "sh000300"),
    )

    metrics = compute_metrics(result.equity_curve, result.closed_trades, result.benchmark_curve)
    adm = bt_cfg.get("admission", {}) or {}
    admission_pass, fails = check_admission(
        metrics,
        min_sharpe=adm.get("min_sharpe", 0.5),
        max_drawdown=adm.get("max_drawdown", 0.25),
        min_win_rate=adm.get("min_win_rate", 0.40),
    )

    out_root = Path(bt_cfg.get("output_dir", "./data/backtest"))
    if not out_root.is_absolute():
        out_root = Path(__file__).resolve().parents[1] / out_root
    out_dir = out_root / f"{args.strategy}_{args.start}_{args.end}"
    out_dir.mkdir(parents=True, exist_ok=True)

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

    write_report(out_dir, args.strategy, args, metrics, admission_pass, fails)
    print(f"\n输出目录: {out_dir}")


if __name__ == "__main__":
    main()
