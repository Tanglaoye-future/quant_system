#!/usr/bin/env python3
"""
equity_factor L9-A: regime-aware partial_exit sweep.

背景：
  L8D2 (fcf=0) 落地后 4y Sharpe 0.675、8y Sharpe 0.195 / DD -19.5%；
  最新 cross_market 12-cell 跑 8y Sharpe 0.28 / 收益 +42.81% / 平均持有 12.3 天 — partial_exit
  在 8y 牛市段把持仓早锁利，吃不到趋势。

L9-A: 当基准指数收盘 > MA(N) 时（"牛市"），跳过 partial_exit 走全平 TP；
        基准 <= MA(N) 时保留 partial_exit 锁利。N ∈ {60, 120, 200} sweep 找最优。

并行：ProcessPoolExecutor + QUANT_DUCKDB_READ_ONLY=1。10 核 16GB 推荐 workers=4。

用法：
  python scripts/backtest/run_l9_partial_regime_sweep.py                 # 4y 全 sweep
  python scripts/backtest/run_l9_partial_regime_sweep.py --window 8y    # 8y 全 sweep
  python scripts/backtest/run_l9_partial_regime_sweep.py --window both  # 4y + 8y 全跑
  python scripts/backtest/run_l9_partial_regime_sweep.py --cases L9-A-baseline L9-A-ma200
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MARKET = "a_share"

WINDOWS = {
    "4y": ("2022-01-01", "2026-05-25"),
    "8y": ("2018-01-01", "2026-05-25"),
}

# (tag, timing_override)
# baseline = 当前 yaml (partial_exit_regime_filter=False)；L9-A 三档 ma_days
EXPERIMENTS: list[tuple[str, dict]] = [
    ("L9-A-baseline",          {}),
    ("L9-A-ma60",              {"partial_exit_regime_filter": True,
                                "partial_exit_regime_ma_days": 60}),
    ("L9-A-ma120",             {"partial_exit_regime_filter": True,
                                "partial_exit_regime_ma_days": 120}),
    ("L9-A-ma200",             {"partial_exit_regime_filter": True,
                                "partial_exit_regime_ma_days": 200}),
]


def _run_one(args: tuple) -> dict:
    """子进程内执行：单 case + 单窗口。"""
    tag, timing_override, window, start, end = args

    # 子进程内 import；DuckDB read_only 已通过 env 设置
    from quant_system.config import Config, load_config
    from quant_system.market import load_market_context
    from quant_system.strategies.equity_factor.bottomup.factors import FactorWeights
    from quant_system.strategies.equity_factor.bottomup.portfolio import m4_config_from_yaml
    from quant_system.strategies.equity_factor.data.loader import DataLoader
    from quant_system.strategies.equity_factor.engine.backtest import BacktestDiagnostics, Backtester
    from quant_system.strategies.equity_factor.engine.metrics import compute_metrics
    from quant_system.strategies.equity_factor.engine.strategy import BottomupTimingStrategy
    from quant_system.strategies.equity_factor.timing.signals import timing_config_from_yaml_node

    base_cfg = load_config()
    cfg_dict = copy.deepcopy(base_cfg.raw)
    market_cfg = cfg_dict.setdefault("markets", {}).setdefault(MARKET, {})
    mkt_timing = market_cfg.setdefault("timing", {})
    if timing_override:
        mkt_timing.update(timing_override)

    cfg = Config(raw=cfg_dict)
    market_cfg_bt = cfg.get("markets", MARKET) or {}
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
    m4_cfg = m4_config_from_yaml(cfg.get("factors", "m4", default=None))
    bench = market_cfg_bt.get("benchmark") or cfg.get("backtest", "benchmark_symbol", default="sh000300")
    merged_timing = {**global_timing, **mkt_timing}
    merged_weights = {**global_weights, **(market_cfg_bt.get("factors") or {}).get("weights", {})}

    tcfg = timing_config_from_yaml_node(merged_timing)
    uni = loader.get_universe(MARKET, universe)
    market_ctx = load_market_context(cfg, MARKET)
    strategy = BottomupTimingStrategy(
        loader=loader, market=MARKET, universe_codes=uni["code"].tolist(),
        timing_cfg=tcfg, weights=FactorWeights(**merged_weights),
        regime_benchmark_symbol=str(bench), m4_cfg=m4_cfg,
        market_ctx=market_ctx,
    )

    out_dir = ROOT / f"data/backtest/_l9_{tag}_{window}"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bt_cfg = cfg.get("backtest") or {}
    hedge_cfg = (market_cfg_bt.get("hedge") or {})
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
    result = bt.run(strategy, start, end, market=MARKET,
                    benchmark_symbol=str(bench), diagnostics=diagnostics)
    elapsed = time.time() - t0
    m = compute_metrics(result.equity_curve, result.closed_trades, result.benchmark_curve)
    return {
        "tag": tag,
        "window": window,
        "start": start,
        "end": end,
        "timing_override": timing_override,
        "sharpe": float(m.sharpe_ratio),
        "total_return": float(m.total_return),
        "max_drawdown": float(m.max_drawdown),
        "win_rate": float(m.win_rate),
        "n_trades": int(m.n_trades),
        "annual_return": float(m.annual_return),
        "annual_vol": float(getattr(m, "annual_volatility", 0.0)),
        "elapsed_s": round(elapsed, 1),
    }


RESULT_DIR = ROOT / "data" / "backtest" / "_l9_results"


def _single_task_subprocess(tag: str, window: str) -> dict:
    """fork 子进程跑单 case + 单窗口，绕开 macOS sandbox ProcessPoolExecutor 限制。"""
    log_file = RESULT_DIR / f"{tag}_{window}.log"
    result_file = RESULT_DIR / f"{tag}_{window}.json"
    # 继承父 env；显式 PYTHONPATH 防 macOS UF_HIDDEN 让 editable .pth 在子进程失效
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    env["QUANT_DUCKDB_READ_ONLY"] = "1"
    cmd = [
        str(ROOT / "venv" / "bin" / "python"),
        str(Path(__file__).resolve()),
        "--single-task", tag, window,
    ]
    t0 = time.time()
    with open(log_file, "w") as f:
        f.write(f"# cmd: {' '.join(cmd)}\n")
        f.write(f"# start: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.flush()
        p = subprocess.run(cmd, env=env, cwd=str(ROOT),
                           stdout=f, stderr=subprocess.STDOUT)
    elapsed = time.time() - t0
    if p.returncode != 0 or not result_file.exists():
        return {"tag": tag, "window": window, "error": f"rc={p.returncode}",
                "elapsed_s": elapsed, "log": str(log_file)}
    try:
        r = json.loads(result_file.read_text())
    except Exception as e:
        return {"tag": tag, "window": window, "error": f"parse: {e}",
                "elapsed_s": elapsed, "log": str(log_file)}
    r["log"] = str(log_file)
    return r


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", choices=["4y", "8y", "both"], default="4y")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--cases", nargs="*", default=None,
                        help="过滤要跑的 tag (默认全部)")
    parser.add_argument("--single-task", nargs=2, metavar=("TAG", "WINDOW"),
                        default=None,
                        help="内部用：跑单 case + 单窗口，结果写 RESULT_DIR/<tag>_<window>.json")
    args = parser.parse_args()

    # 单 case 模式（被父进程 subprocess 调用）
    if args.single_task is not None:
        tag, window = args.single_task
        cases_map = dict(EXPERIMENTS)
        if tag not in cases_map:
            print(f"!! 未知 tag: {tag}", file=sys.stderr); sys.exit(2)
        if window not in WINDOWS:
            print(f"!! 未知 window: {window}", file=sys.stderr); sys.exit(2)
        start, end = WINDOWS[window]
        r = _run_one((tag, cases_map[tag], window, start, end))
        RESULT_DIR.mkdir(parents=True, exist_ok=True)
        (RESULT_DIR / f"{tag}_{window}.json").write_text(
            json.dumps(r, indent=2, ensure_ascii=False)
        )
        print(f"[single-task] {tag}/{window} sharpe={r['sharpe']:+.3f} done", flush=True)
        return

    cases = EXPERIMENTS if not args.cases else [
        (t, ov) for (t, ov) in EXPERIMENTS if t in args.cases
    ]
    if not cases:
        print(f"!! 没有匹配的 case: {args.cases}; 可选 {[t for t, _ in EXPERIMENTS]}",
              file=sys.stderr)
        return

    windows = ["4y", "8y"] if args.window == "both" else [args.window]
    tasks = []
    for w in windows:
        for tag, _ in cases:
            tasks.append((tag, w))

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"=== L9-A sweep ===")
    print(f"  cases: {[t for t, _ in cases]}")
    print(f"  windows: {windows}")
    print(f"  total tasks: {len(tasks)}  workers: {args.workers} (subprocess pool)")
    print(f"  per-case log: {RESULT_DIR}/<tag>_<window>.log")
    print(flush=True)

    results = []
    t_start = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_single_task_subprocess, tag, w): (tag, w) for tag, w in tasks}
        for f in as_completed(futs):
            tag, w = futs[f]
            try:
                r = f.result()
            except Exception as e:
                print(f"  ❌ {tag}/{w} ERROR: {e}", file=sys.stderr, flush=True)
                continue
            results.append(r)
            if "error" in r:
                print(f"  ❌ {tag:<22} {w} ERROR: {r['error']} log={r.get('log')}",
                      flush=True)
                continue
            print(
                f"  ✅ {r['tag']:<22} {r['window']} "
                f"sharpe={r['sharpe']:+.3f} ann={r['annual_return']*100:+.1f}% "
                f"ret={r['total_return']*100:+.1f}% dd={r['max_drawdown']*100:+.1f}% "
                f"win={r['win_rate']*100:.1f}% n={r['n_trades']} "
                f"elapsed={r['elapsed_s']/60:.1f}min",
                flush=True,
            )

    total_min = (time.time() - t_start) / 60.0
    print(f"\n=== 全部完成 === 挂钟 {total_min:.1f}min")

    # 过滤错误项 + 按 window 排序输出汇总
    results = [r for r in results if "error" not in r]
    results.sort(key=lambda r: (r["window"], r["tag"]))
    out_md = ROOT / "data/backtest/equity_factor_l9_partial_regime_summary.md"
    lines = [
        "# equity_factor L9-A: regime-aware partial_exit sweep",
        "",
        f"市场: {MARKET}",
        "",
        "对照：baseline = 当前 yaml (partial_exit_regime_filter=False)；",
        "L9-A: 当 HS300 收盘 > MA(N) 时跳过 partial_exit 走全平 TP，吃趋势；MA 下方保留 partial 锁利。",
        "",
        "| 窗口 | 标签 | Sharpe | 年化 | 收益 | DD | 胜率 | 笔数 | 耗时 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['window']} | {r['tag']} | {r['sharpe']:+.3f} | "
            f"{r['annual_return']*100:+.2f}% | {r['total_return']*100:+.1f}% | "
            f"{r['max_drawdown']*100:+.2f}% | {r['win_rate']*100:.1f}% | "
            f"{r['n_trades']} | {r['elapsed_s']/60:.1f}min |"
        )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    out_md.with_suffix(".json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False)
    )
    print(f"\n[L9-A sweep] summary → {out_md}", flush=True)


if __name__ == "__main__":
    main()
