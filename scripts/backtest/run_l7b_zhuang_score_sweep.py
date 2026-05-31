#!/usr/bin/env python3
"""
zhuang L7-B: accumulation_score_entry sweep — 放宽入场阈值.

driver: L7-A 揭示 L1-E 入场太严, mean concurrent 0.5 仓位, cap 6 永不 binding (4/728 天打满).
hypothesis: 把 score 70 → 65/67 用上闲置仓位, 看能否在不显著掉 win rate 下 Sharpe 持平或微增.

baseline (yaml): score=70, pos=0.4 (L1-E)
历史参照 (3y baseline universe, 旧权重): 65+pos=0.5 → Sharpe 1.143 (L1A2);
                                          70+pos=0.4 → Sharpe 1.370 (L1-E)
本次 (新 L6-A equal weights): L7A-posmax6 (= score 70 + pos 0.4) → Sharpe 1.505 作 control

3 case 串行, 3y 窗口. winner 上 6y verify.

用法:
  python scripts/backtest/run_l7b_zhuang_score_sweep.py
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON = str(ROOT / "venv" / "bin" / "python")
UNIVERSE = "data/cache/universe_2022-01-01.csv"
START = "2022-01-01"
END = "2024-12-31"

# (tag, accumulation_score_entry, entry_price_position_min)
CASES = [
    ("L7B-score70-pos40",  70, 0.4),   # control (= L1-E, 已知 Sharpe 1.505 但重跑确保 reproducible)
    ("L7B-score67-pos40",  67, 0.4),
    ("L7B-score65-pos40",  65, 0.4),
]


def run_case(tag: str, score: int, pos: float) -> dict:
    t0 = time.time()
    cmd = [
        PYTHON, "scripts/backtest/run_experiment_zhuang.py",
        "--tag", tag,
        "--start", START, "--end", END,
        "--universe-file", UNIVERSE,
        "--strategy",
        f"accumulation_score_entry={score}",
        f"entry_price_position_min={pos}",
    ]
    log_path = ROOT / "data" / "backtest" / f"_exp_{tag}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src") + ":" + os.environ.get("PYTHONPATH", "")}
        proc = subprocess.run(cmd, cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT, env=env)
    elapsed = time.time() - t0

    summary_path = ROOT / "data" / "backtest" / f"_exp_{tag}" / f"zhuang_a_share_{START}_{END}" / "experiment_summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {"error": "no summary"}
    return {"tag": tag, "elapsed_s": round(elapsed, 1), "exit_code": proc.returncode,
            "score": score, "pos": pos, "summary": summary}


def concurrent_stats(tag: str) -> dict | None:
    """计算 trades.csv 的 mean / max concurrent positions"""
    try:
        import pandas as pd
        path = ROOT / "data" / "backtest" / f"_exp_{tag}" / f"zhuang_a_share_{START}_{END}" / "trades.csv"
        if not path.exists():
            return None
        t = pd.read_csv(path, parse_dates=["entry_date", "exit_date"])
        if t.empty:
            return None
        days = pd.date_range(t["entry_date"].min(), t["exit_date"].max(), freq="B")
        concurrent = [((t["entry_date"] <= d) & (t["exit_date"] >= d)).sum() for d in days]
        import numpy as np
        arr = np.array(concurrent)
        return {"max": int(arr.max()), "mean": round(float(arr.mean()), 2),
                "pct_cap6": round(float((arr == 6).mean()) * 100, 1),
                "pct_idle": round(float((arr == 0).mean()) * 100, 1)}
    except Exception as e:
        return {"error": str(e)}


def main():
    print(f"=== zhuang L7-B accumulation_score_entry sweep ({len(CASES)} cases, serial) ===")
    print(f"  window: {START} → {END}  universe: {UNIVERSE}")
    print(f"  weights: L6-A equal (0.20×5) [已落 yaml]")
    print(f"  position_max_count: 6 [L7-A 已证非瓶颈]")
    for c in CASES:
        print(f"  - {c[0]:<22} score={c[1]}  pos≥{c[2]}")
    print()

    t_start = time.time()
    results = []
    for c in CASES:
        print(f"\n[running] {c[0]}...")
        res = run_case(*c)
        res["concurrent"] = concurrent_stats(c[0])
        results.append(res)
        m = (res.get("summary") or {}).get("metrics") or {}
        sh = m.get("sharpe_ratio"); tot = m.get("total_return"); dd = m.get("max_drawdown")
        nt = m.get("total_trades", m.get("n_trades"))
        wr = m.get("win_rate"); pf = m.get("profit_factor")
        sh_s = f"{sh:+.3f}" if sh is not None else "NA"
        tot_s = f"{tot*100:+.2f}%" if tot is not None else "NA"
        dd_s = f"{dd*100:+.2f}%" if dd is not None else "NA"
        wr_s = f"{wr*100:.1f}%" if wr is not None else "NA"
        pf_s = f"{pf:.2f}" if pf is not None else "NA"
        cc = res["concurrent"] or {}
        print(f"  [done] {c[0]:<22} Sharpe {sh_s:>7}  Ret {tot_s:>7}  DD {dd_s:>7}  N {nt}  win {wr_s}  pf {pf_s}  elapsed {res['elapsed_s']}s")
        if cc and "error" not in cc:
            print(f"         concurrent: mean={cc['mean']} max={cc['max']} idle%={cc['pct_idle']} cap6%={cc['pct_cap6']}")

    results.sort(key=lambda r: ((r.get("summary") or {}).get("metrics") or {}).get("sharpe_ratio", -99),
                 reverse=True)
    print(f"\n=== L7-B Top Sharpe ranking ===")
    header = f"{'rank':<5} {'tag':<22} {'sc':>4} {'pos':>5} {'Sharpe':>7} {'Ret%':>7} {'DD%':>7} {'N':>4} {'win%':>6} {'pf':>5} {'cMean':>6} {'idle%':>6}"
    print(header)
    summary_md = ["# zhuang L7-B accumulation_score_entry sweep",
                  f"\n窗口: {START} → {END}", f"universe: {UNIVERSE}",
                  "权重: L6-A equal (0.20×5), position_max_count=6 (L7-A 已证非瓶颈)", "",
                  "| rank | tag | score | pos | Sharpe | Ret% | DD% | N | win% | pf | cMean | idle% |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(results, 1):
        m = (r.get("summary") or {}).get("metrics") or {}
        sh = m.get("sharpe_ratio", float("nan"))
        tot = m.get("total_return", float("nan"))
        dd = m.get("max_drawdown", float("nan"))
        nt = m.get("n_trades", m.get("total_trades", 0))
        wr = m.get("win_rate", float("nan"))
        pf = m.get("profit_factor", float("nan"))
        cc = r.get("concurrent") or {}
        try:
            sh_s = f"{sh:+.3f}"; tot_s = f"{tot*100:+.2f}"; dd_s = f"{dd*100:+.2f}"
            wr_s = f"{wr*100:.1f}"; pf_s = f"{pf:.2f}"
        except Exception:
            sh_s = str(sh); tot_s = str(tot); dd_s = str(dd); wr_s = str(wr); pf_s = str(pf)
        cmean = cc.get("mean", "NA")
        idle = cc.get("pct_idle", "NA")
        print(f"  {i:<5} {r['tag']:<22} {r['score']:>4} {r['pos']:>5} {sh_s:>7} {tot_s:>7} {dd_s:>7} {nt:>4} {wr_s:>6} {pf_s:>5} {str(cmean):>6} {str(idle):>6}")
        summary_md.append(f"| {i} | {r['tag']} | {r['score']} | {r['pos']} | {sh_s} | {tot_s} | {dd_s} | {nt} | {wr_s} | {pf_s} | {cmean} | {idle} |")

    out_md = ROOT / "data" / "backtest" / "zhuang_l7b_score_sweep_summary.md"
    out_md.write_text("\n".join(summary_md), encoding="utf-8")
    out_json = out_md.with_suffix(".json")
    out_json.write_text(json.dumps(results, indent=2, default=str, ensure_ascii=False))
    print(f"\n[出口] {out_md}")
    print(f"[出口] {out_json}")
    print(f"\n总耗时 {round((time.time()-t_start)/60, 1)} min")


if __name__ == "__main__":
    main()
