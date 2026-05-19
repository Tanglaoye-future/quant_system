#!/usr/bin/env python3
"""
equity_factor L7-B (Pullback Plan B) sweep.

Plan B 三组增量过滤（基于 L7-A defaults 的 5 条基础检查 + 增量）:
  B1: 强势 regime gate (HS300 > MA200 AND > MA60 AND 20d_dd > -5%)
  B2: 反弹确认 (higher low + close > MA20)
  B3: 相对强度 (个股 20d 跑赢指数)

实验 (a_share HS300, 2020-2026):
  baseline-current  : 当前追高 baseline (对照)
  L7-B0-defaults    : 纯 pullback 默认 (control, 已知失败)
  L7-B1-regime      : + 强势 regime gate
  L7-B1B2-conf      : + 反弹确认
  L7-B1B2B3-rs      : + 相对强度

每实验 ~1.5-2.5h，共 ~10h. 用 2020-2026 (6y) 而非 2018-2026 节省时间.
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
START = "2020-01-01"
END = "2026-05-04"
MARKET = "a_share"


# 共用 B0 defaults
B0 = {
    "m2_pullback_mode": True,
    "pullback_price_position_max": 0.5,
    "pullback_rsi_low": 35.0, "pullback_rsi_high": 55.0,
    "pullback_vol_max_ratio": 1.0,
    "pullback_require_long_trend": True,
}
B1 = {**B0, "pullback_b1_regime_strict": True}
B1B2 = {**B1, "pullback_b2_reversal_required": True}
B1B2B3 = {**B1B2, "pullback_b3_relative_strength_min": 0.0}  # 0% = 不输给指数


EXPERIMENTS: list[tuple[str, dict]] = [
    ("baseline-current",   {}),
    ("L7-B0-defaults",     B0),
    ("L7-B1-regime",       B1),
    ("L7-B1B2-conf",       B1B2),
    ("L7-B1B2B3-rs",       B1B2B3),
]


def run_one(tag: str, overrides: dict, base_raw: dict, market: str) -> dict:
    cfg_dict = copy.deepcopy(base_raw)
    market_cfg = cfg_dict.setdefault("markets", {}).setdefault(market, {})
    mkt_timing = market_cfg.setdefault("timing", {})
    if overrides:
        mkt_timing.update(overrides)

    cfg = Config(raw=cfg_dict)
    market_cfg_bt = cfg.get("markets", market) or {}
    universe = market_cfg_bt.get("universe", "hs300")

    data_cfg = cfg.get("data", default={}) or {}
    loader = DataLoader(
        cfg.cache_dir, refresh_days=999,
        price_adjust=data_cfg.get("price_adjust", "qfq"),
        hang_seng_indexes=data_cfg.get("hang_seng_indexes"),
        us_market=data_cfg.get("us_market"),
    )

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

    out_dir = ROOT / f"data/backtest/_l7b_{tag}"
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
        "tag": tag, "override": overrides,
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
    base_raw = base_cfg.raw
    results = []
    for tag, overrides in EXPERIMENTS:
        try:
            results.append(run_one(tag, overrides, base_raw, MARKET))
        except Exception as e:
            print(f"[{tag}] ERROR: {e}", file=sys.stderr, flush=True)
            import traceback; traceback.print_exc()

    out_md = ROOT / "data/backtest/equity_factor_l7b_pullback_summary.md"
    lines = [
        "# equity_factor L7-B Pullback Plan B 扫描",
        "",
        f"市场: {MARKET}  窗口: {START} → {END}",
        "",
        "B0 = pure pullback defaults (5 检查); B1+ = 加强势 regime; B2+ = 加反弹确认; B3+ = 加相对强度",
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
    print(f"\n[L7-B sweep] summary → {out_md}", flush=True)


if __name__ == "__main__":
    main()
