#!/usr/bin/env python3
"""
9-cell 跨市场回测并行 driver.

跑 6 cell × 2 窗口 = 12 个回测任务, 并行 4 个 subprocess。

可跑的 6 cell:
  原生 4:
    equity_momentum     @ a_share   (L7-C3 + L8D2)
    equity_hk_momentum  @ hk_share  (L1+L2-B)
    equity_us_momentum  @ us_share  (deprecated; 仅研究)
    zhuang              @ a_share   (L1-L5 落地版)
  cross-market 2 (Phase 1-B 解锁):
    equity_momentum     @ hk_share  (A 股最优参数跑 HK; transferability 测试)
    equity_momentum     @ us_share  (同上跑 US)

不可跑的 3 cell:
    zhuang @ hk/us  — Phase 1-D 调研后退回, HK provider 未接入
    options @ *     — options 不是回测系统 (IBKR 实时期权扫描)

并发安全: 通过 env QUANT_DUCKDB_READ_ONLY=1 让 DuckDBStore read_only 打开,
避免多进程同时写 DuckDB 撞 file lock。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON = str(REPO_ROOT / "venv" / "bin" / "python")
LOG_DIR = REPO_ROOT / "data" / "cross_market_audit_logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# (label, strategy, market, runner, start, end)
ALL_TASKS = [
    # 4 原生 cell × 2 窗口
    ("eq_a_4y",      "equity_momentum",     "a_share",  "equity", "2022-01-01", "2026-05-25"),
    ("eq_a_8y",      "equity_momentum",     "a_share",  "equity", "2018-01-01", "2026-05-25"),
    ("eq_hk_4y",     "equity_hk_momentum",  "hk_share", "equity", "2022-01-01", "2026-05-25"),
    ("eq_hk_8y",     "equity_hk_momentum",  "hk_share", "equity", "2018-01-01", "2026-05-25"),
    ("eq_us_4y",     "equity_us_momentum",  "us_share", "equity", "2022-01-01", "2026-05-25"),
    ("eq_us_8y",     "equity_us_momentum",  "us_share", "equity", "2018-01-01", "2026-05-25"),
    # 2 cross-market cell × 2 窗口 (Phase 1-B 解锁)
    ("eq_x_hk_4y",   "equity_momentum",     "hk_share", "equity", "2022-01-01", "2026-05-25"),
    ("eq_x_hk_8y",   "equity_momentum",     "hk_share", "equity", "2018-01-01", "2026-05-25"),
    ("eq_x_us_4y",   "equity_momentum",     "us_share", "equity", "2022-01-01", "2026-05-25"),
    ("eq_x_us_8y",   "equity_momentum",     "us_share", "equity", "2018-01-01", "2026-05-25"),
    # zhuang × 2 窗口
    ("zh_a_4y",      "zhuang",              "a_share",  "zhuang", "2022-01-01", "2026-05-25"),
    ("zh_a_8y",      "zhuang",              "a_share",  "zhuang", "2018-01-01", "2026-05-25"),
]


def run_task(task: tuple) -> dict:
    label, sname, market, runner, start, end = task
    log_file = LOG_DIR / f"{label}.log"

    env = {
        # 走 venv site-packages
        "PYTHONPATH": "src",
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        # 多进程 DuckDB read_only 安全
        "QUANT_DUCKDB_READ_ONLY": "1",
        "HOME": os.environ.get("HOME", ""),
        "USER": os.environ.get("USER", ""),
        "LC_ALL": "en_US.UTF-8",
        "LANG": "en_US.UTF-8",
    }

    if runner == "equity":
        # 用 strategy_name + market 精确 lookup 路径 (Phase 1-B)
        cmd = [
            PYTHON, "scripts/backtest/backtest.py",
            "--strategy", sname,
            "--market", market,
            "--start", start, "--end", end,
            "--refresh-days", "999",  # 命中本地 cache, 不走远端
        ]
    else:
        # backtest_zhuang.py 没有 --strategy / --market 参数 (只跑 zhuang)
        # Phase 1-C 加了 --market 但默认 a_share 已足够 (zhuang_hk_small 未实现)
        cmd = [
            PYTHON, "scripts/backtest/backtest_zhuang.py",
            "--start", start, "--end", end,
            "--refresh-days", "999",
        ]

    t0 = time.time()
    with open(log_file, "w") as f:
        f.write(f"# cmd: {' '.join(cmd)}\n")
        f.write(f"# start: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.flush()
        p = subprocess.run(
            cmd, env=env, cwd=str(REPO_ROOT),
            stdout=f, stderr=subprocess.STDOUT,
        )
    elapsed = time.time() - t0
    return {
        "label": label, "strategy": sname, "market": market,
        "start": start, "end": end,
        "returncode": p.returncode, "elapsed_min": elapsed / 60.0,
        "log": str(log_file),
    }


def collect_metrics() -> list[dict]:
    import pandas as pd
    rows = []
    for task in ALL_TASKS:
        label, sname, market, runner, start, end = task
        row = {
            "label": label, "strategy": sname, "market": market,
            "start": start, "end": end,
            "sharpe": None, "annual_ret": None, "max_dd": None,
            "win_rate": None, "n_trades": None, "admission": None,
        }
        if runner == "equity":
            mdir = REPO_ROOT / f"data/backtest/{sname}_{market}_{start}_{end}"
            mfile = mdir / "metrics.json"
            if mfile.exists():
                try:
                    m = json.loads(mfile.read_text())
                    mm = m.get("metrics", {})
                    row.update({
                        "sharpe": round(float(mm.get("sharpe_ratio", 0)), 4),
                        "annual_ret": round(float(mm.get("annual_return", 0)) * 100, 2),
                        "max_dd": round(float(mm.get("max_drawdown", 0)) * 100, 2),
                        "win_rate": round(float(mm.get("win_rate", 0)) * 100, 1),
                        "n_trades": int(mm.get("n_trades", 0)),
                        "admission": "PASS" if m.get("admission_pass") else "FAIL",
                    })
                except Exception as e:
                    row["error"] = f"parse_metrics_json: {e}"
        else:  # zhuang
            mdir = REPO_ROOT / f"data/backtest/zhuang_{market}_{start}_{end}"
            mfile = mdir / "metrics.csv"
            if mfile.exists():
                try:
                    m = pd.read_csv(mfile, header=None, index_col=0, names=["v"])["v"].to_dict()
                    row.update({
                        "sharpe": round(float(m.get("sharpe_ratio", 0)), 4),
                        "annual_ret": round(float(m.get("annualized_return", 0)) * 100, 2),
                        "max_dd": round(float(m.get("max_drawdown", 0)) * 100, 2),
                        "win_rate": round(float(m.get("win_rate", 0)) * 100, 1),
                        "n_trades": int(m.get("total_trades", 0)),
                    })
                except Exception as e:
                    row["error"] = f"parse_metrics_csv: {e}"
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description="9-cell 跨市场回测并行 driver")
    parser.add_argument("--workers", type=int, default=4,
                        help="并行 worker 数 (默认 4; 10 核 16 GB 推荐 4-6)")
    parser.add_argument("--only-4y", action="store_true", help="仅跑 4y 窗口 (快验)")
    parser.add_argument("--only-8y", action="store_true", help="仅跑 8y 窗口")
    parser.add_argument("--collect-only", action="store_true",
                        help="跳过跑回测, 仅从现有 data/backtest/ 汇总 metrics")
    args = parser.parse_args()

    tasks = ALL_TASKS
    if args.only_4y:
        tasks = [t for t in tasks if t[0].endswith("_4y")]
    if args.only_8y:
        tasks = [t for t in tasks if t[0].endswith("_8y")]

    if not args.collect_only:
        # 长任务 (8y) 先派, 让 4 worker 同时启动后均匀消耗
        tasks_sorted = sorted(tasks, key=lambda t: 0 if t[0].endswith("_8y") else 1)

        print(f"=== 启动并行回测 ===")
        print(f"  任务数: {len(tasks_sorted)}")
        print(f"  并行 workers: {args.workers}")
        print(f"  log 目录: {LOG_DIR}")
        print(f"  调度: 8y 优先 (耗时长), 4y 后续\n")

        t_start = time.time()
        results: list[dict] = []
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(run_task, t): t for t in tasks_sorted}
            for f in as_completed(futs):
                try:
                    r = f.result()
                except Exception as e:
                    t = futs[f]
                    r = {"label": t[0], "returncode": -1, "elapsed_min": 0,
                         "error": str(e)}
                results.append(r)
                status = "✅" if r.get("returncode") == 0 else "❌"
                print(f"  {status} {r['label']:<14} rc={r.get('returncode')} "
                      f"elapsed={r.get('elapsed_min', 0):.1f}min "
                      f"log={r.get('log', 'n/a')}")

        total_min = (time.time() - t_start) / 60.0
        print(f"\n=== 全部完成 ===  挂钟 {total_min:.1f}min")

    print(f"\n=== 汇总 metrics ===")
    rows = collect_metrics()
    import pandas as pd
    df = pd.DataFrame(rows)
    cols_show = ["label", "strategy", "market", "start", "end",
                 "sharpe", "annual_ret", "max_dd", "win_rate", "n_trades", "admission"]
    cols_show = [c for c in cols_show if c in df.columns]
    print(df[cols_show].to_string(index=False))

    summary_csv = LOG_DIR / "_summary.csv"
    df.to_csv(summary_csv, index=False)
    print(f"\n汇总 → {summary_csv}")


if __name__ == "__main__":
    main()
