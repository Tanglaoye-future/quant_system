#!/usr/bin/env python3
"""
v6 regime overlay — 用 HS300 MA200 + HSCHK100 MA200 双 regime gate 动态切 v5 权重。

设计：
  - 每日算 regime 状态：bull (HS300>MA200 且 HSCHK100>MA200) / defensive (任一 ≤ MA200)
  - bull regime：给 A_mom / HK 多一点 (吃 beta)
  - defensive：给 zhuang / GLD 多一点 (抗跌)
  - 每月末重平衡（避免日频切换的摩擦）

步骤：
  1) 加载 6 资产 daily equity (与 P1 一致) + HS300 + HSCHK100 index
  2) 算 regime 序列 + 月度重平衡日
  3) 在 bull / defensive 两 regime 下分别 grid search 最优权重 (sub-grid)
  4) 拼接动态权重日序列 → portfolio daily return
  5) 对比 vs v5 静态 + 5 段稳健性

用法:
  python scripts/portfolio/run_v6_regime_overlay.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "portfolio"))

from run_p1_weight_grid_search import (  # type: ignore
    load_strategy_equity, load_passive_equity, metrics_from_returns, gen_weight_grid,
)

TRADING_DAYS = 252
WINDOW_START = "2020-01-02"
WINDOW_END = "2026-04-30"
STEP = 0.05
REGIME_MA_DAYS = 200

PATHS = {
    "HK_mom":  ROOT / "data/backtest/equity_hk_momentum_hk_share_2018-01-01_2026-05-25/equity.csv",
    "A_mom":   ROOT / "data/backtest/equity_momentum_a_share_2018-01-01_2026-05-25/equity.csv",
    "A_mr":    ROOT / "data/backtest/mean_reversion_a_share_2018-01-01_2026-05-25/equity.csv",
    "zhuang":  ROOT / "data/backtest/zhuang_a_share_2018-01-01_2026-05-25/equity_curve.csv",
}

# v5 静态 baseline
V5_WEIGHTS = {"HK_mom": 0.25, "A_mom": 0.10, "A_mr": 0.10, "zhuang": 0.40, "QQQ": 0.05, "GLD": 0.10}

# 各 regime 下 cap (zhuang 40% 仍 binding, capacity 约束)
CAPS = {
    "HK_mom": 0.40, "A_mom": 0.30, "A_mr": 0.20, "zhuang": 0.40, "QQQ": 0.20, "GLD": 0.25
}

SEGMENTS = [
    ("2020 疫情",       "2020-01-02", "2020-12-31"),
    ("2021 牛/顶",      "2021-01-04", "2021-12-31"),
    ("2022 熊",         "2022-01-04", "2022-12-30"),
    ("2023-24 震荡",    "2023-01-03", "2024-12-31"),
    ("2025-26 反弹",    "2025-01-02", "2026-04-30"),
]


def load_hs300_close(loader_csv: Path | None = None) -> pd.Series:
    """通过 DataLoader 拿 HS300 daily close."""
    sys.path.insert(0, str(ROOT / "src"))
    from quant_system.config import load_config
    from quant_system.strategies.equity_factor.data.loader import DataLoader
    cfg = load_config()
    loader = DataLoader(cfg.cache_dir, refresh_days=999)
    df = loader.get_index_daily("sh000300")
    s = pd.Series(df["close"].values, index=pd.to_datetime(df["date"]))
    s.name = "hs300_close"
    return s


def load_hschk100_close() -> pd.Series:
    """从 ./data/hk_prices/HSCHK100_index.csv 拿 HSCHK100 close."""
    p = ROOT / "data/hk_prices/HSCHK100_index.csv"
    df = pd.read_csv(p)
    s = pd.Series(df["close"].values, index=pd.to_datetime(df["date"]))
    s.name = "hschk100_close"
    return s


def regime_series(hs300: pd.Series, hk: pd.Series, ma_days: int = 200) -> pd.Series:
    """每日 regime 标签：bull / defensive.
       bull = HS300 close > MA200 且 HSCHK100 close > MA200
       defensive = 任一 ≤ MA200
    """
    hs_ma = hs300.rolling(ma_days).mean()
    hk_ma = hk.rolling(ma_days).mean()
    df = pd.concat({
        "hs": hs300, "hs_ma": hs_ma, "hk": hk, "hk_ma": hk_ma,
    }, axis=1).dropna()
    bull = (df["hs"] > df["hs_ma"]) & (df["hk"] > df["hk_ma"])
    labels = np.where(bull, "bull", "defensive")
    return pd.Series(labels, index=df.index, name="regime")


def monthly_rebalance_dates(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """每月最后一个交易日."""
    df = pd.DataFrame(index=index)
    df["ym"] = df.index.to_period("M")
    return df.groupby("ym").apply(lambda s: s.index.max()).tolist()


def regime_sub_grid(rets: pd.DataFrame, regime: pd.Series, asset_names: list[str],
                    label: str, caps: dict[str, float], step: float):
    """在某个 regime 子集上跑 grid search 找 max-Sharpe 权重."""
    mask = regime == label
    aligned = mask.reindex(rets.index).fillna(False)
    sub = rets[aligned]
    if len(sub) < 30:
        return None, None
    R = sub.values
    units = int(round(1.0 / step))
    cap_units = [int(round(caps[a] / step)) for a in asset_names]
    n = len(asset_names)
    out = []
    def rec(remaining: int, depth: int, prefix: list[int]):
        if depth == n - 1:
            if 0 <= remaining <= cap_units[depth]:
                out.append(tuple(prefix + [remaining]))
            return
        max_rest = sum(cap_units[depth+1:])
        lo = max(0, remaining - max_rest)
        hi = min(cap_units[depth], remaining)
        for u in range(lo, hi + 1):
            rec(remaining - u, depth + 1, prefix + [u])
    rec(units, 0, [])
    W = np.array(out, dtype=np.float64) * step
    port = R @ W.T
    mu = port.mean(axis=0) * TRADING_DAYS
    sigma = port.std(axis=0) * np.sqrt(TRADING_DAYS)
    sharpe = np.where(sigma > 1e-12, mu / sigma, 0.0)
    cum = np.cumprod(1 + port, axis=0)
    cummax = np.maximum.accumulate(cum, axis=0)
    dd = (cum / cummax - 1).min(axis=0)
    best_idx = np.argmax(sharpe)
    return {n: float(W[best_idx, i]) for i, n in enumerate(asset_names)}, {
        "sharpe": float(sharpe[best_idx]),
        "annual_return": float(mu[best_idx]),
        "annual_vol": float(sigma[best_idx]),
        "max_drawdown": float(dd[best_idx]),
        "n_days": int(len(sub)),
    }


def main():
    print(f"=== v6 regime overlay (HS300 + HSCHK100 MA{REGIME_MA_DAYS} gate) ===")
    print(f"  window: {WINDOW_START} → {WINDOW_END}  step: {STEP}\n")

    # 1. 加载 6 资产
    print("[1/5] 加载 6 资产 + 2 个 regime 指数...")
    eq_map: dict[str, pd.Series] = {}
    for name, path in PATHS.items():
        eq_map[name] = load_strategy_equity(path, name)
    for tk in ["QQQ", "GLD"]:
        eq_map[tk] = load_passive_equity(tk, WINDOW_START, WINDOW_END)

    df = pd.DataFrame({k: v for k, v in eq_map.items()})
    df = df[(df.index >= WINDOW_START) & (df.index <= WINDOW_END)].dropna()
    rets = df.pct_change().dropna()
    asset_names = list(rets.columns)
    print(f"  6 资产对齐 {len(rets)} 个交易日 ({rets.index[0].date()} → {rets.index[-1].date()})")

    # 2. Regime 序列
    print(f"\n[2/5] 算 regime 序列 (MA{REGIME_MA_DAYS})...")
    hs300 = load_hs300_close()
    hk = load_hschk100_close()
    regime = regime_series(hs300, hk, REGIME_MA_DAYS)
    regime = regime.reindex(rets.index, method="ffill").dropna()
    rets = rets.loc[regime.index]
    n_bull = int((regime == "bull").sum())
    n_def = int((regime == "defensive").sum())
    print(f"  bull 天数: {n_bull} ({n_bull/len(regime)*100:.1f}%)  defensive: {n_def} ({n_def/len(regime)*100:.1f}%)")

    # 3. v5 静态 baseline
    print(f"\n[3/5] v5 静态 baseline...")
    w_v5 = np.array([V5_WEIGHTS[c] for c in asset_names])
    port_v5 = rets.values @ w_v5
    m_v5 = metrics_from_returns(port_v5)
    print(f"  v5 全窗口: Sharpe {m_v5['sharpe']:+.3f} / Ann {m_v5['annual_return']*100:+.2f}% / "
          f"DD {m_v5['max_drawdown']*100:+.2f}%")

    # 4. 每个 regime 子集 grid search
    print(f"\n[4/5] regime 子集 grid search...")
    bull_w, bull_m = regime_sub_grid(rets, regime, asset_names, "bull", CAPS, STEP)
    def_w, def_m = regime_sub_grid(rets, regime, asset_names, "defensive", CAPS, STEP)
    print(f"\n  bull regime 最优 (in-regime metrics):")
    print(f"    Sharpe {bull_m['sharpe']:+.3f} / Ann {bull_m['annual_return']*100:+.2f}% / "
          f"DD {bull_m['max_drawdown']*100:+.2f}% / n_days {bull_m['n_days']}")
    print(f"    权重: " + " / ".join(f"{n} {int(round(bull_w[n]*100))}%" for n in asset_names))
    print(f"\n  defensive regime 最优 (in-regime metrics):")
    print(f"    Sharpe {def_m['sharpe']:+.3f} / Ann {def_m['annual_return']*100:+.2f}% / "
          f"DD {def_m['max_drawdown']*100:+.2f}% / n_days {def_m['n_days']}")
    print(f"    权重: " + " / ".join(f"{n} {int(round(def_w[n]*100))}%" for n in asset_names))

    # 5. 月末重平衡：按上月末 regime 选权重
    print(f"\n[5/5] 月末重平衡拼接动态组合...")
    rebal_dates = monthly_rebalance_dates(rets.index)
    w_daily = pd.DataFrame(0.0, index=rets.index, columns=asset_names)

    # 每月开始用上月末的 regime 决定权重
    current_w = np.array([V5_WEIGHTS[c] for c in asset_names])  # 初始 v5
    last_rebal_regime = None
    for i, dt in enumerate(rets.index):
        # 月底重平衡：用今日 regime 决定明日开始的权重
        if dt in rebal_dates:
            r = regime.loc[dt]
            if r == "bull":
                current_w = np.array([bull_w[c] for c in asset_names])
            else:
                current_w = np.array([def_w[c] for c in asset_names])
            last_rebal_regime = r
        w_daily.loc[dt] = current_w

    port_dyn = (rets.values * w_daily.values).sum(axis=1)
    m_dyn = metrics_from_returns(port_dyn)
    print(f"\n  v6 动态 全窗口: Sharpe {m_dyn['sharpe']:+.3f} / Ann {m_dyn['annual_return']*100:+.2f}% / "
          f"DD {m_dyn['max_drawdown']*100:+.2f}%")
    print(f"  ΔSharpe vs v5: {m_dyn['sharpe'] - m_v5['sharpe']:+.3f}")

    # 6. 跨段稳健性
    print(f"\n=== 跨段稳健性 (v5 vs v6 动态) ===")
    print(f"{'段':<14} {'v5 Sharpe':>10} {'v6 Sharpe':>10} {'ΔSharpe':>10}  v5 DD%   v6 DD%")
    seg_rows = []
    for label, s, e in SEGMENTS:
        seg_mask = (rets.index >= s) & (rets.index <= e)
        seg_rets = rets[seg_mask]
        if len(seg_rets) < 30:
            continue
        seg_v5 = seg_rets.values @ w_v5
        seg_dyn = (seg_rets.values * w_daily[seg_mask].values).sum(axis=1)
        m5 = metrics_from_returns(seg_v5)
        md = metrics_from_returns(seg_dyn)
        delta = md['sharpe'] - m5['sharpe']
        print(f"  {label:<14} {m5['sharpe']:>+10.3f} {md['sharpe']:>+10.3f} {delta:>+10.3f}  "
              f"{m5['max_drawdown']*100:>+6.2f} {md['max_drawdown']*100:>+6.2f}")
        seg_rows.append({"segment": label, "start": s, "end": e,
                         "v5_sharpe": m5['sharpe'], "v6_sharpe": md['sharpe'],
                         "delta_sharpe": delta,
                         "v5_dd": m5['max_drawdown'], "v6_dd": md['max_drawdown']})

    # 7. 落产物
    out_md = ROOT / "data/backtest/portfolio_v6_regime_overlay.md"
    out_json = out_md.with_suffix(".json")

    def fmt_w(w):
        return " / ".join(f"{n} {int(round(w[n]*100))}%" for n in asset_names)

    md = [
        f"# v6 regime overlay (HS300+HSCHK100 MA{REGIME_MA_DAYS} 双 gate)",
        "",
        f"窗口: {rets.index[0].date()} → {rets.index[-1].date()} ({len(rets)} 天)",
        f"bull 天数: {n_bull} ({n_bull/len(regime)*100:.1f}%) · defensive: {n_def} ({n_def/len(regime)*100:.1f}%)",
        "",
        "## 全窗口对比",
        "",
        f"- **v5 静态**: Sharpe **{m_v5['sharpe']:+.3f}** / Ann {m_v5['annual_return']*100:+.2f}% / DD {m_v5['max_drawdown']*100:+.2f}%",
        f"- **v6 动态**: Sharpe **{m_dyn['sharpe']:+.3f}** / Ann {m_dyn['annual_return']*100:+.2f}% / DD {m_dyn['max_drawdown']*100:+.2f}%",
        f"- ΔSharpe: {m_dyn['sharpe'] - m_v5['sharpe']:+.3f}",
        "",
        "## Regime 子集最优权重",
        "",
        f"### bull (in-regime sharpe {bull_m['sharpe']:+.3f}, n={bull_m['n_days']})",
        f"权重: {fmt_w(bull_w)}",
        "",
        f"### defensive (in-regime sharpe {def_m['sharpe']:+.3f}, n={def_m['n_days']})",
        f"权重: {fmt_w(def_w)}",
        "",
        "## 跨段稳健性",
        "",
        "| 段 | 区间 | v5 Sharpe | v6 Sharpe | ΔSharpe | v5 DD% | v6 DD% |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in seg_rows:
        md.append(f"| {r['segment']} | {r['start']}~{r['end']} | "
                  f"{r['v5_sharpe']:+.3f} | {r['v6_sharpe']:+.3f} | {r['delta_sharpe']:+.3f} | "
                  f"{r['v5_dd']*100:+.2f} | {r['v6_dd']*100:+.2f} |")
    out_md.write_text("\n".join(md), encoding="utf-8")

    payload = {
        "window": [str(rets.index[0].date()), str(rets.index[-1].date())],
        "trading_days": int(len(rets)),
        "regime_ma_days": REGIME_MA_DAYS,
        "n_bull": n_bull, "n_defensive": n_def,
        "v5_metrics": m_v5,
        "v6_dyn_metrics": m_dyn,
        "bull_weights": bull_w, "bull_in_regime": bull_m,
        "def_weights": def_w,   "def_in_regime": def_m,
        "v5_weights": V5_WEIGHTS,
        "segments": seg_rows,
    }
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    print(f"\n[出口] {out_md}")
    print(f"[出口] {out_json}")


if __name__ == "__main__":
    main()
