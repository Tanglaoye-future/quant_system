#!/usr/bin/env python3
"""
SwingReversion v2 参数 sweep — 在 v2 baseline (buffer=0.03, slope=on, grace=3) 附近搜.

设计：固定 ma_long_slope_enabled=true（v1 baseline 已证 break_ma200 噪音大），
扫 (buffer, grace) 二维 9 组合 + 1 个 slope_off 对照 = 10 cases.

参数:
  buffer:  [0.02, 0.03, 0.05]
  grace:   [2, 3, 5]
  对照:    buffer=0, slope=False, grace=0 (v1 baseline 已跑过；这里跳过避免重复)

每 case 在子进程跑 backtest.py，通过临时 yaml override 注入参数. 4-worker 并行.

输出：data/backtest/swing_rev_v2_sweep_<tag>/，并汇总 summary.md.

用法:
  python scripts/backtest/run_swing_rev_v2_sweep.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml

ROOT = Path(__file__).resolve().parents[2]
START = "2022-01-01"
END = "2026-05-25"
PYTHON = str(ROOT / "venv" / "bin" / "python")
# 必须串行：yaml 全局共享 + backtest.py 固定 output dir，并发 worker 会 race
# (2026-05-30 sweep 用 4-worker 时多 case 拿到错误数据 / metrics.json 缺失)
N_WORKERS = 1

CASES = [
    # (tag, buffer, slope_enabled, grace)
    ("buf02_slope_g2", 0.02, True, 2),
    ("buf02_slope_g3", 0.02, True, 3),
    ("buf02_slope_g5", 0.02, True, 5),
    ("buf03_slope_g2", 0.03, True, 2),
    ("buf03_slope_g3", 0.03, True, 3),  # v2 default
    ("buf03_slope_g5", 0.03, True, 5),
    ("buf05_slope_g2", 0.05, True, 2),
    ("buf05_slope_g3", 0.05, True, 3),
    ("buf05_slope_g5", 0.05, True, 5),
    # 对照: buffer only (no slope/grace) 看是否单 buffer 就足够
    ("buf03_only",     0.03, False, 1),
]


def run_one_case(tag: str, buffer: float, slope: bool, grace: int) -> dict:
    """跑一个 case：临时改 yaml 注入参数，调 backtest.py，移到 sweep 子目录.

    串行运行：因 yaml 全局共享 + backtest.py 固定 output dir, 并发 worker 会 race.
    """
    cfg_path = ROOT / "config" / "markets" / "a_share.yaml"
    bak = cfg_path.read_text(encoding="utf-8")
    try:
        # 改 yaml swing_reversion 节
        d = yaml.safe_load(bak)
        d["swing_reversion"] = {
            "ma_long_buffer_pct": float(buffer),
            "ma_long_slope_enabled": bool(slope),
            "ma_long_slope_lookback": 20,
            "break_ma_grace_days": int(grace),
        }
        cfg_path.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")

        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
        env["QUANT_DUCKDB_READ_ONLY"] = "1"

        log_path = ROOT / "data" / "backtest" / f"swing_rev_v2_{tag}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        with open(log_path, "w", encoding="utf-8") as f:
            proc = subprocess.run(
                [PYTHON, "scripts/backtest/backtest.py",
                 "--strategy", "swing_reversion", "--market", "a_share",
                 "--start", START, "--end", END, "--refresh-days", "999"],
                cwd=str(ROOT), env=env, stdout=f, stderr=subprocess.STDOUT,
            )
        elapsed = time.time() - t0

        # backtest.py 输出到 data/backtest/swing_reversion_a_share_<start>_<end>/
        # 移到 sweep 子目录避免互相覆盖（串行运行下安全）
        src = ROOT / "data" / "backtest" / f"swing_reversion_a_share_{START}_{END}"
        dst = ROOT / "data" / "backtest" / f"swing_rev_v2_sweep_{tag}"
        if src.exists():
            if dst.exists():
                import shutil
                shutil.rmtree(dst)
            src.rename(dst)
            # 读 metrics.json — backtest.py 写的是嵌套结构 {"metrics": {...}}
            metrics_path = dst / "metrics.json"
            if metrics_path.exists():
                raw = json.loads(metrics_path.read_text())
                metrics = raw.get("metrics") or raw   # 容错 flat / nested 两种结构
            else:
                metrics = {}
        else:
            metrics = {}
        return {
            "tag": tag, "buffer": buffer, "slope": slope, "grace": grace,
            "elapsed_s": round(elapsed, 1), "exit_code": proc.returncode,
            "metrics": metrics,
        }
    finally:
        cfg_path.write_text(bak, encoding="utf-8")


def main():
    print(f"=== SwingReversion v2 sweep ({len(CASES)} cases, {N_WORKERS}-worker) ===")
    print(f"  window: {START} → {END}")
    for t, b, s, g in CASES:
        print(f"  - {t:<20} buf={b} slope={s} grace={g}")
    print()

    t_start = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=N_WORKERS) as ex:
        futs = {ex.submit(run_one_case, *case): case for case in CASES}
        for f in as_completed(futs):
            res = f.result()
            results.append(res)
            m = res.get("metrics") or {}
            sharpe = m.get("sharpe_ratio", m.get("sharpe"))
            n_trades = m.get("n_trades", "?")
            print(f"  [{res['tag']:<20}] sharpe={sharpe} trades={n_trades} elapsed={res['elapsed_s']}s")

    # 汇总
    results.sort(key=lambda r: (r.get("metrics") or {}).get("sharpe_ratio",
                                                            (r.get("metrics") or {}).get("sharpe", -99)),
                 reverse=True)
    print(f"\n=== Top winners (sorted by Sharpe) ===")
    print(f"{'rank':<5} {'tag':<22} {'Sharpe':>7} {'Ann%':>7} {'DD%':>7} {'Trades':>7} buffer slope grace")
    summary_md = ["# SwingReversion v2 sweep\n",
                  f"window: {START} → {END}", f"workers: {N_WORKERS}", "",
                  "| rank | tag | Sharpe | Ann% | DD% | 胜率% | Trades | buffer | slope | grace |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(results, 1):
        m = r.get("metrics") or {}
        sh = m.get("sharpe_ratio", m.get("sharpe", float("nan")))
        ann = m.get("annual_return", float("nan"))
        dd = m.get("max_drawdown", float("nan"))
        n_tr = m.get("n_trades", "?")
        win = m.get("win_rate", float("nan"))
        try:
            sh_s = f"{float(sh):+.3f}" if sh is not None else "NA"
            ann_s = f"{float(ann)*100:+.2f}" if ann is not None else "NA"
            dd_s = f"{float(dd)*100:+.2f}" if dd is not None else "NA"
            win_s = f"{float(win)*100:.1f}" if win is not None else "NA"
        except Exception:
            sh_s = str(sh); ann_s = str(ann); dd_s = str(dd); win_s = str(win)
        print(f"  {i:<5} {r['tag']:<22} {sh_s:>7} {ann_s:>7} {dd_s:>7} {str(n_tr):>7}  "
              f"{r['buffer']} {r['slope']} {r['grace']}")
        summary_md.append(f"| {i} | {r['tag']} | {sh_s} | {ann_s} | {dd_s} | {win_s} | {n_tr} | "
                          f"{r['buffer']} | {r['slope']} | {r['grace']} |")

    out_md = ROOT / "data" / "backtest" / "swing_rev_v2_sweep_summary.md"
    out_md.write_text("\n".join(summary_md), encoding="utf-8")
    out_json = out_md.with_suffix(".json")
    out_json.write_text(json.dumps(results, indent=2, default=str, ensure_ascii=False))
    print(f"\n  [汇总] {out_md}")
    print(f"  [汇总] {out_json}")
    print(f"\n总耗时 {round((time.time()-t_start)/60, 1)} min")


if __name__ == "__main__":
    main()
