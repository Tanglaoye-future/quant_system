#!/usr/bin/env python3
"""
zhuang L7-A: position_max_count sweep — 同时持仓上限 hypothesis 测试.

baseline (config): position_max_count=6
L1-D-pos8 (旧实验, 在 baseline 入场下) Sharpe 0.928 弱
本次重测 L1-E (pos=0.4 + score=70) 入场后, max_pos ∈ {6, 8, 10} 联调

3 case 串行跑（避免 yaml + output dir race），3y 窗口 (2022-2024).
winner 上 6y verify (2020-2026-05) 双窗口.

用法:
  python scripts/backtest/run_l7a_zhuang_posmax_sweep.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON = str(ROOT / "venv" / "bin" / "python")
UNIVERSE = "data/cache/universe_2022-01-01.csv"   # 稳定 universe (L4/L5/L6 同一份)
START = "2022-01-01"
END = "2024-12-31"

CASES = [
    # tag                  position_max_count
    ("L7A-posmax6",         6),    # baseline
    ("L7A-posmax8",         8),
    ("L7A-posmax10",       10),
]


def run_case(tag: str, posmax: int) -> dict:
    t0 = time.time()
    cmd = [
        PYTHON, "scripts/backtest/run_experiment_zhuang.py",
        "--tag", tag,
        "--start", START, "--end", END,
        "--universe-file", UNIVERSE,
        "--strategy", f"position_max_count={posmax}",
    ]
    log_path = ROOT / "data" / "backtest" / f"_exp_{tag}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src") + ":" + os.environ.get("PYTHONPATH", "")}
        proc = subprocess.run(cmd, cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT, env=env)
    elapsed = time.time() - t0

    summary_path = ROOT / "data" / "backtest" / f"_exp_{tag}" / f"zhuang_a_share_{START}_{END}" / "experiment_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())
    else:
        summary = {"error": "no summary"}
    return {"tag": tag, "elapsed_s": round(elapsed, 1), "exit_code": proc.returncode,
            "position_max_count": posmax, "summary": summary}


def main():
    print(f"=== zhuang L7-A position_max_count sweep ({len(CASES)} cases, serial) ===")
    print(f"  window: {START} → {END}  universe: {UNIVERSE}")
    print(f"  entry: L1-E (entry_price_position_min=0.4 + accumulation_score_entry=70) [已落 yaml]")
    print(f"  weights: L6-A equal (0.20×5) [已落 yaml]")
    for c in CASES:
        print(f"  - {c[0]:<22} position_max_count={c[1]}")
    print()

    t_start = time.time()
    results = []
    for c in CASES:
        print(f"\n[running] {c[0]}...")
        res = run_case(*c)
        results.append(res)
        m = (res.get("summary") or {}).get("metrics") or {}
        sh = m.get("sharpe_ratio")
        tot = m.get("total_return")
        dd = m.get("max_drawdown")
        nt = m.get("total_trades", m.get("n_trades"))
        sh_s = f"{sh:+.3f}" if sh is not None else "NA"
        tot_s = f"{tot*100:+.2f}%" if tot is not None else "NA"
        dd_s = f"{dd*100:+.2f}%" if dd is not None else "NA"
        print(f"  [done] {c[0]:<22} Sharpe {sh_s:>7}  Ret {tot_s:>7}  DD {dd_s:>7}  N {nt}  elapsed {res['elapsed_s']}s")

    results.sort(key=lambda r: ((r.get("summary") or {}).get("metrics") or {}).get("sharpe_ratio", -99),
                 reverse=True)
    print(f"\n=== L7-A Top Sharpe ranking ===")
    print(f"{'rank':<5} {'tag':<22} {'pos':>4} {'Sharpe':>7} {'Ret%':>7} {'DD%':>7} {'N':>4}")
    summary_md = ["# zhuang L7-A position_max_count sweep",
                  f"\n窗口: {START} → {END}", f"universe: {UNIVERSE}",
                  "入场: L1-E (pos≥0.4 + score≥70)  权重: L6-A equal (0.20×5)", "",
                  "| rank | tag | pos | Sharpe | Ret% | DD% | N |",
                  "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(results, 1):
        m = (r.get("summary") or {}).get("metrics") or {}
        sh = m.get("sharpe_ratio", float("nan"))
        tot = m.get("total_return", float("nan"))
        dd = m.get("max_drawdown", float("nan"))
        nt = m.get("n_trades", m.get("total_trades", 0))
        pos = r["position_max_count"]
        try:
            sh_s = f"{sh:+.3f}"
            tot_s = f"{tot*100:+.2f}"
            dd_s = f"{dd*100:+.2f}"
        except Exception:
            sh_s = str(sh); tot_s = str(tot); dd_s = str(dd)
        print(f"  {i:<5} {r['tag']:<22} {pos:>4} {sh_s:>7} {tot_s:>7} {dd_s:>7} {nt:>4}")
        summary_md.append(f"| {i} | {r['tag']} | {pos} | {sh_s} | {tot_s} | {dd_s} | {nt} |")

    out_md = ROOT / "data" / "backtest" / "zhuang_l7a_posmax_sweep_summary.md"
    out_md.write_text("\n".join(summary_md), encoding="utf-8")
    out_json = out_md.with_suffix(".json")
    out_json.write_text(json.dumps(results, indent=2, default=str, ensure_ascii=False))
    print(f"\n[出口] {out_md}")
    print(f"[出口] {out_json}")
    print(f"\n总耗时 {round((time.time()-t_start)/60, 1)} min")


if __name__ == "__main__":
    main()
