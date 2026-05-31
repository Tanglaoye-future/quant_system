#!/usr/bin/env python3
"""
zhuang L6-A 6y verify — 用 3y sweep 找出来的 top 2-3 winner 跑 6y (2020-2026) 双窗口验证.

读 zhuang_l6a_sweep_summary.json 自动选 top 3 + baseline 对照，跑 6y.
Winner 6y Sharpe vs baseline 1.806 才算有效改进.

用法:
  python scripts/backtest/run_l6a_verify_6y.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON = str(ROOT / "venv" / "bin" / "python")
UNIVERSE = "data/cache/universe_2022-01-01.csv"
START = "2020-01-01"
END = "2026-05-04"


def run_case(tag: str, weights: dict) -> dict:
    t0 = time.time()
    cmd = [
        PYTHON, "scripts/backtest/run_experiment_zhuang.py",
        "--tag", f"{tag}-6y",
        "--start", START, "--end", END,
        "--universe-file", UNIVERSE,
        "--accumulation-weights",
        f"ma_convergence={weights['ma']}",
        f"volume_asymmetry={weights['vol']}",
        f"price_consolidation={weights['price']}",
        f"turnover_decline={weights['turn']}",
        f"vp_divergence={weights['vp']}",
    ]
    log_path = ROOT / "data" / "backtest" / f"_exp_{tag}-6y.log"
    with open(log_path, "w", encoding="utf-8") as f:
        proc = subprocess.run(cmd, cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT,
                              env={**__import__("os").environ,
                                   "PYTHONPATH": str(ROOT / "src") + ":" + __import__("os").environ.get("PYTHONPATH", "")})
    elapsed = time.time() - t0
    summary_path = ROOT / "data" / "backtest" / f"_exp_{tag}-6y" / f"zhuang_a_share_{START}_{END}" / "experiment_summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {"error": "no summary"}
    return {"tag": tag, "elapsed_s": round(elapsed, 1), "exit_code": proc.returncode,
            "weights": weights, "summary": summary}


def main():
    # 读 3y sweep 结果
    sweep_path = ROOT / "data" / "backtest" / "zhuang_l6a_sweep_summary.json"
    if not sweep_path.exists():
        print(f"[FATAL] {sweep_path} 不存在；先跑 3y sweep")
        sys.exit(2)

    sweep_3y = json.loads(sweep_path.read_text())
    # 选 top 3 + baseline (baseline 必跑做对照)
    sorted_3y = sorted(sweep_3y,
                       key=lambda r: ((r.get("summary") or {}).get("metrics") or {}).get("sharpe_ratio", -99),
                       reverse=True)
    top3 = sorted_3y[:3]
    baseline_case = next((r for r in sweep_3y if r["tag"] == "L6A-baseline"), None)
    candidates = list({r["tag"]: r for r in [baseline_case] + top3 if r is not None}.values())

    print(f"=== L6-A 6y verify (top 3 by 3y Sharpe + baseline) ===")
    for c in candidates:
        m = (c.get("summary") or {}).get("metrics") or {}
        sh = m.get("sharpe_ratio", float("nan"))
        print(f"  - {c['tag']:<26} 3y Sharpe {sh:+.3f}")
    print()

    results = []
    for c in candidates:
        tag = c["tag"]
        weights = c["weights"]
        print(f"\n[running 6y] {tag} weights {weights}...")
        res = run_case(tag, weights)
        results.append(res)
        m = (res.get("summary") or {}).get("metrics") or {}
        sh = m.get("sharpe_ratio")
        tot = m.get("total_return")
        dd = m.get("max_drawdown")
        nt = m.get("n_trades")
        sh_s = f"{sh:+.3f}" if sh is not None else "NA"
        tot_s = f"{tot*100:+.2f}%" if tot is not None else "NA"
        dd_s = f"{dd*100:+.2f}%" if dd is not None else "NA"
        print(f"  [done] 6y Sharpe {sh_s}  Ret {tot_s}  DD {dd_s}  N {nt}  elapsed {res['elapsed_s']}s")

    # 排序
    results.sort(key=lambda r: ((r.get("summary") or {}).get("metrics") or {}).get("sharpe_ratio", -99),
                 reverse=True)
    print(f"\n=== 6y final ranking ===")
    print(f"{'rank':<5} {'tag':<26} {'6y Sharpe':>10} {'Ret%':>7} {'DD%':>7} {'N':>4}")
    summary_md = ["# zhuang L6-A 6y verify",
                  f"\n窗口: {START} → {END}",
                  "对照: 3y top 3 + baseline",
                  "",
                  "| rank | tag | 6y Sharpe | Ret% | DD% | N | ma | vol | pr | tu | vp |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(results, 1):
        m = (r.get("summary") or {}).get("metrics") or {}
        sh = m.get("sharpe_ratio", float("nan"))
        tot = m.get("total_return", float("nan"))
        dd = m.get("max_drawdown", float("nan"))
        nt = m.get("total_trades", m.get("n_trades", 0))
        w = r["weights"]
        try:
            sh_s = f"{sh:+.3f}"; tot_s = f"{tot*100:+.2f}"; dd_s = f"{dd*100:+.2f}"
        except Exception:
            sh_s = str(sh); tot_s = str(tot); dd_s = str(dd)
        print(f"  {i:<5} {r['tag']:<26} {sh_s:>10} {tot_s:>7} {dd_s:>7} {nt:>4}")
        summary_md.append(f"| {i} | {r['tag']} | {sh_s} | {tot_s} | {dd_s} | {nt} | "
                          f"{w['ma']} | {w['vol']} | {w['price']} | {w['turn']} | {w['vp']} |")

    out_md = ROOT / "data" / "backtest" / "zhuang_l6a_verify_6y_summary.md"
    out_md.write_text("\n".join(summary_md), encoding="utf-8")
    out_json = out_md.with_suffix(".json")
    out_json.write_text(json.dumps(results, indent=2, default=str, ensure_ascii=False))
    print(f"\n[出口] {out_md}")
    print(f"[出口] {out_json}")


if __name__ == "__main__":
    main()
