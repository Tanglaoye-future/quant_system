#!/usr/bin/env python3
"""
zhuang L6-A → 组合层验证 — 用 6y verify winner equity_curve 替换 v5 grid 里 zhuang 曲线，
看组合 Sharpe (v5 2.22) 是否提升 + 跨段稳健性.

读 zhuang_l6a_verify_6y_summary.json 拿 6y top winner tag → 替换 v5 zhuang path
→ 跑 v5 静态 portfolio + 5 段稳健性对比 baseline (=当前 zhuang 8y) vs L6A-winner.

用法:
  python scripts/portfolio/run_v6_zhuang_l6a_portfolio.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "portfolio"))

from run_p1_weight_grid_search import (  # type: ignore
    load_strategy_equity, load_passive_equity, metrics_from_returns,
)

TRADING_DAYS = 252

V5_WEIGHTS = {"HK_mom": 0.25, "A_mom": 0.10, "A_mr": 0.10, "zhuang": 0.40, "QQQ": 0.05, "GLD": 0.10}

# 5 资产基础路径
# ⚠️ zhuang_baseline 改用 L6-A sweep 同 universe (2496 只) 跑出的 6y baseline equity_curve，
# 不用 8y backtest 的曲线（universe 3270 只不同），避免 universe 差异污染 Δ Sharpe 解读。
PATHS = {
    "HK_mom":  ROOT / "data/backtest/equity_hk_momentum_hk_share_2018-01-01_2026-05-25/equity.csv",
    "A_mom":   ROOT / "data/backtest/equity_momentum_a_share_2018-01-01_2026-05-25/equity.csv",
    "A_mr":    ROOT / "data/backtest/mean_reversion_a_share_2018-01-01_2026-05-25/equity.csv",
    "zhuang_baseline": ROOT / "data/backtest/_exp_L6A-baseline-6y/zhuang_a_share_2020-01-01_2026-05-04/equity_curve.csv",
}

SEGMENTS = [
    ("2020 疫情",    "2020-01-02", "2020-12-31"),
    ("2021 牛/顶",   "2021-01-04", "2021-12-31"),
    ("2022 熊",      "2022-01-04", "2022-12-30"),
    ("2023-24 震荡", "2023-01-03", "2024-12-31"),
    ("2025-26 反弹", "2025-01-02", "2026-04-30"),
]


def main():
    print("=== zhuang L6-A 组合层验证 ===\n")

    # 1. 读 6y verify 结果，选 top winner
    verify_path = ROOT / "data" / "backtest" / "zhuang_l6a_verify_6y_summary.json"
    if not verify_path.exists():
        print(f"[FATAL] {verify_path} 不存在；先跑 6y verify")
        sys.exit(2)
    verify = json.loads(verify_path.read_text())
    sorted_6y = sorted(verify,
                       key=lambda r: ((r.get("summary") or {}).get("metrics") or {}).get("sharpe_ratio", -99),
                       reverse=True)
    winner = sorted_6y[0]
    winner_tag = winner["tag"]
    winner_path = ROOT / "data" / "backtest" / f"_exp_{winner_tag}-6y" / "zhuang_a_share_2020-01-01_2026-05-04" / "equity_curve.csv"
    if not winner_path.exists():
        print(f"[FATAL] winner equity_curve 不存在: {winner_path}")
        sys.exit(2)
    print(f"[1/3] L6-A 6y winner: {winner_tag}")
    m6 = (winner.get("summary") or {}).get("metrics") or {}
    print(f"      6y Sharpe {m6.get('sharpe_ratio'):+.3f} / Ret {m6.get('total_return')*100:+.2f}% / DD {m6.get('max_drawdown')*100:+.2f}%")
    print(f"      weights: {winner['weights']}")

    # 2. 加载所有资产 (zhuang 两个版本: baseline 8y + L6A-winner 6y)
    print("\n[2/3] 加载 7 资产...")
    eq_map = {}
    for n in ["HK_mom", "A_mom", "A_mr"]:
        eq_map[n] = load_strategy_equity(PATHS[n], n)
    eq_map["zhuang_baseline"] = load_strategy_equity(PATHS["zhuang_baseline"], "zhuang_baseline")
    eq_map["zhuang_L6A"] = load_strategy_equity(winner_path, "zhuang_L6A")
    for tk in ["QQQ", "GLD"]:
        eq_map[tk] = load_passive_equity(tk, "2020-01-02", "2026-04-30")

    for n, s in eq_map.items():
        print(f"  {n:<20} {len(s):>5} 行  {s.index[0].date()} → {s.index[-1].date()}")

    # 3. 对每个 zhuang 版本跑组合
    print("\n[3/3] 组合层对比...")

    def run_v5_with_zhuang(zhuang_key: str) -> tuple[dict, list[dict]]:
        df = pd.DataFrame({
            "HK_mom": eq_map["HK_mom"], "A_mom": eq_map["A_mom"], "A_mr": eq_map["A_mr"],
            "zhuang": eq_map[zhuang_key],
            "QQQ": eq_map["QQQ"], "GLD": eq_map["GLD"],
        })
        df = df.dropna()
        rets = df.pct_change().dropna()
        asset_names = list(V5_WEIGHTS.keys())
        R = rets.values
        w = np.array([V5_WEIGHTS[c] for c in asset_names])
        port = R @ w
        m_full = metrics_from_returns(port)
        seg_metrics = []
        for label, s, e in SEGMENTS:
            seg = rets[(rets.index >= s) & (rets.index <= e)]
            if len(seg) < 30:
                continue
            m_seg = metrics_from_returns(seg.values @ w)
            seg_metrics.append({"segment": label, "start": s, "end": e, **m_seg})
        return {"full": m_full, "n_days": int(len(rets)),
                "start": str(rets.index[0].date()), "end": str(rets.index[-1].date())}, seg_metrics

    base, base_segs = run_v5_with_zhuang("zhuang_baseline")
    l6a, l6a_segs = run_v5_with_zhuang("zhuang_L6A")

    print(f"\n  v5 + zhuang baseline (8y data): {base['n_days']} 天 {base['start']}~{base['end']}")
    print(f"    Sharpe {base['full']['sharpe']:+.3f} / Ann {base['full']['annual_return']*100:+.2f}% / DD {base['full']['max_drawdown']*100:+.2f}%")
    print(f"\n  v5 + zhuang L6A ({winner_tag}, 6y data): {l6a['n_days']} 天 {l6a['start']}~{l6a['end']}")
    print(f"    Sharpe {l6a['full']['sharpe']:+.3f} / Ann {l6a['full']['annual_return']*100:+.2f}% / DD {l6a['full']['max_drawdown']*100:+.2f}%")
    delta = l6a['full']['sharpe'] - base['full']['sharpe']
    flag = "✅" if delta > 0.02 else ("⚠️" if delta < -0.02 else "—")
    print(f"\n  ΔSharpe (v5+L6A vs v5+baseline): {delta:+.3f} {flag}")

    # 跨段对比
    print(f"\n=== 跨段稳健性 ===")
    print(f"{'段':<14} {'base Sharpe':>12} {'L6A Sharpe':>12} {'Δ':>8}  base DD%  L6A DD%")
    seg_compare = []
    for b, l in zip(base_segs, l6a_segs):
        d = l['sharpe'] - b['sharpe']
        print(f"  {b['segment']:<14} {b['sharpe']:>+12.3f} {l['sharpe']:>+12.3f} {d:>+8.3f}  "
              f"{b['max_drawdown']*100:>+7.2f}  {l['max_drawdown']*100:>+7.2f}")
        seg_compare.append({"segment": b['segment'], "start": b['start'], "end": b['end'],
                            "base_sharpe": b['sharpe'], "l6a_sharpe": l['sharpe'], "delta_sharpe": d,
                            "base_dd": b['max_drawdown'], "l6a_dd": l['max_drawdown']})

    # 落产物
    out_md = ROOT / "data/backtest/portfolio_v6_zhuang_l6a.md"
    md = [
        f"# v5 + zhuang L6-A ({winner_tag}) 组合层验证",
        "",
        f"L6-A winner weights: {winner['weights']}",
        "",
        "## 全窗口对比",
        "",
        f"- **v5 + zhuang baseline**: Sharpe **{base['full']['sharpe']:+.3f}** / Ann {base['full']['annual_return']*100:+.2f}% / DD {base['full']['max_drawdown']*100:+.2f}% (n={base['n_days']})",
        f"- **v5 + zhuang L6A**:     Sharpe **{l6a['full']['sharpe']:+.3f}** / Ann {l6a['full']['annual_return']*100:+.2f}% / DD {l6a['full']['max_drawdown']*100:+.2f}% (n={l6a['n_days']})",
        f"- ΔSharpe: **{delta:+.3f}** {flag}",
        "",
        "## 跨段稳健性",
        "",
        "| 段 | 区间 | base Sharpe | L6A Sharpe | Δ | base DD% | L6A DD% |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in seg_compare:
        md.append(f"| {r['segment']} | {r['start']}~{r['end']} | {r['base_sharpe']:+.3f} | "
                  f"{r['l6a_sharpe']:+.3f} | {r['delta_sharpe']:+.3f} | "
                  f"{r['base_dd']*100:+.2f} | {r['l6a_dd']*100:+.2f} |")
    out_md.write_text("\n".join(md), encoding="utf-8")
    out_json = out_md.with_suffix(".json")
    out_json.write_text(json.dumps({
        "winner_tag": winner_tag, "winner_weights": winner["weights"],
        "v5_base": base, "v5_l6a": l6a,
        "segments": seg_compare, "delta_sharpe": delta,
    }, indent=2, ensure_ascii=False, default=str))
    print(f"\n[出口] {out_md}")
    print(f"[出口] {out_json}")


if __name__ == "__main__":
    main()
