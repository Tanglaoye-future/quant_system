#!/usr/bin/env python3
"""
A1' HK 南向 gate backtest sweep.

driver: 预检查 PROCEED — 10d 累计 >200 亿阈值下 mean pnl_pct +37%, win rate +4.9pp.
       见 [[a1_northbound_dead_southbound_alive_2026-06]]

cases:
  A1P-base     : control = 现有 yaml (gate disabled, widen 仍开)
  A1P-gate-10d200: gate enabled (lookback=10, threshold=200 亿)

4y 窗口 (2022-2026-05). winner 上 8y verify, 双窗口同向才落 yaml.

注意: yaml 当前已开 m3_southbound_widen_enabled, gate 与 widen 互补
     (widen = 强买日放宽入场带, gate = 弱买日拒入场). 两者可独立或叠加.
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_system.config import Config, load_config
from quant_system.market import load_market_context
from quant_system.strategies.equity_factor.bottomup.factors import FactorWeights
from quant_system.strategies.equity_factor.bottomup.portfolio import m4_config_from_yaml
from quant_system.strategies.equity_factor.data.loader import DataLoader
from quant_system.strategies.equity_factor.engine.backtest import (
    BacktestDiagnostics,
    Backtester,
)
from quant_system.strategies.equity_factor.engine.metrics import compute_metrics
from quant_system.strategies.equity_factor.engine.strategy import BottomupTimingStrategy
from quant_system.strategies.equity_factor.timing.signals import timing_config_from_yaml_node

START = "2022-01-01"
END = "2026-05-25"
MARKET = "hk_share"

# (tag, timing_override) — 只动 gate 配置
EXPERIMENTS: list[tuple[str, dict]] = [
    ("A1P-base", {}),
    ("A1P-gate-10d200", {
        "m3_southbound_gate_enabled": True,
        "m3_southbound_gate_lookback_days": 10,
        "m3_southbound_gate_threshold_yi": 200.0,
    }),
]


def run_one(tag: str, timing_override: dict, base_raw: dict, market: str) -> dict:
    cfg_dict = copy.deepcopy(base_raw)
    market_cfg = cfg_dict.setdefault("markets", {}).setdefault(market, {})

    mkt_timing = market_cfg.setdefault("timing", {})
    mkt_timing.update(timing_override)

    cfg = Config(raw=cfg_dict)
    market_cfg_bt = cfg.get("markets", market) or {}
    universe = market_cfg_bt.get("universe", "hschk100")
    data_cfg = cfg.get("data", default={}) or {}
    loader = DataLoader(
        cfg.cache_dir,
        refresh_days=999,
        price_adjust=data_cfg.get("price_adjust", "qfq"),
        hang_seng_indexes=data_cfg.get("hang_seng_indexes"),
        us_market=data_cfg.get("us_market"),
    )

    global_timing = cfg.get("strategy", "timing", default=None) or {}
    global_weights = cfg.get("factors", "weights", default={}) or {}
    m4_cfg = m4_config_from_yaml(cfg.get("factors", "m4", default=None))
    bench = market_cfg_bt.get("benchmark") or cfg.get(
        "backtest", "benchmark_symbol", default="HSCHK100"
    )
    merged_timing = {**global_timing, **mkt_timing}
    merged_weights = {**global_weights, **(market_cfg_bt.get("factors") or {}).get("weights", {})}

    tcfg = timing_config_from_yaml_node(merged_timing)
    uni = loader.get_universe(market, universe)
    market_ctx = load_market_context(cfg, market)
    strategy = BottomupTimingStrategy(
        loader=loader, market=market, universe_codes=uni["code"].tolist(),
        timing_cfg=tcfg, weights=FactorWeights(**merged_weights),
        regime_benchmark_symbol=str(bench), m4_cfg=m4_cfg,
        market_ctx=market_ctx,
    )

    out_dir = ROOT / f"data/backtest/_a1p_{tag}"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bt_cfg = cfg.get("backtest") or {}
    hedge_cfg = market_cfg_bt.get("hedge") or {}
    market_fees = (market_cfg_bt.get("fees") or {}) if isinstance(market_cfg_bt, dict) else {}
    stamp_tax = market_fees.get("stamp_tax", bt_cfg.get("stamp_tax", 0.0013))   # HK 0.13%
    bt = Backtester(
        loader=loader,
        initial_capital=bt_cfg.get("initial_capital", 1_000_000),
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
    diagnostics = BacktestDiagnostics()
    t0 = time.time()
    result = bt.run(strategy, START, END, market=market,
                    benchmark_symbol=str(bench), diagnostics=diagnostics)
    elapsed = time.time() - t0
    m = compute_metrics(result.equity_curve, result.closed_trades, result.benchmark_curve)
    out = {
        "tag": tag,
        "timing_override": timing_override,
        "sharpe": float(m.sharpe_ratio),
        "total_return": float(m.total_return),
        "max_drawdown": float(m.max_drawdown),
        "win_rate": float(m.win_rate),
        "n_trades": int(m.n_trades),
        "annual_return": float(m.annual_return),
        "elapsed_s": round(elapsed, 1),
    }
    print(
        f"[{tag}] sharpe={out['sharpe']:.3f} ann={out['annual_return']*100:+.1f}% "
        f"ret={out['total_return']*100:+.1f}% dd={out['max_drawdown']*100:.1f}% "
        f"win={out['win_rate']*100:.1f}% trades={out['n_trades']} elapsed={elapsed:.0f}s",
        flush=True,
    )
    return out


def main():
    print(f"=== A1' HK 南向 gate sweep ({len(EXPERIMENTS)} cases) ===")
    print(f"  market: {MARKET}  window: {START} → {END}")
    for t, ov in EXPERIMENTS:
        print(f"  - {t:<22} timing_override={ov}")
    print()

    base_cfg = load_config()
    base_raw = base_cfg.raw
    results = []
    for tag, t_ov in EXPERIMENTS:
        try:
            results.append(run_one(tag, t_ov, base_raw, MARKET))
        except Exception as e:
            print(f"[{tag}] ERROR: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc()

    results.sort(key=lambda r: r["sharpe"], reverse=True)
    out_md = ROOT / "data/backtest/a1prime_southbound_gate_summary.md"
    lines = [
        "# A1' HK 南向 gate sweep",
        "",
        f"市场: {MARKET}  窗口: {START} → {END}",
        "",
        "| rank | tag | Sharpe | 年化 | 收益 | DD | 胜率 | 笔数 | Δ Sharpe |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    base_sh = next((r["sharpe"] for r in results if r["tag"] == "A1P-base"), None)
    for i, r in enumerate(results, 1):
        delta = (r["sharpe"] - base_sh) if base_sh is not None else 0.0
        lines.append(
            f"| {i} | {r['tag']} | {r['sharpe']:.3f} | {r['annual_return']*100:+.1f}% | "
            f"{r['total_return']*100:+.1f}% | {r['max_drawdown']*100:.1f}% | "
            f"{r['win_rate']*100:.1f}% | {r['n_trades']} | {delta:+.3f} |"
        )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    out_md.with_suffix(".json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False)
    )
    print(f"\n[A1' sweep] summary → {out_md}", flush=True)


if __name__ == "__main__":
    main()
