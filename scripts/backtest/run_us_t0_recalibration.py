"""US equity_us_momentum / equity_sp500_momentum 双窗口 T+0 vs T+1 对比.

Spec: docs/specs/market_settlement_t0_t1.md
背景: HK 跑通后 ([[hk_t0_recalibration_2026-06]] +0.06 Sharpe), 验证 US 是否同款.
当前 [[sp500_negative_2026-05]] base -0.18 Sharpe / [[three_universe_2026-05]] NASDAQ100 -0.05 Sharpe.

用法:
  venv/bin/python3 scripts/backtest/run_us_t0_recalibration.py
输出:
  data/backtest/_us_settlement_recal/results.json + summary.md
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
MARKET = "us_share"
# 两组策略 (nasdaq100 / sp500) 共享 market=us_share
RUNS = [
    {"strategy_name": "equity_us_momentum", "universe_override": "nasdaq100"},
    {"strategy_name": "equity_sp500_momentum", "universe_override": "sp500"},
]


def _build_strategy(cfg, loader, market_ctx, strategy_name):
    deps = cfg.get("deployments") or {}
    dep_entry = (deps.get(strategy_name) or {}).get(MARKET) or {}
    universe = loader.get_universe(MARKET, dep_entry.get("universe"))
    params = resolve_strategy_params(cfg, MARKET, strategy_name=strategy_name)
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


def _run(cfg, loader_factory, market_ctx, strategy_name, start, end, settlement_mode):
    deps = cfg.get("deployments") or {}
    dep_entry = (deps.get(strategy_name) or {}).get(MARKET) or {}
    bench = dep_entry.get("benchmark") or cfg.get("backtest", "benchmark_symbol", default="NDX")
    hedge_cfg = (dep_entry.get("hedge") or {})
    fees = (dep_entry.get("fees") or {})
    bt_cfg = cfg.get("backtest") or {}

    loader = loader_factory(dep_entry.get("universe"))

    bt = Backtester(
        loader=loader,
        initial_capital=bt_cfg.get("initial_capital", 1_000_000),
        max_positions=cfg.get("strategy", "position_max_count", default=10),
        single_position_pct=cfg.get("strategy", "single_position_pct_max", default=0.15),
        commission=bt_cfg.get("commission", 0.0003),
        stamp_tax=fees.get("stamp_tax", bt_cfg.get("stamp_tax", 0.0)),
        slippage=bt_cfg.get("slippage", 0.001),
        cash_buffer_pct=bt_cfg.get("cash_buffer_pct", 0.05),
        benchmark_hedge_ratio=float(hedge_cfg.get("ratio", 0.0)),
        benchmark_hedge_ma_days=int(hedge_cfg.get("ma_days", 200)),
        benchmark_hedge_borrow_cost=float(hedge_cfg.get("borrow_cost", 0.03)),
        settlement_mode=settlement_mode,
    )
    strategy = _build_strategy(cfg, loader, market_ctx, strategy_name)
    diagnostics = BacktestDiagnostics()
    t0 = time.time()
    result = bt.run(strategy, start, end, market=MARKET, benchmark_symbol=str(bench),
                    verbose=False, diagnostics=diagnostics)
    elapsed = time.time() - t0
    m = compute_metrics(result.equity_curve, result.closed_trades, result.benchmark_curve)
    return {
        "strategy": strategy_name,
        "settlement_mode": settlement_mode,
        "start": start, "end": end,
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
    market_ctx = load_market_context(cfg, MARKET)

    def loader_factory(universe_override):
        return DataLoader(
            cfg.cache_dir,
            refresh_days=999,
            price_adjust=cfg.get("data", "price_adjust", default="qfq"),
            hang_seng_indexes=hsi_cfg,
            us_market=us_cfg,
            us_universe=universe_override,
        )

    out_dir = ROOT / "data/backtest/_us_settlement_recal"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for run in RUNS:
        sname = run["strategy_name"]
        for tag, start, end in WINDOWS:
            for mode in MODES:
                label = f"{sname}_{tag}_{mode}"
                print(f"[run] {label}  {start} → {end}", flush=True)
                try:
                    row = _run(cfg, loader_factory, market_ctx, sname,
                               start, end, settlement_mode=mode)
                    row["window"] = tag
                    results.append(row)
                    print(f"   Sharpe {row['sharpe']:+.3f}  Ret {row['total_return']*100:+.2f}%  "
                          f"DD {row['max_drawdown']*100:+.2f}%  WR {row['win_rate']*100:.1f}%  "
                          f"N={row['n_trades']}  [{row['elapsed_s']}s]")
                except Exception as e:
                    print(f"   FAILED: {e}")
                    results.append({"strategy": sname, "window": tag,
                                    "settlement_mode": mode, "error": str(e)})

    (out_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                          encoding="utf-8")

    # 写 summary
    lines = ["# US equity (NASDAQ100 + SP500) T+0 vs T+1 双窗口对比", ""]
    for sname in [r["strategy_name"] for r in RUNS]:
        lines += [f"## {sname}", "",
                  "| window | mode | Sharpe | Sortino | Ann | Ret | DD | WR | N | avgHold |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        sub = [r for r in results if r.get("strategy") == sname and "error" not in r]
        for r in sub:
            lines.append(
                f"| {r['window']} | {r['settlement_mode']} | "
                f"{r['sharpe']:+.3f} | {r['sortino']:+.3f} | "
                f"{r['annual_return']*100:+.2f}% | {r['total_return']*100:+.2f}% | "
                f"{r['max_drawdown']*100:+.2f}% | {r['win_rate']*100:.1f}% | "
                f"{r['n_trades']} | {r['avg_hold_days']:.1f} |"
            )
        # Δ
        lines += ["", "### Δ (T+0 − T+1)", "",
                  "| window | ΔSharpe | ΔSortino | ΔRet | ΔDD | ΔWR | ΔN |",
                  "|---|---|---|---|---|---|---|"]
        by_win = {}
        for r in sub:
            by_win.setdefault(r["window"], {})[r["settlement_mode"]] = r
        for win in [w[0] for w in WINDOWS]:
            a = by_win.get(win, {}).get("t+0"); b = by_win.get(win, {}).get("t+1")
            if a and b:
                lines.append(
                    f"| {win} | {a['sharpe']-b['sharpe']:+.3f} | {a['sortino']-b['sortino']:+.3f} | "
                    f"{(a['total_return']-b['total_return'])*100:+.2f}pp | "
                    f"{(a['max_drawdown']-b['max_drawdown'])*100:+.2f}pp | "
                    f"{(a['win_rate']-b['win_rate'])*100:+.2f}pp | "
                    f"{a['n_trades']-b['n_trades']:+d} |"
                )
        lines.append("")
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n输出: {out_dir}/summary.md")


if __name__ == "__main__":
    main()
