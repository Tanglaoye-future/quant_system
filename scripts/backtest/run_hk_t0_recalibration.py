"""HK equity_hk_momentum 双窗口 T+0 vs T+1 对比.

Spec: docs/specs/market_settlement_t0_t1.md
背景：当前 backtester 全市场用 A 股 T+1 假设，HK 实际是 T+0。
本脚本一次跑 4y / 8y 双窗口 × {t+1 baseline, t+0 new} 4 组对比。

用法：
  venv/bin/python3 scripts/backtest/run_hk_t0_recalibration.py
输出：
  data/backtest/_hk_settlement_recal/results.json
  data/backtest/_hk_settlement_recal/summary.md
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_system.config import load_config, resolve_strategy_params
from quant_system.market import load_market_context
from quant_system.strategies.equity_factor.bottomup.factors import FactorWeights
from quant_system.strategies.equity_factor.bottomup.portfolio import m4_config_from_yaml
from quant_system.strategies.equity_factor.data.loader import DataLoader
from quant_system.strategies.equity_factor.engine.backtest import BacktestDiagnostics, Backtester
from quant_system.strategies.equity_factor.engine.metrics import compute_metrics
from quant_system.strategies.equity_factor.engine.strategy import BottomupTimingStrategy
from quant_system.strategies.equity_factor.timing.signals import timing_config_from_yaml_node


WINDOWS = [
    ("4y", "2022-01-01", "2026-05-25"),
    ("8y", "2018-01-01", "2026-05-25"),
]
MODES = ["t+1", "t+0"]
MARKET = "hk_share"
STRATEGY_NAME = "equity_hk_momentum"


def _build_strategy(cfg, loader: DataLoader, market_ctx):
    deps = cfg.get("deployments") or {}
    dep_entry = (deps.get(STRATEGY_NAME) or {}).get(MARKET) or {}
    universe = loader.get_universe(MARKET, dep_entry["universe"])
    params = resolve_strategy_params(cfg, MARKET, strategy_name=STRATEGY_NAME)
    tcfg = timing_config_from_yaml_node(params["timing"])
    m4_cfg = m4_config_from_yaml(params["m4"])
    return BottomupTimingStrategy(
        loader=loader, market=MARKET,
        universe_codes=universe["code"].tolist(),
        timing_cfg=tcfg,
        weights=FactorWeights(**params["weights"]),
        regime_benchmark_symbol=str(params["benchmark"]),
        m4_cfg=m4_cfg,
        market_ctx=market_ctx,
    )


def _run(cfg, loader, market_ctx, start, end, settlement_mode: str):
    deps = cfg.get("deployments") or {}
    dep_entry = (deps.get(STRATEGY_NAME) or {}).get(MARKET) or {}
    bench = dep_entry.get("benchmark") or cfg.get("backtest", "benchmark_symbol", default="HSCHK100")
    hedge_cfg = (dep_entry.get("hedge") or {})
    fees = (dep_entry.get("fees") or {})
    bt_cfg = cfg.get("backtest") or {}

    bt = Backtester(
        loader=loader,
        initial_capital=bt_cfg.get("initial_capital", 1_000_000),
        max_positions=cfg.get("strategy", "position_max_count", default=10),
        single_position_pct=cfg.get("strategy", "single_position_pct_max", default=0.20),
        commission=bt_cfg.get("commission", 0.0003),
        stamp_tax=fees.get("stamp_tax", bt_cfg.get("stamp_tax", 0.0)),
        slippage=bt_cfg.get("slippage", 0.001),
        cash_buffer_pct=bt_cfg.get("cash_buffer_pct", 0.05),
        benchmark_hedge_ratio=float(hedge_cfg.get("ratio", 0.0)),
        benchmark_hedge_ma_days=int(hedge_cfg.get("ma_days", 200)),
        benchmark_hedge_borrow_cost=float(hedge_cfg.get("borrow_cost", 0.03)),
        settlement_mode=settlement_mode,
    )
    strategy = _build_strategy(cfg, loader, market_ctx)
    diagnostics = BacktestDiagnostics()
    t0 = time.time()
    result = bt.run(strategy, start, end, market=MARKET, benchmark_symbol=str(bench),
                    verbose=False, diagnostics=diagnostics)
    elapsed = time.time() - t0
    m = compute_metrics(result.equity_curve, result.closed_trades, result.benchmark_curve)
    return {
        "settlement_mode": settlement_mode,
        "start": start,
        "end": end,
        "sharpe": float(m.sharpe_ratio),
        "sortino": float(m.sortino_ratio),
        "annual_return": float(m.annual_return),
        "total_return": float(m.total_return),
        "annual_volatility": float(m.annual_volatility),
        "max_drawdown": float(m.max_drawdown),
        "calmar": float(m.calmar_ratio),
        "win_rate": float(m.win_rate),
        "n_trades": int(m.n_trades),
        "avg_hold_days": float(m.avg_hold_days),
        "excess_return": float(m.excess_return),
        "elapsed_s": round(elapsed, 1),
    }


def main():
    cfg = load_config()
    hsi_cfg = cfg.get("data", "hang_seng_indexes", default=None) or {}
    us_cfg = cfg.get("data", "us_market", default=None) or {}
    deps = cfg.get("deployments") or {}
    dep_entry = (deps.get(STRATEGY_NAME) or {}).get(MARKET) or {}
    loader = DataLoader(
        cfg.cache_dir,
        refresh_days=999,
        price_adjust=cfg.get("data", "price_adjust", default="qfq"),
        hang_seng_indexes=hsi_cfg,
        us_market=us_cfg,
        us_universe=dep_entry.get("universe"),
    )
    market_ctx = load_market_context(cfg, MARKET)

    out_dir = ROOT / "data/backtest/_hk_settlement_recal"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for tag, start, end in WINDOWS:
        for mode in MODES:
            label = f"{tag}_{mode}"
            print(f"[run] {label}  {start} → {end}", flush=True)
            row = _run(cfg, loader, market_ctx, start, end, settlement_mode=mode)
            row["window"] = tag
            results.append(row)
            print(f"   Sharpe {row['sharpe']:+.3f}  Ret {row['total_return']*100:+.2f}%  "
                  f"DD {row['max_drawdown']*100:+.2f}%  WR {row['win_rate']*100:.1f}%  "
                  f"N={row['n_trades']}  [{row['elapsed_s']}s]")

    (out_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                          encoding="utf-8")

    # 写 summary
    lines = ["# HK equity_hk_momentum T+0 vs T+1 双窗口对比",
             "",
             "| window | mode | Sharpe | Sortino | Ann | Ret | DD | WR | N | avgHold |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(
            f"| {r['window']} | {r['settlement_mode']} | "
            f"{r['sharpe']:+.3f} | {r['sortino']:+.3f} | "
            f"{r['annual_return']*100:+.2f}% | {r['total_return']*100:+.2f}% | "
            f"{r['max_drawdown']*100:+.2f}% | {r['win_rate']*100:.1f}% | "
            f"{r['n_trades']} | {r['avg_hold_days']:.1f} |"
        )
    # Δ rows
    by_win = {r["window"]: {} for r in results}
    for r in results:
        by_win[r["window"]][r["settlement_mode"]] = r
    lines += ["", "## Δ (T+0 − T+1)", "", "| window | ΔSharpe | ΔSortino | ΔRet | ΔDD | ΔWR | ΔN |",
              "|---|---|---|---|---|---|---|"]
    for win in [w[0] for w in WINDOWS]:
        a = by_win[win].get("t+0"); b = by_win[win].get("t+1")
        if a and b:
            lines.append(
                f"| {win} | {a['sharpe']-b['sharpe']:+.3f} | {a['sortino']-b['sortino']:+.3f} | "
                f"{(a['total_return']-b['total_return'])*100:+.2f}pp | "
                f"{(a['max_drawdown']-b['max_drawdown'])*100:+.2f}pp | "
                f"{(a['win_rate']-b['win_rate'])*100:+.2f}pp | "
                f"{a['n_trades']-b['n_trades']:+d} |"
            )
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n输出: {out_dir}/summary.md")


if __name__ == "__main__":
    main()
