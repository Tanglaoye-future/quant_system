#!/usr/bin/env python3
"""
equity_factor L7 Pullback 入场模式扫描.

完全替换原"金叉+突破+RSI 50-70+量能"追高 timing 为"大趋势+回调+量缩+RSI 反弹"低位识别.

实验 (a_share HS300, 2018-2026):
  baseline  : 当前 config (金叉/突破模式, m2_pullback_mode=False)
  L7-A1     : pullback defaults (pos<=0.5, RSI 35-55, vol<=1×5d, MA60>MA200, 2/5 green)
  L7-A2     : pos<=0.7 (broader)
  L7-A3     : pos<=0.3 (deep dips only)
  L7-A4     : RSI 30-60 (wider band)
  L7-A5     : no long_trend filter (MA60>MA200 removed)
  L7-A6     : vol<=0.8 (stricter contraction)

每实验同窗口，输出 markdown summary.

用法:
  PYTHONUNBUFFERED=1 PYTHONPATH=src venv/bin/python -u \\
      scripts/backtest/run_l7_pullback_sweep.py
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
import time
from pathlib import Path

import pandas as pd
import yaml

from quant_system.config import Config, load_config
from quant_system.strategies.equity_factor.bottomup.factors import FactorWeights
from quant_system.strategies.equity_factor.bottomup.portfolio import m4_config_from_yaml
from quant_system.strategies.equity_factor.data.loader import DataLoader
from quant_system.strategies.equity_factor.engine.backtest import BacktestDiagnostics, Backtester
from quant_system.strategies.equity_factor.engine.metrics import compute_metrics
from quant_system.strategies.equity_factor.engine.strategy import BottomupTimingStrategy
from quant_system.strategies.equity_factor.timing.signals import timing_config_from_yaml_node


ROOT = Path(__file__).resolve().parents[2]
START = "2018-01-01"
END = "2026-05-04"
MARKET = "a_share"


EXPERIMENTS: list[tuple[str, dict]] = [
    ("baseline-current",   {}),  # 当前 config（金叉/突破模式）
    ("L7-A1-defaults",     {
        "m2_pullback_mode": True,
        "pullback_price_position_max": 0.5,
        "pullback_rsi_low": 35.0, "pullback_rsi_high": 55.0,
        "pullback_vol_max_ratio": 1.0,
        "pullback_require_long_trend": True,
    }),
    ("L7-A2-pos070",       {
        "m2_pullback_mode": True,
        "pullback_price_position_max": 0.7,
    }),
    ("L7-A3-pos030",       {
        "m2_pullback_mode": True,
        "pullback_price_position_max": 0.3,
    }),
    ("L7-A4-rsi30-60",     {
        "m2_pullback_mode": True,
        "pullback_rsi_low": 30.0, "pullback_rsi_high": 60.0,
    }),
    ("L7-A5-no-long-trend",{
        "m2_pullback_mode": True,
        "pullback_require_long_trend": False,
    }),
    ("L7-A6-vol08",        {
        "m2_pullback_mode": True,
        "pullback_vol_max_ratio": 0.8,
    }),
]


def run_one(tag: str, overrides: dict, base_raw: dict, market: str) -> dict:
    cfg_dict = copy.deepcopy(base_raw)
    # 注入 overrides 到 markets.<market>.timing (优先级高于 strategy.timing)
    market_cfg = cfg_dict.setdefault("markets", {}).setdefault(market, {})
    mkt_timing = market_cfg.setdefault("timing", {})
    if overrides:
        mkt_timing.update(overrides)

    cfg = Config(raw=cfg_dict)

    market_cfg_bt = cfg.get("markets", market) or {}
    universe = market_cfg_bt.get("universe", "hs300")

    data_cfg = cfg.get("data", default={}) or {}
    hsi = data_cfg.get("hang_seng_indexes")
    us_mkt = data_cfg.get("us_market")
    loader = DataLoader(
        cfg.cache_dir,
        refresh_days=999,
        price_adjust=data_cfg.get("price_adjust", "qfq"),
        hang_seng_indexes=hsi, us_market=us_mkt,
    )

    # 构造 strategy（同 backtest.py build_strategy 逻辑）
    global_timing = cfg.get("strategy", "timing", default=None) or {}
    global_weights = cfg.get("factors", "weights", default={}) or {}
    m4_cfg = m4_config_from_yaml(cfg.get("factors", "m4", default=None))
    bt_fallback = cfg.get("backtest", "benchmark_symbol", default="sh000300")
    bench = market_cfg_bt.get("benchmark") or bt_fallback
    merged_timing = {**global_timing, **mkt_timing}
    merged_weights = {**global_weights, **(market_cfg_bt.get("factors") or {}).get("weights", {})}
    tcfg = timing_config_from_yaml_node(merged_timing)

    uni = loader.get_universe(market, universe)
    strategy = BottomupTimingStrategy(
        loader=loader, market=market,
        universe_codes=uni["code"].tolist(),
        timing_cfg=tcfg,
        weights=FactorWeights(**merged_weights),
        regime_benchmark_symbol=str(bench),
        m4_cfg=m4_cfg,
    )

    # 隔离输出
    out_dir = ROOT / f"data/backtest/_l7_{tag}"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bt_cfg = cfg.get("backtest") or {}
    hedge_cfg = (market_cfg_bt.get("hedge") or {})
    bt = Backtester(
        loader=loader,
        initial_capital=bt_cfg.get("initial_capital", 1_000_000),
        max_positions=cfg.get("strategy", "position_max_count", default=10),
        single_position_pct=cfg.get("strategy", "single_position_pct_max", default=0.15),
        commission=bt_cfg.get("commission", 0.0003),
        stamp_tax=bt_cfg.get("stamp_tax", 0.001),
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
        "override": overrides,
        "sharpe": float(m.sharpe_ratio),
        "total_return": float(m.total_return),
        "max_drawdown": float(m.max_drawdown),
        "win_rate": float(m.win_rate),
        "n_trades": int(m.n_trades),
        "annual_return": float(m.annual_return),
        "calmar": float(m.calmar_ratio),
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
    base_cfg = load_config()
    base_raw = base_cfg.raw  # 共享 base, 每次 deep-copy 改
    results = []
    for tag, overrides in EXPERIMENTS:
        try:
            results.append(run_one(tag, overrides, base_raw, MARKET))
        except Exception as e:
            print(f"[{tag}] ERROR: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc()
            continue

    # 输出 md
    out_md = ROOT / "data/backtest/equity_factor_l7_pullback_summary.md"
    lines = [
        "# equity_factor L7 Pullback 入场模式扫描",
        "",
        f"市场: {MARKET}  窗口: {START} → {END}",
        "",
        "baseline = 当前 config (金叉/突破追高); L7-A* = pullback 模式不同参数",
        "",
        "| 标签 | Sharpe | 年化 | 总收益 | DD | 胜率 | 笔数 | Calmar |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['tag']} | {r['sharpe']:.3f} | {r['annual_return']*100:+.1f}% | "
            f"{r['total_return']*100:+.1f}% | {r['max_drawdown']*100:.1f}% | "
            f"{r['win_rate']*100:.1f}% | {r['n_trades']} | {r['calmar']:.2f} |"
        )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    out_md.with_suffix(".json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\n[L7 sweep] summary → {out_md}", flush=True)


if __name__ == "__main__":
    main()
