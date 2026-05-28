#!/usr/bin/env python3
"""
P1: 6-asset portfolio weight grid search.

读 6 个策略 / 资产的 daily equity curve，在 weight grid 上求多目标最优组合：
  (1) 最高 Sharpe
  (2) 最高 Sharpe @ max_drawdown >= -10%
  (3) 最高 Sharpe @ max_drawdown >= -7%
  (4) 最低 max_drawdown
  (5) 最高 annualized return

资产清单（默认）:
  - HK_mom    : equity_hk_momentum 8y backtest
  - A_mom     : equity_momentum (L8D2 / L9-A) 8y backtest
  - A_mr      : mean_reversion 8y backtest
  - zhuang    : zhuang L5 8y backtest（起点 2020）
  - QQQ       : yfinance 被动持有
  - GLD       : yfinance 被动持有

窗口受 zhuang 限制必须 ≥ 2020-01-02。

用法:
  python scripts/portfolio/run_p1_weight_grid_search.py
  python scripts/portfolio/run_p1_weight_grid_search.py --tag L9A --a-mom-path <path>
  python scripts/portfolio/run_p1_weight_grid_search.py --step 0.025 --max-weight 0.45
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

DEFAULT_PATHS = {
    "HK_mom":  ROOT / "data/backtest/equity_hk_momentum_hk_share_2018-01-01_2026-05-25/equity.csv",
    "A_mom":   ROOT / "data/backtest/equity_momentum_a_share_2018-01-01_2026-05-25/equity.csv",
    "A_mr":    ROOT / "data/backtest/mean_reversion_a_share_2018-01-01_2026-05-04/equity.csv",
    "zhuang":  ROOT / "data/backtest/zhuang_a_share_2018-01-01_2026-05-25/equity_curve.csv",
}

# 当前实盘 (deployment_plan_2026-05.md v4): HK 20 / A_mom 20 / A_mr 10 / zhuang 20 / QQQ 15 / GLD 15
CURRENT_WEIGHTS = {
    "HK_mom":  0.20,
    "A_mom":   0.20,
    "A_mr":    0.10,
    "zhuang":  0.20,
    "QQQ":     0.15,
    "GLD":     0.15,
}

# 默认窗口受 zhuang 起点限制
DEFAULT_WINDOW_START = "2020-01-02"
DEFAULT_WINDOW_END = "2026-04-30"


def load_strategy_equity(path: Path, label: str) -> pd.Series:
    """读 backtest equity.csv (date, equity, benchmark) 或 zhuang 的 (unnamed, equity)."""
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
    """yfinance Adj Close (含分红) 归一化到 1M."""
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


def gen_weight_grid(n_assets: int, step: float, max_weight: float):
    """生成所有 sum=1, w_i ∈ {0, step, ..., max_weight} 的权重组合."""
    units = int(round(1.0 / step))
    max_units = int(round(max_weight / step))
    # compositions: w1+w2+...+wn=units, 0<=wi<=max_units
    # 用 itertools 暴力（n=6, units=20, max=8 → 几千个，秒级）
    out = []
    # 递归生成
    def rec(remaining: int, depth: int, prefix: list[int]):
        if depth == n_assets - 1:
            if 0 <= remaining <= max_units:
                out.append(tuple(prefix + [remaining]))
            return
        lo = max(0, remaining - max_units * (n_assets - depth - 1))
        hi = min(max_units, remaining)
        for u in range(lo, hi + 1):
            rec(remaining - u, depth + 1, prefix + [u])
    rec(units, 0, [])
    weights = np.array(out, dtype=np.float64) * step
    return weights  # shape (N, n_assets)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="L8D2",
                    help="输出文件名标识（区分 L8D2 / L9A 对照）")
    ap.add_argument("--a-mom-path", default=None,
                    help="覆盖 A_mom equity.csv 路径（默认 L8D2 era）")
    ap.add_argument("--window-start", default=DEFAULT_WINDOW_START)
    ap.add_argument("--window-end", default=DEFAULT_WINDOW_END)
    ap.add_argument("--step", type=float, default=0.05,
                    help="权重步长 (默认 0.05 = 5pct)")
    ap.add_argument("--max-weight", type=float, default=0.40,
                    help="单资产最大权重 (默认 0.40 = 40pct, 避免过度集中)")
    args = ap.parse_args()

    paths = dict(DEFAULT_PATHS)
    if args.a_mom_path:
        paths["A_mom"] = Path(args.a_mom_path)

    print(f"=== P1 grid search [{args.tag}] ===")
    print(f"  window: {args.window_start} → {args.window_end}")
    print(f"  step:   {args.step:.3f}  max_weight: {args.max_weight:.2f}")
    print()

    # 1. 加载 6 资产
    print("[1/4] 加载资产 equity curves...")
    eq_map: dict[str, pd.Series] = {}
    for name, path in paths.items():
        if not path.exists():
            print(f"  [FATAL] {name}: {path} 不存在", file=sys.stderr)
            sys.exit(2)
        eq_map[name] = load_strategy_equity(path, name)
        print(f"  {name:<10} {len(eq_map[name]):>5} 行  "
              f"{eq_map[name].index[0].date()} → {eq_map[name].index[-1].date()}")

    for tk in ["QQQ", "GLD"]:
        eq_map[tk] = load_passive_equity(tk, args.window_start, args.window_end)
        print(f"  {tk:<10} {len(eq_map[tk]):>5} 行  "
              f"{eq_map[tk].index[0].date()} → {eq_map[tk].index[-1].date()} (yfinance)")

    # 2. 对齐窗口 + intersection 日期
    print(f"\n[2/4] 对齐到 {args.window_start} ~ {args.window_end} 交易日 intersection...")
    df = pd.DataFrame({k: v for k, v in eq_map.items()})
    df = df[(df.index >= args.window_start) & (df.index <= args.window_end)]
    df = df.dropna()  # intersection
    rets = df.pct_change().dropna()
    print(f"  对齐后 {len(rets)} 个交易日 ({rets.index[0].date()} ~ {rets.index[-1].date()})")
    asset_names = list(rets.columns)
    R = rets.values  # shape (T, n_assets)

    # 3. 单资产 metrics + 相关性
    print("\n[3/4] 单资产 metrics:")
    solo_rows = []
    for i, name in enumerate(asset_names):
        m = metrics_from_returns(R[:, i])
        solo_rows.append({"name": name, **m})
        print(f"  {name:<10} Sharpe={m['sharpe']:+.3f}  "
              f"Ann={m['annual_return']*100:+.2f}%  "
              f"DD={m['max_drawdown']*100:+.2f}%  "
              f"Vol={m['annual_vol']*100:.2f}%  "
              f"Tot={m['total_return']*100:+.1f}%")

    corr = rets.corr()
    print("\n相关性矩阵 (日收益):")
    print(corr.round(3).to_string())

    # 4. 当前权重 baseline
    print(f"\n[4/4] 当前实盘权重 baseline (HK 20 / A_mom 20 / A_mr 10 / zhuang 20 / QQQ 15 / GLD 15):")
    w_cur = np.array([CURRENT_WEIGHTS[c] for c in asset_names])
    port_ret_cur = R @ w_cur
    m_cur = metrics_from_returns(port_ret_cur)
    print(f"  Sharpe={m_cur['sharpe']:+.3f}  "
          f"Ann={m_cur['annual_return']*100:+.2f}%  "
          f"DD={m_cur['max_drawdown']*100:+.2f}%  "
          f"Vol={m_cur['annual_vol']*100:.2f}%  "
          f"Tot={m_cur['total_return']*100:+.1f}%")

    # 5. Grid search
    print(f"\n[grid] 生成权重组合 (step={args.step}, max={args.max_weight})...")
    t0 = time.time()
    W = gen_weight_grid(len(asset_names), args.step, args.max_weight)
    print(f"  组合数: {len(W):,}  生成耗时 {time.time()-t0:.2f}s")

    print("  计算组合 metrics...")
    t1 = time.time()
    port_returns = R @ W.T  # shape (T, N)
    # vectorized metrics
    mu = port_returns.mean(axis=0) * TRADING_DAYS
    sigma = port_returns.std(axis=0) * np.sqrt(TRADING_DAYS)
    sharpe = np.where(sigma > 1e-12, mu / sigma, 0.0)
    # drawdown loop (向量化版)
    cum = np.cumprod(1 + port_returns, axis=0)
    cummax = np.maximum.accumulate(cum, axis=0)
    dd = (cum / cummax - 1).min(axis=0)
    total = cum[-1] - 1
    print(f"  计算耗时 {time.time()-t1:.2f}s")

    results = pd.DataFrame({
        "sharpe": sharpe,
        "annual_return": mu,
        "annual_vol": sigma,
        "max_drawdown": dd,
        "total_return": total,
    })
    for i, name in enumerate(asset_names):
        results[name] = W[:, i]

    # 6. 多目标 top
    def fmt_weights(row):
        return " / ".join(f"{name} {int(round(row[name]*100))}%"
                          for name in asset_names)

    def show_top(df_sub, label, n=10):
        print(f"\n=== {label} (top {n}) ===")
        print(f"{'rank':<5} {'Sharpe':>8} {'Ann%':>7} {'DD%':>7} {'Vol%':>7} {'Tot%':>7}  权重")
        for k, (_, r) in enumerate(df_sub.head(n).iterrows(), 1):
            print(f"{k:<5} {r['sharpe']:+8.3f} {r['annual_return']*100:+7.2f} "
                  f"{r['max_drawdown']*100:+7.2f} {r['annual_vol']*100:7.2f} "
                  f"{r['total_return']*100:+7.1f}  {fmt_weights(r)}")

    top_sharpe = results.sort_values("sharpe", ascending=False).head(20)
    top_sharpe_dd10 = results[results.max_drawdown >= -0.10].sort_values(
        "sharpe", ascending=False).head(20)
    top_sharpe_dd7 = results[results.max_drawdown >= -0.07].sort_values(
        "sharpe", ascending=False).head(20)
    top_ret = results.sort_values("annual_return", ascending=False).head(20)
    min_dd = results.sort_values("max_drawdown", ascending=False).head(20)

    show_top(top_sharpe, "Top 10 by Sharpe (无 DD 约束)")
    show_top(top_sharpe_dd10, "Top 10 by Sharpe @ DD >= -10%")
    show_top(top_sharpe_dd7,  "Top 10 by Sharpe @ DD >= -7% (institutional bar)")
    show_top(top_ret,         "Top 10 by Annual Return")
    show_top(min_dd,          "Top 10 by Min DrawDown")

    # 7. 写产物
    out_md = ROOT / f"data/backtest/portfolio_p1_{args.tag}.md"
    out_json = out_md.with_suffix(".json")

    def df_to_md(df_sub, title, n=10):
        lines = [f"\n## {title}", "",
                 "| rank | Sharpe | Ann% | DD% | Vol% | Tot% | " +
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
        f"# P1 grid search [{args.tag}]",
        "",
        f"窗口: {rets.index[0].date()} → {rets.index[-1].date()} ({len(rets)} 天)",
        f"步长: {args.step}  单资产 cap: {args.max_weight*100:.0f}%  "
        f"组合数: {len(W):,}",
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
        "## 当前实盘权重 baseline (HK 20 / A_mom 20 / A_mr 10 / zhuang 20 / QQQ 15 / GLD 15)",
        "",
        f"Sharpe **{m_cur['sharpe']:+.3f}** / Ann {m_cur['annual_return']*100:+.2f}% / "
        f"DD {m_cur['max_drawdown']*100:+.2f}% / Vol {m_cur['annual_vol']*100:.2f}% / "
        f"Tot {m_cur['total_return']*100:+.1f}%",
    ]
    lines.append(df_to_md(top_sharpe,      "Top 10 by Sharpe (无 DD 约束)"))
    lines.append(df_to_md(top_sharpe_dd10, "Top 10 by Sharpe @ DD >= -10%"))
    lines.append(df_to_md(top_sharpe_dd7,  "Top 10 by Sharpe @ DD >= -7%"))
    lines.append(df_to_md(top_ret,         "Top 10 by Annual Return"))
    lines.append(df_to_md(min_dd,          "Top 10 by Min DrawDown"))
    out_md.write_text("\n".join(lines), encoding="utf-8")

    payload = {
        "tag": args.tag,
        "window": [str(rets.index[0].date()), str(rets.index[-1].date())],
        "trading_days": int(len(rets)),
        "step": args.step,
        "max_weight": args.max_weight,
        "n_combos": int(len(W)),
        "asset_names": asset_names,
        "solo": solo_rows,
        "corr": corr.round(4).to_dict(),
        "current_weights": CURRENT_WEIGHTS,
        "current_metrics": m_cur,
        "top_sharpe": top_sharpe.head(20).to_dict(orient="records"),
        "top_sharpe_dd10": top_sharpe_dd10.head(20).to_dict(orient="records"),
        "top_sharpe_dd7":  top_sharpe_dd7.head(20).to_dict(orient="records"),
        "top_annual_ret":  top_ret.head(20).to_dict(orient="records"),
        "min_dd":          min_dd.head(20).to_dict(orient="records"),
    }
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    print(f"\n[出口] {out_md}")
    print(f"[出口] {out_json}")


if __name__ == "__main__":
    main()
