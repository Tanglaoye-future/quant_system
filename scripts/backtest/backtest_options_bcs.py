#!/usr/bin/env python3
"""
Options Bull Call Spread (QQQ) — Black-Scholes 近似回测.

⚠️ 这是近似基线，不是真实期权链回测。
   缺历史期权链（行权价/各档 IV/买卖价），无法精确回测。
   本脚本用「真实历史信号 + BS 定价」近似 BCS 的收益分布，给一个有数据支撑的基线。

信号层（忠实复刻 live 策略 config/strategies/options_bull_call_spread.yaml）:
  - 动量门：QQQ close > MA200 且 RSI14 ∈ [50,78] 且 3月动量 > 0
  - IV 门：IVR = (VXN - 52w低)/(52w高 - 52w低)，入场要 IVR < 50（LOW/MID mode，HIGH 跳过）
  - bullish 且 IV 门通过 且 当前无持仓 → 开一个 BCS

BCS 结构（BS 反推行权价，r=0，无股息）:
  - DTE 入场 50（config 区间 40-65 中点），long delta 0.45 / short delta 0.27
  - premium = C(K_long) - C(K_short)，width = K_short - K_long
出场:
  - 价差 mark ≥ 2× premium → 止盈 (config profit_target_mult)
  - 价差 mark ≤ 0.5× premium → 止损 (config stop_loss_mult)
  - DTE 到期 → 结算内在价值
sizing: 单标的一次一仓；每笔投入 premium = NAV × premium_pct（BCS 最大亏损 = premium）。

数据: yfinance QQQ + ^VXN（2017 起，留 MA200 预热）。

局限（明确标注）:
  1. VXN 当 flat IV 喂两腿 → 忽略 vol skew（真实 OTM 短腿更便宜 → 真实 premium 略低）
  2. 无真实 bid/ask；用 round_trip_haircut 近似（默认 2% of premium）
  3. BS 连续行权价 vs 实际离散挂牌
  4. r=0 / 无股息（QQQ ~0.5% 收益率，短期影响小）
  5. 固定 50 DTE 入场 + 固定 sizing
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TRADING_DAYS = 252


# ---- 正态分布 Φ 与 Φ⁻¹（无 scipy）----
def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Acklam 逆正态 CDF 近似（误差 < 1.15e-9）."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def bs_call(S: float, K: float, iv: float, T: float) -> float:
    """BS 看涨期权价（r=0，无股息）."""
    if T <= 0 or iv <= 0:
        return max(0.0, S - K)
    d1 = (math.log(S / K) + 0.5 * iv * iv * T) / (iv * math.sqrt(T))
    d2 = d1 - iv * math.sqrt(T)
    return S * norm_cdf(d1) - K * norm_cdf(d2)


def strike_from_delta(S: float, delta: float, iv: float, T: float) -> float:
    """给定目标 call delta = N(d1) 反推行权价（r=0）."""
    d1 = norm_ppf(delta)
    return S * math.exp(0.5 * iv * iv * T - d1 * iv * math.sqrt(T))


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rsi = np.where(avg_loss == 0, 100.0, 100.0 - 100.0 / (1.0 + avg_gain / avg_loss))
    return pd.Series(rsi, index=close.index)


def load_yf(ticker: str, start: str, end: str) -> pd.Series:
    import yfinance as yf
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    close = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    s = close.dropna()
    s.index = pd.to_datetime(s.index)
    return s


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
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--end", default="2026-05-25")
    ap.add_argument("--dte-entry", type=int, default=50)
    ap.add_argument("--long-delta", type=float, default=0.45)
    ap.add_argument("--short-delta", type=float, default=0.27)
    ap.add_argument("--pt-mult", type=float, default=2.0)
    ap.add_argument("--sl-mult", type=float, default=0.5)
    ap.add_argument("--ivr-max", type=float, default=50.0,
                    help="IVR 入场上限 (默认 50 = LOW/MID mode)")
    ap.add_argument("--premium-pct", type=float, default=0.10,
                    help="每笔投入 premium 占 NAV 比例 (BCS 最大亏损=premium)")
    ap.add_argument("--haircut", type=float, default=0.02,
                    help="round-trip bid/ask 近似 (premium 的比例)")
    ap.add_argument("--tag", default="8y")
    args = ap.parse_args()

    print(f"=== Options BCS BS 近似回测 [{args.tag}] {args.start}~{args.end} ===\n")
    fetch_start = (pd.Timestamp(args.start) - pd.Timedelta(days=420)).strftime("%Y-%m-%d")
    qqq = load_yf("QQQ", fetch_start, args.end)
    vxn = load_yf("^VXN", fetch_start, args.end)
    df = pd.DataFrame({"qqq": qqq, "vxn": vxn}).dropna()
    df["ma200"] = df["qqq"].rolling(200).mean()
    df["rsi"] = compute_rsi(df["qqq"], 14)
    df["mom3m"] = df["qqq"] / df["qqq"].shift(63) - 1.0
    # IVR 252d
    df["vxn_lo"] = df["vxn"].rolling(252).min()
    df["vxn_hi"] = df["vxn"].rolling(252).max()
    df["ivr"] = (df["vxn"] - df["vxn_lo"]) / (df["vxn_hi"] - df["vxn_lo"]) * 100.0
    df["bullish"] = (df["qqq"] > df["ma200"]) & (df["rsi"].between(50, 78)) & (df["mom3m"] > 0)
    # 裁剪到回测窗口
    bt = df[(df.index >= args.start) & (df.index <= args.end)].copy()
    dates = list(bt.index)
    print(f"  交易日 {len(dates)}  ({dates[0].date()} ~ {dates[-1].date()})")
    bull_days = int(bt["bullish"].sum())
    entry_elig = int((bt["bullish"] & (bt["ivr"] < args.ivr_max)).sum())
    print(f"  bullish 日 {bull_days}  入场合格日(含 IVR门) {entry_elig}\n")

    # ---- 事件循环 ----
    pos = None   # {entry_i, K_long, K_short, premium, width, expiry_i, iv_entry}
    trades = []
    daily_ret = pd.Series(0.0, index=bt.index)
    for i, dt in enumerate(dates):
        row = bt.iloc[i]
        S = float(row["qqq"])
        iv = float(row["vxn"]) / 100.0
        if pos is not None:
            # 剩余 DTE 用日历日（与 config DTE 口径一致）；T = 日历日/365
            dte_remain = (pos["expiry_date"] - dt).days
            T = max(dte_remain, 0) / 365.0
            if dte_remain <= 0:
                val = max(0.0, min(S - pos["K_long"], pos["width"]))
            else:
                cl = bs_call(S, pos["K_long"], iv, T)
                cs = bs_call(S, pos["K_short"], iv, T)
                val = max(0.0, min(cl - cs, pos["width"]))
            prev_val = pos["last_val"]
            # 当日组合收益 = 投入比例 × 价差变动 / premium
            daily_ret.iloc[i] = args.premium_pct * (val - prev_val) / pos["premium"]
            pos["last_val"] = val
            # 出场判定
            exit_reason = None
            if val >= args.pt_mult * pos["premium"]:
                exit_reason = "profit_target"
            elif val <= args.sl_mult * pos["premium"]:
                exit_reason = "stop_loss"
            elif dte_remain <= 0:
                exit_reason = "expiry"
            if exit_reason:
                gross_pnl_pct = (val - pos["premium"]) / pos["premium"]
                net_pnl_pct = gross_pnl_pct - args.haircut  # round-trip 滑点
                trades.append(dict(
                    entry_date=str(dates[pos["entry_i"]].date()),
                    exit_date=str(dt.date()),
                    hold_days=i - pos["entry_i"],
                    S_entry=round(pos["S_entry"], 2), S_exit=round(S, 2),
                    K_long=round(pos["K_long"], 2), K_short=round(pos["K_short"], 2),
                    premium=round(pos["premium"], 3), exit_val=round(val, 3),
                    iv_entry=round(pos["iv_entry"], 3),
                    gross_pnl_pct=gross_pnl_pct, net_pnl_pct=net_pnl_pct,
                    exit_reason=exit_reason,
                ))
                # 出场当天再扣滑点（一次性）
                daily_ret.iloc[i] -= args.premium_pct * args.haircut
                pos = None
        # 开仓（无持仓 + 信号）
        if pos is None and bool(row["bullish"]) and float(row["ivr"]) < args.ivr_max:
            T0 = args.dte_entry / 365.0
            K_long = strike_from_delta(S, args.long_delta, iv, T0)
            K_short = strike_from_delta(S, args.short_delta, iv, T0)
            cl = bs_call(S, K_long, iv, T0)
            cs = bs_call(S, K_short, iv, T0)
            premium = cl - cs
            width = K_short - K_long
            if premium > 0 and width > premium:  # 合理 debit spread
                pos = dict(entry_i=i, S_entry=S, K_long=K_long, K_short=K_short,
                           premium=premium, width=width,
                           expiry_date=dt + pd.Timedelta(days=args.dte_entry),
                           iv_entry=iv, last_val=premium)

    # ---- 汇总 ----
    tr = pd.DataFrame(trades)
    m = metrics_from_daily(daily_ret)
    print(f"[结果] (sizing: premium {args.premium_pct:.0%}/笔, haircut {args.haircut:.0%})")
    print(f"  组合 Sharpe   {m['sharpe']:+.3f}")
    print(f"  年化收益      {m['annual_return']*100:+.2f}%")
    print(f"  年化波动      {m['annual_vol']*100:.2f}%")
    print(f"  最大回撤      {m['max_drawdown']*100:+.2f}%")
    print(f"  总收益        {m['total_return']*100:+.1f}%")
    if len(tr):
        wins = tr[tr.net_pnl_pct > 0]
        print(f"\n[交易层] (sizing 无关)")
        print(f"  笔数          {len(tr)}")
        print(f"  胜率          {len(wins)/len(tr)*100:.1f}%")
        print(f"  平均盈利      {wins.net_pnl_pct.mean()*100:+.1f}% (on premium)" if len(wins) else "  无盈利单")
        loss = tr[tr.net_pnl_pct <= 0]
        print(f"  平均亏损      {loss.net_pnl_pct.mean()*100:+.1f}% (on premium)" if len(loss) else "  无亏损单")
        pf = wins.net_pnl_pct.sum() / abs(loss.net_pnl_pct.sum()) if len(loss) and loss.net_pnl_pct.sum() != 0 else float('inf')
        print(f"  盈亏比(PF)    {pf:.2f}")
        print(f"  平均持有      {tr.hold_days.mean():.1f} 交易日")
        print(f"  trade-ret Sharpe (年化, 假设均匀) {tr.net_pnl_pct.mean()/tr.net_pnl_pct.std()*np.sqrt(len(tr)/((dates[-1]-dates[0]).days/365)):.2f}" if tr.net_pnl_pct.std() > 0 else "")
        print(f"\n  出场原因分布:")
        print(tr.exit_reason.value_counts().to_string())

    # 写产物
    out_dir = ROOT / f"data/backtest/options_bcs_qqq_{args.start}_{args.end}"
    out_dir.mkdir(parents=True, exist_ok=True)
    eq = (1 + daily_ret).cumprod() * 1_000_000
    eq.name = "equity"
    eq.to_csv(out_dir / "equity.csv", header=True)
    if len(tr):
        tr.to_csv(out_dir / "trades.csv", index=False)
    payload = dict(tag=args.tag, start=args.start, end=args.end,
                   params=vars(args), metrics=m,
                   n_trades=len(tr),
                   win_rate=float((tr.net_pnl_pct > 0).mean()) if len(tr) else 0.0,
                   bull_days=bull_days, entry_eligible_days=entry_elig)
    (out_dir / "metrics.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    print(f"\n[出口] {out_dir}")


if __name__ == "__main__":
    main()
