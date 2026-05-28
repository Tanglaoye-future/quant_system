#!/usr/bin/env python3
"""
P2: zhuang capacity 压测.

问题：P1 grid search 给 zhuang 40% 配比（cap binding），但 zhuang 跑中小盘庄股，
高 AUM 下市场冲击会侵蚀 alpha。本脚本量化「zhuang 能撑多少 AUM」。

模型（平方根冲击律 / Almgren）:
  对每笔交易 i:
    pos_val_base = size × entry_price          # 1M base 下的仓位市值
    sleeve = AUM_total × zhuang_weight          # zhuang 实际可用资金
    f = sleeve / 1_000_000                       # 相对 1M base 的放大倍数
    scaled_pos = pos_val_base × f
    participation_in  = scaled_pos / ADV_entry   # ADV = 20d 平均成交额(元)
    participation_out = scaled_pos / ADV_exit
    impact_one_way = Y × σ_daily × sqrt(participation)   # Y≈0.5, σ=标的日波动
    net_pnl_pct = gross_pnl_pct - impact_in - impact_out

  把 (impact_in × posfrac) 在 entry 日、(impact_out × posfrac) 在 exit 日
  从 sleeve 日收益里扣除 → 重建净值 → 重算 Sharpe / DD / 年化。

  posfrac = pos_val_base / equity_at_entry  (≈ 仓位占组合比例 3-8%)

输出: data/backtest/zhuang_capacity_p2.md + .json
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
TRADING_DAYS = 252

TRADES_CSV = ROOT / "data/backtest/zhuang_a_share_2018-01-01_2026-05-25/trades.csv"
EQUITY_CSV = ROOT / "data/backtest/zhuang_a_share_2018-01-01_2026-05-25/equity_curve.csv"
PRICES_DIR = ROOT / "data/prices"

# Almgren 平方根律系数 (经验 0.3~1.0)；取 0.5 中性偏保守
IMPACT_Y = 0.5
ADV_WINDOW = 20          # ADV 用 entry/exit 前 20 个交易日均值
VOL_WINDOW = 60          # σ_daily 用前 60 日
BREACH_PARTICIPATION = 0.25   # 单笔 > 25% ADV 视为流动性 breach（一天吃不下）

# 扫描网格
AUM_LEVELS = [1e6, 3e6, 10e6, 30e6, 100e6, 300e6, 1000e6]  # 总组合 AUM (元)
ZHUANG_WEIGHTS = [0.20, 0.40]   # 当前 vs grid 最优


def load_equity() -> pd.Series:
    df = pd.read_csv(EQUITY_CSV)
    cols = list(df.columns)
    df = df.rename(columns={cols[0]: "date"})[["date", "equity"]]
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["equity"].astype(float)


def stock_daily(code: str) -> pd.DataFrame:
    d = pd.read_csv(PRICES_DIR / f"{code}_daily.csv", parse_dates=["date"])
    d = d.sort_values("date").reset_index(drop=True)
    d["adv_rmb"] = d["volume"] * d["close"]
    d["ret"] = d["close"].pct_change()
    return d


def adv_before(d: pd.DataFrame, date: pd.Timestamp, window: int) -> float:
    sub = d[d["date"] <= date].tail(window)
    if len(sub) == 0:
        return np.nan
    return float(sub["adv_rmb"].mean())


def vol_before(d: pd.DataFrame, date: pd.Timestamp, window: int) -> float:
    sub = d[d["date"] <= date].tail(window)
    if len(sub) < 5:
        return np.nan
    return float(sub["ret"].std())


def metrics_from_daily(rets: pd.Series) -> dict:
    rets = rets.dropna()
    if len(rets) == 0:
        return dict(sharpe=0.0, annual_return=0.0, annual_vol=0.0,
                    max_drawdown=0.0, total_return=0.0)
    mu = rets.mean() * TRADING_DAYS
    sigma = rets.std() * np.sqrt(TRADING_DAYS)
    sharpe = mu / sigma if sigma > 1e-12 else 0.0
    eq = (1 + rets).cumprod()
    dd = float((eq / eq.cummax() - 1).min())
    return dict(sharpe=float(sharpe), annual_return=float(mu),
                annual_vol=float(sigma), max_drawdown=dd,
                total_return=float(eq.iloc[-1] - 1))


def main():
    print("=== P2 zhuang capacity 压测 ===\n")
    tr = pd.read_csv(TRADES_CSV, dtype={"code": str})
    tr["entry_date"] = pd.to_datetime(tr["entry_date"])
    tr["exit_date"] = pd.to_datetime(tr["exit_date"])
    tr["pos_val_base"] = tr["size"] * tr["entry_price"]
    eq = load_equity()

    # 预加载每笔交易的 ADV / σ / posfrac
    print(f"[1/3] 计算 {len(tr)} 笔交易的 ADV / σ / posfrac...")
    recs = []
    for _, t in tr.iterrows():
        d = stock_daily(t["code"])
        adv_in = adv_before(d, t["entry_date"], ADV_WINDOW)
        adv_out = adv_before(d, t["exit_date"], ADV_WINDOW)
        sigma = vol_before(d, t["entry_date"], VOL_WINDOW)
        # equity at entry (sleeve base 1M 下) → posfrac
        eq_at = eq[eq.index <= t["entry_date"]]
        equity_entry = float(eq_at.iloc[-1]) if len(eq_at) else 1_000_000.0
        posfrac = t["pos_val_base"] / equity_entry
        recs.append(dict(
            code=t["code"], entry_date=t["entry_date"], exit_date=t["exit_date"],
            gross_pnl_pct=t["pnl_pct"], pos_val_base=t["pos_val_base"],
            adv_in=adv_in, adv_out=adv_out, sigma=sigma, posfrac=posfrac,
        ))
    rt = pd.DataFrame(recs)
    # σ fallback：缺失用中位数
    rt["sigma"] = rt["sigma"].fillna(rt["sigma"].median())
    rt["adv_in"] = rt["adv_in"].fillna(rt["adv_in"].median())
    rt["adv_out"] = rt["adv_out"].fillna(rt["adv_out"].median())
    print(f"  σ_daily 中位 {rt.sigma.median()*100:.2f}%  "
          f"ADV_in 中位 {rt.adv_in.median()/1e6:.1f}M  "
          f"posfrac 中位 {rt.posfrac.median()*100:.1f}%")

    # gross 基线
    gross_rets = eq.pct_change()
    m_gross = metrics_from_daily(gross_rets)
    print(f"\n[2/3] zhuang gross (1M base): "
          f"Sharpe {m_gross['sharpe']:.3f} / Ann {m_gross['annual_return']*100:+.2f}% / "
          f"DD {m_gross['max_drawdown']*100:+.2f}% / Tot {m_gross['total_return']*100:+.1f}%")

    # 逐 (AUM, weight) 扫描
    print(f"\n[3/3] 扫描 AUM × zhuang_weight ...\n")
    scan = []
    header = (f"{'AUM':>8} {'w':>5} {'sleeve':>8} {'f':>6} "
              f"{'Sharpe':>8} {'净Sharpe':>9} {'保留%':>7} "
              f"{'净Ann%':>8} {'净DD%':>8} {'breach':>7} {'maxPart%':>9} {'cost_bps':>9}")
    print(header)
    print("-" * len(header))
    for w in ZHUANG_WEIGHTS:
        for aum in AUM_LEVELS:
            sleeve = aum * w
            f = sleeve / 1_000_000.0
            # 每笔冲击
            part_in = (rt["pos_val_base"] * f) / rt["adv_in"]
            part_out = (rt["pos_val_base"] * f) / rt["adv_out"]
            impact_in = IMPACT_Y * rt["sigma"] * np.sqrt(part_in)
            impact_out = IMPACT_Y * rt["sigma"] * np.sqrt(part_out)
            # sleeve 日收益里扣冲击：entry 日扣 impact_in×posfrac，exit 日扣 impact_out×posfrac
            drag = pd.Series(0.0, index=eq.index)
            for i, r in rt.iterrows():
                if r["entry_date"] in drag.index:
                    drag[r["entry_date"]] -= impact_in.iloc[i] * r["posfrac"]
                if r["exit_date"] in drag.index:
                    drag[r["exit_date"]] -= impact_out.iloc[i] * r["posfrac"]
            net_rets = gross_rets.add(drag, fill_value=0.0)
            m_net = metrics_from_daily(net_rets)
            # 总冲击成本 (bps of sleeve, 全周期)
            total_cost = -(drag.sum()) * 10000  # bps
            max_part = float(max(part_in.max(), part_out.max()))
            n_breach = int(((part_in > BREACH_PARTICIPATION) |
                            (part_out > BREACH_PARTICIPATION)).sum())
            retention = (m_net["sharpe"] / m_gross["sharpe"]
                         if m_gross["sharpe"] else 0.0)
            scan.append(dict(
                aum=aum, weight=w, sleeve=sleeve, f=f,
                gross_sharpe=m_gross["sharpe"], net_sharpe=m_net["sharpe"],
                sharpe_retention=retention, net_annual=m_net["annual_return"],
                net_dd=m_net["max_drawdown"], n_breach=n_breach,
                max_participation=max_part, total_cost_bps=total_cost,
            ))
            print(f"{aum/1e6:>7.0f}M {w:>5.0%} {sleeve/1e6:>7.0f}M {f:>6.0f} "
                  f"{m_gross['sharpe']:>8.3f} {m_net['sharpe']:>9.3f} "
                  f"{retention*100:>6.1f}% "
                  f"{m_net['annual_return']*100:>+7.2f} {m_net['max_drawdown']*100:>+7.2f} "
                  f"{n_breach:>7} {max_part*100:>8.1f}% {total_cost:>8.0f}")
        print()

    # 写产物
    out_md = ROOT / "data/backtest/zhuang_capacity_p2.md"
    lines = [
        "# P2 zhuang capacity 压测",
        "",
        f"模型: Almgren 平方根冲击律 impact = {IMPACT_Y} × σ_daily × sqrt(参与率)；"
        f"参与率 = 仓位市值 / 20日ADV(元)；冲击在 entry+exit 双边各扣一次。",
        "",
        f"标的: zhuang 91 笔交易 (2020-2026)，universe 50亿-2000亿市值中小盘。",
        f"σ_daily 中位 {rt.sigma.median()*100:.2f}%  ADV 中位 {rt.adv_in.median()/1e6:.1f}M  "
        f"单仓占比中位 {rt.posfrac.median()*100:.1f}%",
        "",
        f"gross 基线 (1M): Sharpe {m_gross['sharpe']:.3f} / "
        f"年化 {m_gross['annual_return']*100:+.2f}% / DD {m_gross['max_drawdown']*100:+.2f}%",
        "",
        "## 扫描表",
        "",
        "| 总AUM | zhuang权重 | sleeve | 放大f | 净Sharpe | Sharpe保留 | 净年化 | 净DD | breach笔 | 最大参与率 | 全周期冲击成本 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in scan:
        lines.append(
            f"| {s['aum']/1e6:.0f}M | {s['weight']:.0%} | {s['sleeve']/1e6:.0f}M | "
            f"{s['f']:.0f}× | {s['net_sharpe']:.3f} | {s['sharpe_retention']*100:.1f}% | "
            f"{s['net_annual']*100:+.2f}% | {s['net_dd']*100:+.2f}% | {s['n_breach']} | "
            f"{s['max_participation']*100:.1f}% | {s['total_cost_bps']:.0f} bps |"
        )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    out_md.with_suffix(".json").write_text(
        json.dumps({"gross": m_gross, "params": dict(
            impact_y=IMPACT_Y, adv_window=ADV_WINDOW, vol_window=VOL_WINDOW,
            breach=BREACH_PARTICIPATION),
            "scan": scan}, indent=2, ensure_ascii=False, default=str))
    print(f"[出口] {out_md}")


if __name__ == "__main__":
    main()
