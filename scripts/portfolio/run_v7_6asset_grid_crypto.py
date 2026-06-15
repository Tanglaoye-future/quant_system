#!/usr/bin/env python3
"""V7 6-asset portfolio grid search — zhuang 出局 + 加密入局.

2026-06-15 用户决策:
  GLD 10% 固定 + 加密 10% 固定 + 股市 80% 优化
  6 asset = HK_mom + A_mom + A_mr + QQQ + GLD + BTC-USD

约束:
  - GLD = 10% 固定 (不入 grid)
  - 加密 = 10% 固定 (不入 grid)  -- 用 BTC-USD 代理 IBIT (历史 2014+; IBIT 仅 2024+)
  - 股市 80% 在 HK/A_mom/A_mr/QQQ 4 块内 step=5% search
  - 单一资产 max 50% (避免过度集中)

双窗口 4y + 8y 同向 PASS 才推荐 (Backstop #2).

基准:
  v5 5-asset baseline: HK 25 / A_mom 25 / A_mr 15 / QQQ 15 / GLD 20 (无加密)
  user 提议组合: HK 35 / A_mom 20 / A_mr 10 / QQQ 15 / GLD 10 / BTC 10

输出:
  data/backtest/portfolio_v7_6asset_crypto_4Y.md + .json
  data/backtest/portfolio_v7_6asset_crypto_8Y.md + .json

用法:
  venv/bin/python scripts/portfolio/run_v7_6asset_grid_crypto.py
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
TRADING_DAYS = 252

# 资产历史曲线路径 (HK_mom 用今天跑的 06-13 截止; A_mom / A_mr 06-09 截止)
DEFAULT_PATHS = {
    "HK_mom":  ROOT / "data/backtest/equity_hk_momentum_hk_share_2018-01-01_2026-06-13/equity.csv",
    "A_mom":   ROOT / "data/backtest/equity_momentum_a_share_2018-01-01_2026-06-09/equity.csv",
    "A_mr":    ROOT / "data/backtest/mean_reversion_a_share_2018-01-01_2026-06-09/equity.csv",
}
PASSIVE_TICKERS = ["QQQ", "GLD", "BTC-USD"]

# Fixed weights (用户决策)
GLD_FIXED = 0.10
CRYPTO_FIXED = 0.10
EQUITY_BUDGET = 0.80  # 100 - 10 - 10

EQUITY_ASSETS = ["HK_mom", "A_mom", "A_mr", "QQQ"]
ALL_ASSETS = EQUITY_ASSETS + ["GLD", "BTC-USD"]

# 用户提议 baseline
USER_BASELINE = {
    "HK_mom": 0.35, "A_mom": 0.20, "A_mr": 0.10,
    "QQQ": 0.15, "GLD": 0.10, "BTC-USD": 0.10,
}

WINDOWS = [
    ("4Y", "2022-01-01", "2026-06-09"),
    ("8Y", "2018-01-01", "2026-06-09"),
]


def load_strategy_equity(path: Path, label: str) -> pd.Series:
    df = pd.read_csv(path)
    cols = list(df.columns)
    if "date" in cols and "equity" in cols:
        df = df[["date", "equity"]]
    elif cols[0] == "Unnamed: 0" or cols[0] == "":
        df = df.rename(columns={cols[0]: "date"})[["date", "equity"]]
    else:
        raise ValueError(f"{label}: unknown columns {cols}")
    df["date"] = pd.to_datetime(df["date"])
    s = df.set_index("date")["equity"].astype(float)
    s.name = label
    return s


def load_passive_equity(ticker: str, start: str, end: str) -> pd.Series:
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


def metrics_from_returns(rets: np.ndarray) -> dict:
    if len(rets) == 0:
        return dict(sharpe=0.0, annual_return=0.0, annual_vol=0.0,
                    max_drawdown=0.0, total_return=0.0)
    mu = rets.mean() * TRADING_DAYS
    sigma = rets.std() * np.sqrt(TRADING_DAYS)
    sharpe = mu / sigma if sigma > 1e-12 else 0.0
    eq = (1 + rets).cumprod()
    dd = (eq / np.maximum.accumulate(eq) - 1).min()
    total = eq[-1] - 1
    return dict(
        sharpe=float(sharpe),
        annual_return=float(mu),
        annual_vol=float(sigma),
        max_drawdown=float(dd),
        total_return=float(total),
    )


def gen_equity_grid(step: float, max_weight: float, budget: float):
    """股市 80% 内 4 资产 grid (sum = budget/step units, each in [0, max_units])."""
    units = int(round(budget / step))
    max_units = int(round(max_weight / step))
    out = []

    def rec(remaining: int, depth: int, prefix: list[int]):
        if depth == len(EQUITY_ASSETS) - 1:
            if 0 <= remaining <= max_units:
                out.append(tuple(prefix + [remaining]))
            return
        lo = max(0, remaining - max_units * (len(EQUITY_ASSETS) - depth - 1))
        hi = min(max_units, remaining)
        for u in range(lo, hi + 1):
            rec(remaining - u, depth + 1, prefix + [u])

    rec(units, 0, [])
    return np.array(out, dtype=np.float64) * step


def run_window(tag: str, start: str, end: str, step: float, max_weight: float,
               out_dir: Path) -> None:
    print(f"\n{'='*78}\n=== Window {tag}: {start} → {end} ===\n{'='*78}")

    # 加载
    eq_map: dict[str, pd.Series] = {}
    print(f"\n[1/4] 加载资产...")
    for name, path in DEFAULT_PATHS.items():
        if not path.exists():
            print(f"  [FATAL] {name}: {path} 不存在", file=sys.stderr)
            sys.exit(2)
        eq_map[name] = load_strategy_equity(path, name)
        print(f"  {name:<10} {len(eq_map[name]):>5} 行  "
              f"{eq_map[name].index[0].date()} → {eq_map[name].index[-1].date()}")
    for tk in PASSIVE_TICKERS:
        eq_map[tk] = load_passive_equity(tk, start, end)
        print(f"  {tk:<10} {len(eq_map[tk]):>5} 行  "
              f"{eq_map[tk].index[0].date()} → {eq_map[tk].index[-1].date()} (yfinance)")

    # 对齐
    print(f"\n[2/4] 对齐 {start} ~ {end} intersection...")
    df = pd.DataFrame({k: v for k, v in eq_map.items()})
    df = df[(df.index >= start) & (df.index <= end)]
    df = df.dropna()
    rets = df.pct_change().dropna()
    print(f"  对齐 {len(rets)} 天 ({rets.index[0].date()} ~ {rets.index[-1].date()})")
    asset_names = list(rets.columns)
    R = rets.values

    # 单资产 + 相关性
    print(f"\n[3/4] 单资产 metrics:")
    solo_rows = []
    for i, name in enumerate(asset_names):
        m = metrics_from_returns(R[:, i])
        solo_rows.append({"name": name, **m})
        print(f"  {name:<10} Sharpe={m['sharpe']:+.3f}  "
              f"Ann={m['annual_return']*100:+6.2f}%  "
              f"DD={m['max_drawdown']*100:+7.2f}%  "
              f"Vol={m['annual_vol']*100:5.2f}%  "
              f"Tot={m['total_return']*100:+7.1f}%")
    corr = rets.corr()
    print(f"\n相关性矩阵 (日收益):\n{corr.round(3).to_string()}")

    # User baseline
    print(f"\n[4/4] User 提议 baseline (HK 35 / A_mom 20 / A_mr 10 / QQQ 15 / GLD 10 / BTC 10):")
    w_user = np.array([USER_BASELINE[c] for c in asset_names])
    m_user = metrics_from_returns(R @ w_user)
    print(f"  Sharpe={m_user['sharpe']:+.3f}  Ann={m_user['annual_return']*100:+.2f}%  "
          f"DD={m_user['max_drawdown']*100:+.2f}%  Vol={m_user['annual_vol']*100:.2f}%  "
          f"Tot={m_user['total_return']*100:+.1f}%")

    # Grid search (股市 80% 内)
    print(f"\n[grid] step={step}, single max={max_weight}, equity budget={EQUITY_BUDGET}")
    W_eq = gen_equity_grid(step, max_weight, EQUITY_BUDGET)
    print(f"  股市部分组合数: {len(W_eq):,}")

    # 拼成完整 6-asset weights
    N = len(W_eq)
    n_assets = len(asset_names)
    W_full = np.zeros((N, n_assets))
    name_idx = {name: i for i, name in enumerate(asset_names)}
    for j, name in enumerate(EQUITY_ASSETS):
        W_full[:, name_idx[name]] = W_eq[:, j]
    W_full[:, name_idx["GLD"]] = GLD_FIXED
    W_full[:, name_idx["BTC-USD"]] = CRYPTO_FIXED

    # 验证 sum=1
    assert np.allclose(W_full.sum(axis=1), 1.0), "weights sum != 1"

    t0 = time.time()
    port_returns = R @ W_full.T  # (T, N)
    mu = port_returns.mean(axis=0) * TRADING_DAYS
    sigma = port_returns.std(axis=0) * np.sqrt(TRADING_DAYS)
    sharpe = np.where(sigma > 1e-12, mu / sigma, 0.0)
    cum = np.cumprod(1 + port_returns, axis=0)
    cummax = np.maximum.accumulate(cum, axis=0)
    dd = (cum / cummax - 1).min(axis=0)
    total = cum[-1] - 1
    print(f"  计算耗时 {time.time()-t0:.2f}s")

    results = pd.DataFrame({
        "sharpe": sharpe, "annual_return": mu, "annual_vol": sigma,
        "max_drawdown": dd, "total_return": total,
    })
    for i, name in enumerate(asset_names):
        results[name] = W_full[:, i]

    # Top 排名
    def fmt_weights(row):
        return " / ".join(f"{n}{int(round(row[n]*100))}" for n in asset_names)

    def show_top(df_sub, label, n=10):
        print(f"\n=== {label} (top {n}) ===")
        print(f"{'rk':<4} {'Sharpe':>8} {'Ann%':>7} {'DD%':>7} {'Vol%':>6} {'Tot%':>7}  权重")
        for k, (_, r) in enumerate(df_sub.head(n).iterrows(), 1):
            print(f"{k:<4} {r['sharpe']:+8.3f} {r['annual_return']*100:+7.2f} "
                  f"{r['max_drawdown']*100:+7.2f} {r['annual_vol']*100:6.2f} "
                  f"{r['total_return']*100:+7.1f}  {fmt_weights(r)}")

    top_sharpe = results.sort_values("sharpe", ascending=False)
    top_sh_dd15 = results[results.max_drawdown >= -0.15].sort_values("sharpe", ascending=False)
    top_sh_dd10 = results[results.max_drawdown >= -0.10].sort_values("sharpe", ascending=False)
    top_ret = results.sort_values("annual_return", ascending=False)
    min_dd = results.sort_values("max_drawdown", ascending=False)

    show_top(top_sharpe, f"{tag} Top 10 by Sharpe (无 DD 约束)")
    show_top(top_sh_dd15, f"{tag} Top 10 by Sharpe @ DD >= -15%")
    show_top(top_sh_dd10, f"{tag} Top 10 by Sharpe @ DD >= -10%")
    show_top(top_ret, f"{tag} Top 10 by Annual Return")
    show_top(min_dd, f"{tag} Top 10 by Min Drawdown")

    # 写产物
    out_md = out_dir / f"portfolio_v7_6asset_crypto_{tag}.md"
    out_json = out_md.with_suffix(".json")

    def df_to_md(df_sub, title, n=10):
        lines = [f"\n## {title}", "",
                 "| rk | Sharpe | Ann% | DD% | Vol% | Tot% | " +
                 " | ".join(asset_names) + " |",
                 "|---|" + "|".join(["---"] * (5 + len(asset_names) + 1)) + "|"]
        for k, (_, r) in enumerate(df_sub.head(n).iterrows(), 1):
            ws = " | ".join(f"{int(round(r[n]*100))}%" for n in asset_names)
            lines.append(f"| {k} | {r['sharpe']:+.3f} | "
                         f"{r['annual_return']*100:+.2f} | "
                         f"{r['max_drawdown']*100:+.2f} | "
                         f"{r['annual_vol']*100:.2f} | "
                         f"{r['total_return']*100:+.1f} | {ws} |")
        return "\n".join(lines)

    lines = [
        f"# V7 6-asset grid (zhuang 出 / 加密入) [{tag}]",
        "",
        f"窗口: {rets.index[0].date()} → {rets.index[-1].date()} ({len(rets)} 天)",
        f"step={step}  单一 cap={max_weight*100:.0f}%  组合数={len(W_eq):,}",
        f"固定: GLD={GLD_FIXED*100:.0f}%, 加密 (BTC-USD 代理 IBIT)={CRYPTO_FIXED*100:.0f}%",
        f"股市 budget={EQUITY_BUDGET*100:.0f}% 分到 HK_mom / A_mom / A_mr / QQQ",
        "",
        "## 单资产 metrics",
        "",
        "| 资产 | Sharpe | 年化 | DD | 年化波动 | 总收益 |",
        "|---|---|---|---|---|---|",
    ]
    for r in solo_rows:
        lines.append(
            f"| {r['name']} | {r['sharpe']:+.3f} | "
            f"{r['annual_return']*100:+.2f}% | "
            f"{r['max_drawdown']*100:+.2f}% | "
            f"{r['annual_vol']*100:.2f}% | "
            f"{r['total_return']*100:+.1f}% |"
        )
    lines += [
        "",
        "## 相关性矩阵 (日收益)",
        "",
        "```",
        corr.round(3).to_string(),
        "```",
        "",
        f"## User 提议 baseline (HK 35 / A_mom 20 / A_mr 10 / QQQ 15 / GLD 10 / BTC 10)",
        "",
        f"Sharpe **{m_user['sharpe']:+.3f}** / Ann {m_user['annual_return']*100:+.2f}% / "
        f"DD {m_user['max_drawdown']*100:+.2f}% / Vol {m_user['annual_vol']*100:.2f}% / "
        f"Tot {m_user['total_return']*100:+.1f}%",
    ]
    lines.append(df_to_md(top_sharpe, "Top 10 by Sharpe (无 DD 约束)"))
    lines.append(df_to_md(top_sh_dd15, "Top 10 by Sharpe @ DD >= -15%"))
    lines.append(df_to_md(top_sh_dd10, "Top 10 by Sharpe @ DD >= -10%"))
    lines.append(df_to_md(top_ret, "Top 10 by Annual Return"))
    lines.append(df_to_md(min_dd, "Top 10 by Min Drawdown"))
    out_md.write_text("\n".join(lines), encoding="utf-8")

    out_json.write_text(json.dumps({
        "window": tag, "start": str(rets.index[0].date()), "end": str(rets.index[-1].date()),
        "n_days": len(rets),
        "step": step, "max_weight": max_weight,
        "gld_fixed": GLD_FIXED, "crypto_fixed": CRYPTO_FIXED,
        "equity_budget": EQUITY_BUDGET,
        "solo": solo_rows,
        "corr": corr.to_dict(),
        "user_baseline": {"weights": USER_BASELINE, "metrics": m_user},
        "top_sharpe": top_sharpe.head(20).to_dict(orient="records"),
        "top_sharpe_dd15": top_sh_dd15.head(20).to_dict(orient="records"),
        "top_sharpe_dd10": top_sh_dd10.head(20).to_dict(orient="records"),
        "top_return": top_ret.head(20).to_dict(orient="records"),
        "min_dd": min_dd.head(20).to_dict(orient="records"),
    }, indent=2, default=str), encoding="utf-8")

    print(f"\n输出: {out_md}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=float, default=0.05)
    ap.add_argument("--max-weight", type=float, default=0.50)
    args = ap.parse_args()

    out_dir = ROOT / "data/backtest"
    out_dir.mkdir(parents=True, exist_ok=True)

    for tag, start, end in WINDOWS:
        run_window(tag, start, end, args.step, args.max_weight, out_dir)


if __name__ == "__main__":
    main()
