#!/usr/bin/env python3
"""
6-asset overlay 分析（zhuang L4-combo4 后）.

之前在外部 zhuang_system 里做的分析（memory: zhuang_overlay_2026-05.md）用的是
旧 zhuang baseline 0.94，10% 配比 5→6 asset Sharpe 1.30→1.35。

现在 zhuang 提升到 1.63（L4-combo4 6y verify），重算应有更大改进。

输入资产 (2020-2026 对齐，每日收益序列):
  - HK_mom    : data/backtest/bottomup_timing_hk_share_2018-01-01_2026-05-04
  - A_mom     : data/backtest/bottomup_timing_a_share_2018-01-01_2026-05-04
  - A_mr      : data/backtest/mean_reversion_a_share_2018-01-01_2026-05-04
  - QQQ       : yfinance 被动持有
  - GLD       : yfinance 被动持有
  - zhuang    : data/backtest/_l4_verify6y-L4-combo4/zhuang_a_share_2020-01-01_2026-05-04

输出: data/backtest/zhuang_l4_overlay_combo4.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]

ASSETS = {
    "HK_mom":  ROOT / "data/backtest/bottomup_timing_hk_share_2018-01-01_2026-05-04/equity.csv",
    "A_mom":   ROOT / "data/backtest/bottomup_timing_a_share_2018-01-01_2026-05-04/equity.csv",
    "A_mr":    ROOT / "data/backtest/mean_reversion_a_share_2018-01-01_2026-05-04/equity.csv",
    "zhuang":  ROOT / "data/backtest/_l4_verify6y-L4-combo4/zhuang_a_share_2020-01-01_2026-05-04/equity_curve.csv",
}

WINDOW_START = "2020-01-02"
WINDOW_END = "2026-05-04"
TRADING_DAYS = 252


def load_strategy_equity(path: Path, label: str) -> pd.Series:
    df = pd.read_csv(path)
    cols = list(df.columns)
    if "date" in cols and "equity" in cols:
        df = df[["date", "equity"]]
    elif "Unnamed: 0" in cols and "equity" in cols:
        df = df.rename(columns={"Unnamed: 0": "date"})[["date", "equity"]]
    else:
        raise ValueError(f"{label}: unknown columns {cols}")
    df["date"] = pd.to_datetime(df["date"])
    s = df.set_index("date")["equity"].astype(float)
    s.name = label
    return s


def load_passive_equity(ticker: str) -> pd.Series:
    import yfinance as yf
    df = yf.download(ticker, start="2018-01-01", end="2026-05-15",
                     progress=False, auto_adjust=False)
    # yfinance 多列 (Close, Adj Close); 用 Adj Close 含分红
    close = df["Adj Close"] if "Adj Close" in df.columns else df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    eq = (close / close.iloc[0]) * 1_000_000  # 标准化到 1M 初始资本
    eq.name = ticker
    return eq


def metrics_from_equity(eq: pd.Series, name: str = "") -> dict:
    rets = eq.pct_change().dropna()
    if len(rets) == 0:
        return {"name": name, "sharpe": 0, "ret": 0, "dd": 0, "vol": 0}
    mu = rets.mean() * TRADING_DAYS
    sigma = rets.std() * np.sqrt(TRADING_DAYS)
    sharpe = mu / sigma if sigma > 0 else 0.0
    cum = eq / eq.iloc[0]
    dd = (cum / cum.cummax() - 1).min()
    total_ret = cum.iloc[-1] - 1
    return {
        "name": name,
        "sharpe": float(sharpe),
        "ret": float(total_ret),
        "dd": float(dd),
        "vol": float(sigma),
    }


def portfolio_equity(equity_map: dict[str, pd.Series], weights: dict[str, float]) -> pd.Series:
    """按权重组合每日 returns -> 重建 equity 曲线."""
    # 对齐每个资产到同一交易日历 (内部 join)
    df = pd.DataFrame(equity_map).dropna()
    rets = df.pct_change().dropna()
    w = np.array([weights[c] for c in rets.columns])
    w = w / w.sum()  # 归一化
    port_ret = (rets.values @ w)
    port_eq = (1 + pd.Series(port_ret, index=rets.index)).cumprod() * 1_000_000
    return port_eq


def correlation_matrix(equity_map: dict[str, pd.Series]) -> pd.DataFrame:
    df = pd.DataFrame(equity_map).dropna()
    return df.pct_change().dropna().corr()


def main():
    print("[overlay] 加载资产...", flush=True)
    assets: dict[str, pd.Series] = {}
    for name, path in ASSETS.items():
        if not path.exists():
            print(f"  [WARN] {name}: {path} 不存在，跳过", file=sys.stderr)
            continue
        assets[name] = load_strategy_equity(path, name)
        print(f"  {name}: {len(assets[name])} 天")

    for tk in ["QQQ", "GLD"]:
        assets[tk] = load_passive_equity(tk)
        print(f"  {tk}: {len(assets[tk])} 天 (yfinance)")

    # 对齐窗口
    for k in list(assets):
        s = assets[k]
        s = s[(s.index >= WINDOW_START) & (s.index <= WINDOW_END)]
        assets[k] = s

    print("\n[overlay] 单资产 metrics (2020-2026):")
    rows = [metrics_from_equity(s, k) for k, s in assets.items()]
    md_solo = pd.DataFrame(rows).to_string(index=False)
    print(md_solo, flush=True)

    print("\n[overlay] 相关性矩阵:")
    corr = correlation_matrix(assets)
    print(corr.round(3).to_string())

    # 5-asset 基线 (无 zhuang)
    five = {k: assets[k] for k in ["HK_mom", "A_mom", "A_mr", "QQQ", "GLD"]}
    # 旧权重: HK 25 / A_mom 25 / A_mr 15 / QQQ 15 / GLD 20
    w_five = {"HK_mom": 0.25, "A_mom": 0.25, "A_mr": 0.15, "QQQ": 0.15, "GLD": 0.20}
    eq_five = portfolio_equity(five, w_five)
    m_five = metrics_from_equity(eq_five, "5-asset (no zhuang)")

    print("\n[overlay] 5-asset 基线 (25/25/15/15/20):")
    print(f"  Sharpe={m_five['sharpe']:.3f}  Ret={m_five['ret']*100:+.1f}%  "
          f"DD={m_five['dd']*100:.1f}%  Vol={m_five['vol']*100:.2f}%")

    # 6-asset 扫描 zhuang 占比 (按比例稀释其他 5 个)
    print("\n[overlay] 6-asset 扫描 zhuang 占比 (其他 5 按比例稀释):")
    scan_results = []
    for z in [0.05, 0.10, 0.15, 0.20, 0.25]:
        scale = 1 - z
        w6 = {k: v * scale for k, v in w_five.items()}
        w6["zhuang"] = z
        six = dict(five); six["zhuang"] = assets["zhuang"]
        eq6 = portfolio_equity(six, w6)
        m6 = metrics_from_equity(eq6, f"+zhuang {int(z*100)}%")
        scan_results.append({"zhuang_pct": z, **m6})
        print(f"  zhuang {int(z*100):>2}%: Sharpe={m6['sharpe']:.3f}  "
              f"Ret={m6['ret']*100:+.1f}%  DD={m6['dd']*100:.1f}%  Vol={m6['vol']*100:.2f}%")

    # 写 markdown summary
    out_md = ROOT / "data/backtest/zhuang_l4_overlay_combo4.md"
    lines = [
        "# 6-asset overlay 分析 — zhuang L4-combo4 之后",
        "",
        f"窗口: {WINDOW_START} → {WINDOW_END}",
        "",
        "## 单资产 metrics",
        "",
        "| 资产 | Sharpe | 收益 | DD | 年化波动 |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['name']} | {r['sharpe']:.3f} | {r['ret']*100:+.1f}% | "
                     f"{r['dd']*100:.1f}% | {r['vol']*100:.2f}% |")
    for tk in ["QQQ", "GLD"]:
        m = metrics_from_equity(assets[tk], tk)
        lines.append(f"| {m['name']} | {m['sharpe']:.3f} | {m['ret']*100:+.1f}% | "
                     f"{m['dd']*100:.1f}% | {m['vol']*100:.2f}% |")

    lines += [
        "",
        "## 相关性矩阵 (日收益)",
        "",
        "```",
        corr.round(3).to_string(),
        "```",
        "",
        "## 5-asset 基线 (HK 25 / A_mom 25 / A_mr 15 / QQQ 15 / GLD 20)",
        "",
        f"Sharpe **{m_five['sharpe']:.3f}** / 收益 {m_five['ret']*100:+.1f}% / "
        f"DD {m_five['dd']*100:.1f}% / 年化波动 {m_five['vol']*100:.2f}%",
        "",
        "## 6-asset 扫描 (zhuang 占比 5-25%，其他按比例稀释)",
        "",
        "| zhuang% | Sharpe | 收益 | DD | 年化波动 |",
        "|---|---|---|---|---|",
    ]
    for r in scan_results:
        lines.append(f"| {int(r['zhuang_pct']*100)}% | {r['sharpe']:.3f} | "
                     f"{r['ret']*100:+.1f}% | {r['dd']*100:.1f}% | {r['vol']*100:.2f}% |")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[overlay] summary → {out_md}", flush=True)

    # json dump
    out_json = out_md.with_suffix(".json")
    out_json.write_text(json.dumps({
        "window": [WINDOW_START, WINDOW_END],
        "solo": rows + [metrics_from_equity(assets[tk], tk) for tk in ["QQQ", "GLD"]],
        "five_asset": m_five,
        "scan": scan_results,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
