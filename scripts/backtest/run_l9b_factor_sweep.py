#!/usr/bin/env python3
"""
equity_factor L9-B：ROIC + 应收账款周转率 YoY 因子层 sweep.

driver: handoff #4 — L9-A 8y Sharpe 0.363 边缘 PASS, 单策略空间还有.
candidate factors:
  - ROIC (投入资本回报率) — 类 ROE 但剥离金融杠杆, akshare A 股全覆盖
  - ar_turnover_yoy (应收账款周转率同比) — 周转率下降 = 应收增速 > 营收 = 造假信号

Baseline (L8D2, sum=0.80):
  pe_inverse 0.15, pb_inverse 0.10, roe 0.20, revenue_growth 0.15,
  momentum_3m 0.20, fcf_yield 0.0, rev_accel 0.0

Cases (单变量 + 联合, 不动 baseline 其他权重):
  L9B-base       : control (= current yaml)
  L9B-roic-10    : +roic 0.10 (sum=0.90)
  L9B-ar-10      : +ar_turnover_yoy 0.10 (sum=0.90)
  L9B-both-05    : +roic 0.05 + ar 0.05 (sum=0.90)

4y 窗口 (2022-01-01 → 2026-05-04), HS300 universe.
winner 上 8y verify, 双窗口同向才落 yaml.

用法:
  python scripts/backtest/run_l9b_factor_sweep.py
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
END = "2026-05-04"
MARKET = "a_share"

# (tag, weights_override) — timing/regime 不动, 只测因子层
EXPERIMENTS: list[tuple[str, dict]] = [
    ("L9B-base", {}),                                    # control
    ("L9B-roic-10", {"roic": 0.10}),
    ("L9B-ar-10", {"ar_turnover_yoy": 0.10}),
    ("L9B-both-05", {"roic": 0.05, "ar_turnover_yoy": 0.05}),
]


def run_one(tag: str, weights_override: dict, base_raw: dict, market: str) -> dict:
    cfg_dict = copy.deepcopy(base_raw)
    market_cfg = cfg_dict.setdefault("markets", {}).setdefault(market, {})

    if weights_override:
        factors_node = market_cfg.setdefault("factors", {})
        weights_node = factors_node.setdefault("weights", {})
        weights_node.update(weights_override)

    cfg = Config(raw=cfg_dict)
    market_cfg_bt = cfg.get("markets", market) or {}
    universe = market_cfg_bt.get("universe", "hs300")
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
    mkt_timing = market_cfg_bt.get("timing") or {}
    m4_cfg = m4_config_from_yaml(cfg.get("factors", "m4", default=None))
    bench = market_cfg_bt.get("benchmark") or cfg.get(
        "backtest", "benchmark_symbol", default="sh000300"
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

    out_dir = ROOT / f"data/backtest/_l9b_{tag}"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bt_cfg = cfg.get("backtest") or {}
    hedge_cfg = market_cfg_bt.get("hedge") or {}
    market_fees = (market_cfg_bt.get("fees") or {}) if isinstance(market_cfg_bt, dict) else {}
    stamp_tax = market_fees.get("stamp_tax", bt_cfg.get("stamp_tax", 0.001))
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
        "weights_override": weights_override,
        "merged_weights": dict(merged_weights),
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
    print(f"=== equity_factor L9-B factor sweep ({len(EXPERIMENTS)} cases) ===")
    print(f"  market: {MARKET}  window: {START} → {END}")
    for t, w in EXPERIMENTS:
        print(f"  - {t:<18} weights_override={w}")
    print()

    base_cfg = load_config()
    base_raw = base_cfg.raw
    results = []
    for tag, w_ov in EXPERIMENTS:
        try:
            results.append(run_one(tag, w_ov, base_raw, MARKET))
        except Exception as e:
            print(f"[{tag}] ERROR: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc()

    # 排序输出
    results.sort(key=lambda r: r["sharpe"], reverse=True)
    out_md = ROOT / "data/backtest/equity_factor_l9b_factor_summary.md"
    lines = [
        "# equity_factor L9-B: ROIC + AR turnover YoY sweep",
        "",
        f"市场: {MARKET}  窗口: {START} → {END}",
        f"baseline = L8D2 (pe 0.15 / pb 0.10 / roe 0.20 / rev_g 0.15 / mom3m 0.20 / fcf 0 / rev_accel 0, sum=0.80)",
        "",
        "| rank | 标签 | Sharpe | 年化 | 收益 | DD | 胜率 | 笔数 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        lines.append(
            f"| {i} | {r['tag']} | {r['sharpe']:.3f} | {r['annual_return']*100:+.1f}% | "
            f"{r['total_return']*100:+.1f}% | {r['max_drawdown']*100:.1f}% | "
            f"{r['win_rate']*100:.1f}% | {r['n_trades']} |"
        )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    out_md.with_suffix(".json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False)
    )
    print(f"\n[L9B sweep] summary → {out_md}", flush=True)


if __name__ == "__main__":
    main()
