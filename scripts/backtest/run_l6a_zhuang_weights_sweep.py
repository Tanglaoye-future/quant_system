#!/usr/bin/env python3
"""
zhuang L6-A: accumulation_weights sweep — 5 维信号权重 hypothesis 测试.

baseline (config): ma=0.20, vol=0.30, price=0.20, turn=0.15, vp=0.15

6 case + baseline = 7 case，串行跑（避免 yaml + output dir race，参 v2 sweep 教训）.
3y 窗口 (2022-2024)，winner 上 6y verify (2020-2026).

用法:
  python scripts/backtest/run_l6a_zhuang_weights_sweep.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON = str(ROOT / "venv" / "bin" / "python")
UNIVERSE = "data/cache/universe_2022-01-01.csv"   # 用稳定 universe (L4/L5 sweep 同一份)
START = "2022-01-01"
END = "2024-12-31"

# 6 hypothesis + baseline
# 每 case 5 维 sum = 1.0
CASES = [
    # tag                        ma    vol   price  turn  vp
    ("L6A-baseline",            0.20, 0.30, 0.20,  0.15, 0.15),
    ("L6A-strong-volume",       0.15, 0.40, 0.20,  0.15, 0.10),
    ("L6A-strong-turnover",     0.15, 0.30, 0.20,  0.25, 0.10),
    ("L6A-strong-conso",        0.15, 0.25, 0.30,  0.20, 0.10),
    ("L6A-strong-ma",           0.30, 0.25, 0.20,  0.15, 0.10),
    ("L6A-weak-vp",             0.20, 0.35, 0.20,  0.20, 0.05),
    ("L6A-equal",               0.20, 0.20, 0.20,  0.20, 0.20),
]


def verify_weights_sum(c):
    """sum=1 校验"""
    tag, ma, vol, pr, tu, vp = c
    s = ma + vol + pr + tu + vp
    assert abs(s - 1.0) < 1e-9, f"{tag} weights sum {s} != 1.0"


def run_case(tag: str, ma: float, vol: float, pr: float, tu: float, vp: float) -> dict:
    t0 = time.time()
    cmd = [
        PYTHON, "scripts/backtest/run_experiment_zhuang.py",
        "--tag", tag,
        "--start", START, "--end", END,
        "--universe-file", UNIVERSE,
        "--accumulation-weights",
        f"ma_convergence={ma}",
        f"volume_asymmetry={vol}",
        f"price_consolidation={pr}",
        f"turnover_decline={tu}",
        f"vp_divergence={vp}",
    ]
    log_path = ROOT / "data" / "backtest" / f"_exp_{tag}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        proc = subprocess.run(cmd, cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT,
                              env={**__import__("os").environ,
                                   "PYTHONPATH": str(ROOT / "src") + ":" + __import__("os").environ.get("PYTHONPATH", "")})
    elapsed = time.time() - t0
    # 读 experiment_summary.json
    summary_path = ROOT / "data" / "backtest" / f"_exp_{tag}" / f"zhuang_a_share_{START}_{END}" / "experiment_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())
    else:
        summary = {"error": "no summary"}
    return {"tag": tag, "elapsed_s": round(elapsed, 1), "exit_code": proc.returncode,
            "weights": {"ma": ma, "vol": vol, "price": pr, "turn": tu, "vp": vp},
            "summary": summary}


def main():
    for c in CASES:
        verify_weights_sum(c)

    print(f"=== zhuang L6-A accumulation_weights sweep ({len(CASES)} cases, serial) ===")
    print(f"  window: {START} → {END}  universe: {UNIVERSE}")
    for c in CASES:
        tag = c[0]
        print(f"  - {tag:<26} ma={c[1]} vol={c[2]} price={c[3]} turn={c[4]} vp={c[5]}")
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
        print(f"  [done] {c[0]:<26} Sharpe {sh_s:>7}  Ret {tot_s:>7}  DD {dd_s:>7}  N {nt}  elapsed {res['elapsed_s']}s")

    # 汇总
    results.sort(key=lambda r: ((r.get("summary") or {}).get("metrics") or {}).get("sharpe_ratio", -99),
                 reverse=True)
    print(f"\n=== L6-A Top Sharpe ranking ===")
    print(f"{'rank':<5} {'tag':<26} {'Sharpe':>7} {'Ret%':>7} {'DD%':>7} {'N':>4} ma/vol/pr/tu/vp")
    summary_md = ["# zhuang L6-A accumulation_weights sweep",
                  f"\n窗口: {START} → {END}", f"universe: {UNIVERSE}", "",
                  "| rank | tag | Sharpe | Ret% | DD% | N | ma | vol | pr | tu | vp |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(results, 1):
        m = (r.get("summary") or {}).get("metrics") or {}
        sh = m.get("sharpe_ratio", float("nan"))
        tot = m.get("total_return", float("nan"))
        dd = m.get("max_drawdown", float("nan"))
        nt = m.get("n_trades", 0)
        w = r["weights"]
        try:
            sh_s = f"{sh:+.3f}" if sh is not None else "NA"
            tot_s = f"{tot*100:+.2f}" if tot is not None else "NA"
            dd_s = f"{dd*100:+.2f}" if dd is not None else "NA"
        except Exception:
            sh_s = str(sh); tot_s = str(tot); dd_s = str(dd)
        wstr = f"{w['ma']}/{w['vol']}/{w['price']}/{w['turn']}/{w['vp']}"
        print(f"  {i:<5} {r['tag']:<26} {sh_s:>7} {tot_s:>7} {dd_s:>7} {nt:>4}  {wstr}")
        summary_md.append(f"| {i} | {r['tag']} | {sh_s} | {tot_s} | {dd_s} | {nt} | "
                          f"{w['ma']} | {w['vol']} | {w['price']} | {w['turn']} | {w['vp']} |")

    out_md = ROOT / "data" / "backtest" / "zhuang_l6a_sweep_summary.md"
    out_md.write_text("\n".join(summary_md), encoding="utf-8")
    out_json = out_md.with_suffix(".json")
    out_json.write_text(json.dumps(results, indent=2, default=str, ensure_ascii=False))
    print(f"\n[出口] {out_md}")
    print(f"[出口] {out_json}")
    print(f"\n总耗时 {round((time.time()-t_start)/60, 1)} min")


if __name__ == "__main__":
    main()
