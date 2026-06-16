#!/usr/bin/env python3
"""V7 + CB 组合层叠加 PR6 — 4Y/6Y 双窗口验证.

CB sleeve 候选: 替换 A_mom / GLD / BTC-USD 比例 5/10/15%.
准入门槛: 双窗口 Sharpe 同向 ≥ v7 baseline + DD 不恶化超 3pp.

输入:
  v7 6 资产 equity.csv (HK_mom/A_mom/A_mr/QQQ/GLD/BTC-USD)
  CB equity.csv (4y: 2022-01-01_2026-05-25, 6y: 2020-01-01_2026-05-25)

输出:
  data/backtest/portfolio_v7_plus_cb_overlay.json
  打印 console 决策表

用法:
  ./venv/bin/python scripts/portfolio/run_v7_plus_cb_overlay.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TRADING_DAYS = 252

# v7 grid 资产 equity 路径
PATHS = {
    "HK_mom": ROOT / "data/backtest/equity_hk_momentum_hk_share_2018-01-01_2026-06-13/equity.csv",
    "A_mom":  ROOT / "data/backtest/equity_momentum_a_share_2018-01-01_2026-06-09/equity.csv",
    "A_mr":   ROOT / "data/backtest/mean_reversion_a_share_2018-01-01_2026-06-09/equity.csv",
}
PASSIVE = ["QQQ", "GLD", "BTC-USD"]
CB_PATH_4Y = ROOT / "data/backtest/cb_double_low_a_share_2022-01-01_2026-05-25/equity.csv"
CB_PATH_6Y = ROOT / "data/backtest/cb_double_low_a_share_2020-01-01_2026-05-25/equity.csv"

V7_BASELINE = {
    "HK_mom": 0.50, "A_mom": 0.20, "A_mr": 0.00,
    "QQQ": 0.10, "GLD": 0.10, "BTC-USD": 0.10,
}

CB_CANDIDATES: list[tuple[str, float]] = [
    ("A_mom", 0.05), ("A_mom", 0.10), ("A_mom", 0.15),
    ("GLD",   0.05), ("GLD",   0.10),
    ("BTC-USD", 0.05),
]

WINDOWS = [
    ("4Y", "2022-01-01", "2026-05-25", CB_PATH_4Y),
    ("6Y", "2020-01-01", "2026-05-25", CB_PATH_6Y),
]


def load_equity_csv(path: Path, label: str) -> pd.Series:
    """robust loader: equity / portfolio_value / 第二列任一."""
    df = pd.read_csv(path)
    cols = list(df.columns)
    date_col = "date" if "date" in cols else cols[0]
    value_col = None
    for cand in ("equity", "portfolio_value"):
        if cand in cols:
            value_col = cand
            break
    if value_col is None:
        # fallback: 第二列
        value_col = cols[1]
    df = df[[date_col, value_col]].copy()
    df.columns = ["date", "equity"]
    df["date"] = pd.to_datetime(df["date"])
    s = df.set_index("date")["equity"].astype(float)
    s.name = label
    return s


def load_passive(ticker: str, start: str, end: str) -> pd.Series:
    import yfinance as yf
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
    close = df["Adj Close"] if "Adj Close" in df.columns else df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = close.dropna()
    eq = (close / close.iloc[0]) * 1_000_000
    eq.index = pd.to_datetime(eq.index)
    eq.name = ticker
    return eq


def metrics(rets: np.ndarray) -> dict:
    if len(rets) == 0:
        return dict(sharpe=0.0, ann_return=0.0, ann_vol=0.0, max_dd=0.0, total=0.0)
    mu = rets.mean() * TRADING_DAYS
    sigma = rets.std() * np.sqrt(TRADING_DAYS)
    sharpe = mu / sigma if sigma > 1e-12 else 0.0
    eq = (1 + rets).cumprod()
    dd = (eq / np.maximum.accumulate(eq) - 1).min()
    return dict(
        sharpe=float(sharpe), ann_return=float(mu),
        ann_vol=float(sigma), max_dd=float(dd),
        total=float(eq[-1] - 1),
    )


def build_weights(replace_from: str, cb_pct: float, baseline: dict) -> dict | None:
    w = dict(baseline)
    if replace_from not in w:
        return None
    if w[replace_from] < cb_pct:
        return None  # 抽超过本身权重
    w[replace_from] -= cb_pct
    w["CB"] = cb_pct
    return w


def run_window(tag: str, start: str, end: str, cb_path: Path) -> dict:
    print(f"\n{'='*78}\n=== Window {tag} {start} → {end} ===\n{'='*78}")

    eq_map: dict[str, pd.Series] = {}
    for name, p in PATHS.items():
        if not p.exists():
            print(f"  [FATAL] {name}: {p} 不存在", file=sys.stderr)
            sys.exit(2)
        eq_map[name] = load_equity_csv(p, name)
    for tk in PASSIVE:
        eq_map[tk] = load_passive(tk, start, end)
    eq_map["CB"] = load_equity_csv(cb_path, "CB")

    # 对齐
    df = pd.DataFrame({k: v for k, v in eq_map.items()})
    df = df[(df.index >= start) & (df.index <= end)]
    df = df.dropna()
    rets = df.pct_change().dropna()
    print(f"  对齐 {len(rets)} 天 ({rets.index[0].date()} → {rets.index[-1].date()})")

    # 相关性
    print(f"\n  CB 与其它资产相关性:")
    corr = rets.corr()["CB"].drop("CB").sort_values()
    for k, v in corr.items():
        print(f"    {k:<10} {v:+.3f}")

    # baseline (v7 无 CB)
    w_base = np.array([V7_BASELINE.get(c, 0.0) for c in rets.columns])
    m_base = metrics(rets.values @ w_base)
    print(
        f"\n  v7 baseline: Sharpe={m_base['sharpe']:+.3f}  "
        f"Ret={m_base['ann_return']*100:+.2f}%  DD={m_base['max_dd']*100:+.2f}%"
    )

    # candidates
    rows = []
    for replace, cb_pct in CB_CANDIDATES:
        w = build_weights(replace, cb_pct, V7_BASELINE)
        if w is None:
            continue
        w_vec = np.array([w.get(c, 0.0) for c in rets.columns])
        m = metrics(rets.values @ w_vec)
        rows.append({
            "label": f"replace {replace} → CB {cb_pct*100:.0f}%",
            "replace_from": replace,
            "cb_pct": cb_pct,
            **m,
            "delta_sharpe": m["sharpe"] - m_base["sharpe"],
            "delta_dd_pp": (m["max_dd"] - m_base["max_dd"]) * 100,
        })

    print(f"\n  candidates (sorted by Sharpe):")
    df_out = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    for _, r in df_out.iterrows():
        flag = (
            "✅" if r["delta_sharpe"] > 0 and r["delta_dd_pp"] > -3
            else ("⚠️" if r["delta_sharpe"] > -0.05 else "❌")
        )
        print(
            f"    {flag} {r['label']:<26} "
            f"Sharpe={r['sharpe']:+.3f} (Δ{r['delta_sharpe']:+.3f}) "
            f"DD={r['max_dd']*100:+.2f}% (Δ{r['delta_dd_pp']:+.2f}pp)"
        )

    return {
        "window": tag, "start": start, "end": end, "n_days": len(rets),
        "v7_baseline": m_base, "candidates": rows,
        "corr": corr.to_dict(),
    }


def main() -> None:
    out_dir = ROOT / "data/backtest"
    results: dict = {}
    for tag, start, end, cb_path in WINDOWS:
        results[tag] = run_window(tag, start, end, cb_path)

    print(f"\n{'='*78}\n=== 双窗口同向决策 ===\n{'='*78}")
    win_4y = results["4Y"]
    win_6y = results["6Y"]
    cand_4y = {r["label"]: r for r in win_4y["candidates"]}
    cand_6y = {r["label"]: r for r in win_6y["candidates"]}
    pass_set: list[dict] = []
    for label in cand_4y:
        if label not in cand_6y:
            continue
        d4_s = cand_4y[label]["delta_sharpe"]
        d6_s = cand_6y[label]["delta_sharpe"]
        d4_dd = cand_4y[label]["delta_dd_pp"]
        d6_dd = cand_6y[label]["delta_dd_pp"]
        same_dir = (d4_s > 0 and d6_s > 0)
        dd_ok = (d4_dd > -3 and d6_dd > -3)
        flag = (
            "✅ STRONG" if same_dir and dd_ok
            else ("⚠️ SOFT  " if same_dir else "❌ FAIL  ")
        )
        print(
            f"  {flag} {label:<26} "
            f"4Y Δ{d4_s:+.3f}/{d4_dd:+.2f}pp  "
            f"6Y Δ{d6_s:+.3f}/{d6_dd:+.2f}pp"
        )
        if same_dir and dd_ok:
            pass_set.append({
                "label": label,
                "delta_sharpe_4y": d4_s, "delta_sharpe_6y": d6_s,
                "delta_dd_pp_4y": d4_dd, "delta_dd_pp_6y": d6_dd,
                "sharpe_4y": cand_4y[label]["sharpe"],
                "sharpe_6y": cand_6y[label]["sharpe"],
            })

    print(f"\n双窗口 STRONG PASS ({len(pass_set)} 个):")
    for p in pass_set:
        print(f"  {p['label']:<26} 4y Sharpe={p['sharpe_4y']:+.3f}  6y Sharpe={p['sharpe_6y']:+.3f}")
    if not pass_set:
        print("  ⚠️ 0 个 — CB sleeve 在 v7 框架下无组合层增量；写 falsified memory 归档.")

    payload = {
        "v7_baseline_weights": V7_BASELINE,
        "cb_candidates": [
            {"replace_from": r, "cb_pct": p} for r, p in CB_CANDIDATES
        ],
        "windows": results,
        "strong_pass": pass_set,
    }
    json_path = out_dir / "portfolio_v7_plus_cb_overlay.json"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\nJSON → {json_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
