"""HK equity_hk_momentum TP runner sweep (atr_target_mult × atr_stop_mult).

触发：2026-06-14 HK T+0 重跑回测分析发现 — TP runner promote 0 次触发 (5×ATR target
太远), 而 time_stop (80d 极限) 出场的票 4y +28% / 8y +30% 平均, 即 ATR trail 2.5×
砍掉了"能扛 80 天的大趋势股"的尾部 alpha. 假设: 放松 target 让更多票走完 TP→runner
promotion 路径, 或调宽 trail 让更多 time_stop 尾部留住.

Grid: 4 × 3 = 12 组合 × 2 窗口 = 24 回测
  atr_target_mult ∈ {3.0, 3.5, 4.0, 5.0(baseline)}
  atr_stop_mult   ∈ {2.5(baseline), 3.0, 3.5}

不动: factor weights / regime ma / RSI window / hedge / 全局风控. 只动 trail+TP.

Backstop:
- #1 17 条证伪墙: TP runner 改动不在证伪墙里 ✓
- #2 双窗口 4y+8y 同向 PASS 才落 yaml — 本脚本仅出报表, 不动 yaml
- #3 < 30 笔实盘不撬 frontier: 本脚本不动实盘 ✓
- #4 PM 决策权: 输出汇总表 + 推荐, 不自动改 yaml ✓
- #5 N/A

用法:
  venv/bin/python scripts/backtest/run_hk_tp_runner_sweep.py
输出:
  data/backtest/_hk_tp_runner_sweep/results.json
  data/backtest/_hk_tp_runner_sweep/summary.md
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
    ("4y", "2022-01-01", "2026-06-13"),
    ("8y", "2018-01-01", "2026-06-13"),
]
MARKET = "hk_share"
STRATEGY_NAME = "equity_hk_momentum"

TARGET_GRID = [3.0, 3.5, 4.0, 5.0]   # 5.0 = current baseline
STOP_GRID = [2.5, 3.0, 3.5]          # 2.5 = current baseline
BASELINE = (5.0, 2.5)


def _build_strategy(cfg, loader, market_ctx, *, atr_target_mult: float, atr_stop_mult: float):
    deps = cfg.get("deployments") or {}
    dep_entry = (deps.get(STRATEGY_NAME) or {}).get(MARKET) or {}
    universe = loader.get_universe(MARKET, dep_entry["universe"])
    params = resolve_strategy_params(cfg, MARKET, strategy_name=STRATEGY_NAME)

    # 覆盖 sweep 参数 — 其它 timing 字段保持 yaml 原值
    params["timing"]["atr_target_mult"] = atr_target_mult
    params["timing"]["atr_stop_mult"] = atr_stop_mult

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


def _run(cfg, loader, market_ctx, start, end, *, atr_target_mult: float, atr_stop_mult: float):
    deps = cfg.get("deployments") or {}
    dep_entry = (deps.get(STRATEGY_NAME) or {}).get(MARKET) or {}
    bench = dep_entry.get("benchmark") or cfg.get("backtest", "benchmark_symbol", default="HSCHK100")
    hedge_cfg = (dep_entry.get("hedge") or {})
    fees = (dep_entry.get("fees") or {})
    bt_cfg = cfg.get("backtest") or {}
    settlement_mode = getattr(market_ctx, "settlement_mode", "t+0")

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
    strategy = _build_strategy(cfg, loader, market_ctx,
                               atr_target_mult=atr_target_mult,
                               atr_stop_mult=atr_stop_mult)
    diagnostics = BacktestDiagnostics()
    t0 = time.time()
    result = bt.run(strategy, start, end, market=MARKET, benchmark_symbol=str(bench),
                    verbose=False, diagnostics=diagnostics)
    elapsed = time.time() - t0
    m = compute_metrics(result.equity_curve, result.closed_trades, result.benchmark_curve)

    # 拆分出场原因 — time_stop / trailing_stop / break_ma80
    import re
    closed = result.closed_trades or []
    n_time_stop = 0
    pnl_time_stop = 0.0
    n_trail = 0
    n_break = 0
    for tr in closed:
        reason = getattr(tr, "exit_reason", "") or ""
        if reason.startswith("time_stop"):
            n_time_stop += 1
            pnl_time_stop += getattr(tr, "pnl_pct", 0.0)
        elif reason.startswith("trailing_stop"):
            n_trail += 1
        elif reason.startswith("break_ma"):
            n_break += 1
    avg_time_stop_pnl = pnl_time_stop / n_time_stop if n_time_stop else 0.0

    return {
        "atr_target_mult": atr_target_mult,
        "atr_stop_mult": atr_stop_mult,
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
        "n_time_stop": n_time_stop,
        "n_trail": n_trail,
        "n_break": n_break,
        "avg_time_stop_pnl_pct": avg_time_stop_pnl,
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

    out_dir = ROOT / "data/backtest/_hk_tp_runner_sweep"
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(WINDOWS) * len(TARGET_GRID) * len(STOP_GRID)
    print(f"[sweep] {total} runs ({len(WINDOWS)} windows × {len(TARGET_GRID)} target × "
          f"{len(STOP_GRID)} stop)\n", flush=True)

    results = []
    counter = 0
    for tag, start, end in WINDOWS:
        for tgt in TARGET_GRID:
            for stp in STOP_GRID:
                counter += 1
                is_baseline = (tgt, stp) == BASELINE
                label = f"[{counter}/{total}] {tag} target={tgt} stop={stp}" + (" (baseline)" if is_baseline else "")
                print(f"{label} …", flush=True)
                row = _run(cfg, loader, market_ctx, start, end,
                           atr_target_mult=tgt, atr_stop_mult=stp)
                row["window"] = tag
                row["is_baseline"] = is_baseline
                results.append(row)
                print(f"   Sharpe {row['sharpe']:+.3f} Sortino {row['sortino']:+.3f} "
                      f"Ret {row['total_return']*100:+.2f}% DD {row['max_drawdown']*100:+.2f}% "
                      f"WR {row['win_rate']*100:.1f}% N={row['n_trades']} "
                      f"[trail={row['n_trail']} time={row['n_time_stop']}@{row['avg_time_stop_pnl_pct']*100:+.1f}% "
                      f"break={row['n_break']}] [{row['elapsed_s']}s]", flush=True)

    (out_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                          encoding="utf-8")

    # ───── summary.md ─────
    # baselines per window for Δ
    by_win = {w[0]: {} for w in WINDOWS}
    for r in results:
        by_win[r["window"]][(r["atr_target_mult"], r["atr_stop_mult"])] = r
    base_4y = by_win["4y"][BASELINE]
    base_8y = by_win["8y"][BASELINE]

    lines = ["# HK equity_hk_momentum TP runner sweep",
             "",
             f"Grid: target_mult ∈ {TARGET_GRID} × stop_mult ∈ {STOP_GRID}",
             f"Baseline (yaml current): target={BASELINE[0]} stop={BASELINE[1]}",
             "",
             "## Full results"]
    lines += ["", "| window | target | stop | Sharpe | Sortino | Ret | DD | WR | N | trail | time | brk | tsPnl |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(results, key=lambda x: (x["window"], -x["sharpe"])):
        flag = " 🏁" if r["is_baseline"] else ""
        lines.append(
            f"| {r['window']} | {r['atr_target_mult']}{flag} | {r['atr_stop_mult']} | "
            f"{r['sharpe']:+.3f} | {r['sortino']:+.3f} | "
            f"{r['total_return']*100:+.2f}% | {r['max_drawdown']*100:+.2f}% | "
            f"{r['win_rate']*100:.1f}% | {r['n_trades']} | "
            f"{r['n_trail']} | {r['n_time_stop']} | {r['n_break']} | "
            f"{r['avg_time_stop_pnl_pct']*100:+.1f}% |"
        )

    # Δ vs baseline 双窗口同向 PASS 检查
    lines += ["", "## Δ vs baseline (both windows must move same direction for PASS)", ""]
    lines += ["| target | stop | 4y ΔSharpe | 4y ΔSortino | 4y ΔRet | 8y ΔSharpe | 8y ΔSortino | 8y ΔRet | both_same_sign_sharpe | PASS |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for tgt in TARGET_GRID:
        for stp in STOP_GRID:
            if (tgt, stp) == BASELINE:
                continue
            r4 = by_win["4y"][(tgt, stp)]
            r8 = by_win["8y"][(tgt, stp)]
            d4_sh = r4["sharpe"] - base_4y["sharpe"]
            d4_so = r4["sortino"] - base_4y["sortino"]
            d4_rt = r4["total_return"] - base_4y["total_return"]
            d8_sh = r8["sharpe"] - base_8y["sharpe"]
            d8_so = r8["sortino"] - base_8y["sortino"]
            d8_rt = r8["total_return"] - base_8y["total_return"]
            same_sign = (d4_sh > 0 and d8_sh > 0) or (d4_sh < 0 and d8_sh < 0)
            both_pos = d4_sh > 0 and d8_sh > 0
            verdict = "✅ PASS" if (both_pos and same_sign) else ("➖ 同负" if (d4_sh < 0 and d8_sh < 0) else "❌ 异号")
            lines.append(
                f"| {tgt} | {stp} | {d4_sh:+.3f} | {d4_so:+.3f} | {d4_rt*100:+.2f}pp | "
                f"{d8_sh:+.3f} | {d8_so:+.3f} | {d8_rt*100:+.2f}pp | "
                f"{'yes' if same_sign else 'no'} | {verdict} |"
            )

    # 推荐
    cand = []
    for tgt in TARGET_GRID:
        for stp in STOP_GRID:
            if (tgt, stp) == BASELINE: continue
            r4 = by_win["4y"][(tgt, stp)]; r8 = by_win["8y"][(tgt, stp)]
            d4 = r4["sharpe"] - base_4y["sharpe"]; d8 = r8["sharpe"] - base_8y["sharpe"]
            if d4 > 0 and d8 > 0:
                cand.append(((tgt, stp), d4, d8, d4 + d8))
    cand.sort(key=lambda x: -x[3])
    lines += ["", "## 推荐 (双窗口同向 PASS, 按 ΔSharpe 之和排序)"]
    if not cand:
        lines.append("\n**无候选** — sweep 全空，baseline (5.0/2.5) 是 efficient set 内。")
    else:
        for (tgt, stp), d4, d8, total in cand[:5]:
            lines.append(f"- target={tgt} stop={stp} → 4y ΔSharpe {d4:+.3f} / 8y ΔSharpe {d8:+.3f} (sum {total:+.3f})")

    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✅ 完成: {out_dir}/summary.md")


if __name__ == "__main__":
    main()
