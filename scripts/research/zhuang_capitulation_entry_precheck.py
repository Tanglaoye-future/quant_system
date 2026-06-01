#!/usr/bin/env python3
"""
Zhuang capitulation entry trigger 预检查.

driver: user 描述策略 = "散户绝望卖出时吃货, 散户狂热时派发" — 本质就是
        zhuang sleeve. 当前 zhuang entry 用 accumulation_score >= 70 (吃货
        累积量 + 横盘), 没专门的 "capitulation 信号" 触发路径.

假设: 加 capitulation entry trigger (跌停撬开 / 放量大阴反包 / RSI < 30 / N
        日回撤大 + 量比异常) 可以补抓更多 winner, 提升 zhuang sleeve.

风险 (paradox 4 模式):
  - 信号互斥: score 70 已经在筛 "横盘累积量", capitulation = "下跌放量"
    可能 mutually exclusive (横盘 ≠ 急跌). 若 winner trades 入场前 5-20 日
    的 capitulation 信号占比 ≤ random base rate → 不是 alpha
  - Base rate spurious: A 股大盘段 capitulation 频发, 任何股都有, 与
    "winner 入场" 无关
  - Sample size: 58 trades 中 capitulation 入场子集可能 < 10, 统计无意义

本预检查 (使用 L7B-score70-pos40 = L1-E 当前 sleeve baseline 的 58 trades):
  1. winner (pnl > 0) vs loser (pnl < 0) 入场前 20 日内:
     - max 单日跌幅 (panic 阴线深度)
     - 跌停日数 (≤ -9.5%)
     - 量比异常日数 (vol > 2× 20d MA)
     - 入场日 RSI(14)
     - 入场日距 20 日高点回撤
  2. 若 winner 在 capitulation 信号上 vs loser 显著正向 (差 > 30% / 显著
     t-test) → 提示做 trigger
  3. 若 winner 与 loser 无差 / 反向 → 软证伪 (capitulation 信号与 score 70
     互斥, 或 base rate 主导)

复用 equity_factor DataLoader (akshare qfq daily, A 股全覆盖).

用法:
  python scripts/research/zhuang_capitulation_entry_precheck.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_system.strategies.equity_factor.data.loader import DataLoader  # type: ignore

TRADES_PATH = (
    ROOT / "data" / "backtest" / "_exp_L7B-score70-pos40" /
    "zhuang_a_share_2022-01-01_2024-12-31" / "trades.csv"
)
OUT_DIR = ROOT / "data" / "backtest" / "_zhuang_cap_precheck"
OUT_DIR.mkdir(parents=True, exist_ok=True)

LOOKBACK = 20            # 入场前 20 个交易日窗口
PANIC_DROP_PCT = -0.05   # 单日跌幅 ≤ -5% 算 panic
LLD_DROP_PCT = -0.095    # ≤ -9.5% 算跌停
VOL_SPIKE_X = 2.0        # 量比 > 2× 20d 均量算放量
RSI_OVERSOLD = 30.0


def rsi14(close: pd.Series) -> float:
    """简化 RSI(14), 返回最末值."""
    if len(close) < 15:
        return float("nan")
    delta = close.diff().dropna()
    up = delta.clip(lower=0)
    dn = (-delta).clip(lower=0)
    avg_up = up.ewm(alpha=1 / 14, adjust=False).mean()
    avg_dn = dn.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_up / avg_dn.replace(0, np.nan)
    return float(100 - 100 / (1 + rs.iloc[-1])) if pd.notna(rs.iloc[-1]) else float("nan")


def features_pre_entry(px: pd.DataFrame, entry_date: str) -> dict | None:
    """从 daily df 算入场前 LOOKBACK 日的 capitulation 特征."""
    if px.empty:
        return None
    px = px.copy()
    px["date"] = pd.to_datetime(px["date"])
    px = px.sort_values("date").reset_index(drop=True)
    entry_dt = pd.to_datetime(entry_date)
    # 入场日含进去 (作为信号触发当日 close 取 RSI)
    px_in = px[px["date"] <= entry_dt].tail(LOOKBACK + 1).reset_index(drop=True)
    if len(px_in) < 10:
        return None

    # 收益率序列
    px_in["ret"] = px_in["close"].pct_change()
    # 量比: 单日 vol / 20d 均量 (用全 LOOKBACK+1)
    vol_ma = px_in["volume"].rolling(window=min(20, len(px_in))).mean()
    px_in["vol_ratio"] = px_in["volume"] / vol_ma

    prior = px_in.iloc[:-1]  # 入场日之前的 N 日 = 严格"过去"
    max_drop = float(prior["ret"].min()) if len(prior) else float("nan")
    n_panic = int((prior["ret"] <= PANIC_DROP_PCT).sum())
    n_lld = int((prior["ret"] <= LLD_DROP_PCT).sum())
    n_vol_spike = int((prior["vol_ratio"] > VOL_SPIKE_X).sum())

    # 入场日 RSI (基于全 LOOKBACK+1)
    rsi_in = rsi14(px_in["close"])

    # 入场日距 20 日高点回撤
    high20 = float(prior["close"].max()) if len(prior) else float("nan")
    close_in = float(px_in["close"].iloc[-1])
    dd_from_high = (close_in / high20 - 1.0) if high20 and high20 > 0 else float("nan")

    return {
        "max_drop_5pct_": max_drop,
        "n_panic_days": n_panic,           # 单日 ≤ -5%
        "n_lld_days": n_lld,               # 单日 ≤ -9.5%
        "n_vol_spike_days": n_vol_spike,   # 量比 > 2.0
        "rsi_entry": rsi_in,
        "dd_from_20d_high": dd_from_high,
    }


def main() -> int:
    trades = pd.read_csv(TRADES_PATH)
    print(f"Trades loaded: {len(trades)}")
    trades["winner"] = trades["pnl_pct"] > 0
    win_n = int(trades["winner"].sum())
    print(f"  winner: {win_n} / {len(trades)} ({win_n/len(trades)*100:.1f}%)")

    loader = DataLoader(cache_dir=ROOT / "data/cache", refresh_days=999)

    rows = []
    for i, t in trades.iterrows():
        code = str(t["code"]).zfill(6)
        entry = t["entry_date"]
        # 拉入场前 60 自然日 ~ 40 交易日, 保险
        end_dt = pd.to_datetime(entry)
        start_dt = end_dt - pd.Timedelta(days=60)
        try:
            px = loader.get_daily(
                "a_share", code,
                start_dt.strftime("%Y-%m-%d"), entry,
            )
        except Exception:
            px = pd.DataFrame()
        feats = features_pre_entry(px, entry)
        if feats is None:
            continue
        feats["code"] = code
        feats["entry_date"] = entry
        feats["pnl_pct"] = float(t["pnl_pct"])
        feats["winner"] = bool(t["winner"])
        rows.append(feats)

    df = pd.DataFrame(rows)
    print(f"  features computed: {len(df)} / {len(trades)}")
    if len(df) < 10:
        print("ABORT: sample too small")
        return 1

    feature_cols = [
        "max_drop_5pct_", "n_panic_days", "n_lld_days",
        "n_vol_spike_days", "rsi_entry", "dd_from_20d_high",
    ]

    print()
    print("=" * 88)
    print(f"{'特征':<24}{'winner mean':>14}{'loser mean':>14}{'Δ (w-l)':>14}{'win%>med':>14}")
    print("=" * 88)
    summary = {}
    for col in feature_cols:
        w_vals = df.loc[df["winner"], col].dropna()
        l_vals = df.loc[~df["winner"], col].dropna()
        if len(w_vals) < 3 or len(l_vals) < 3:
            continue
        w_mean = float(w_vals.mean())
        l_mean = float(l_vals.mean())
        delta = w_mean - l_mean
        # 中位数分组, 看 capitulation 强 (col > median) 的 winner% 是否比 base rate 高
        med = float(df[col].dropna().median())
        if col == "rsi_entry" or col == "dd_from_20d_high" or col == "max_drop_5pct_":
            # 这些越低代表越绝望; 取 ≤ median 子集
            strong = df[df[col] <= med]
        else:
            strong = df[df[col] >= med]
        strong_winrate = float(strong["winner"].mean()) if len(strong) else float("nan")
        summary[col] = {
            "winner_mean": w_mean, "loser_mean": l_mean,
            "delta": delta, "strong_winrate": strong_winrate,
            "median": med, "n_w": int(len(w_vals)), "n_l": int(len(l_vals)),
        }
        print(f"{col:<24}{w_mean:>14.3f}{l_mean:>14.3f}{delta:>+14.3f}{strong_winrate*100:>13.1f}%")
    print("=" * 88)

    base_rate = float(df["winner"].mean())
    print(f"\nbase rate (overall winner%): {base_rate*100:.1f}%")

    # 简单判读
    strong_winrates = [summary[c]["strong_winrate"] for c in summary]
    deltas = [summary[c]["delta"] for c in summary]
    max_lift = max([sw - base_rate for sw in strong_winrates if sw == sw])
    n_aligned = sum(
        1 for col in summary
        if (col in ("rsi_entry", "dd_from_20d_high", "max_drop_5pct_") and summary[col]["delta"] < 0)
        or (col not in ("rsi_entry", "dd_from_20d_high", "max_drop_5pct_") and summary[col]["delta"] > 0)
    )

    if max_lift >= 0.10 and n_aligned >= 4:
        verdict = (
            f"PROCEED: capitulation 强子集 winner% lift ≥ +10pp 且 ≥ 4 个特征方向"
            f" 对齐 (winner more capitulation). 投 1-2 session 实现 entry trigger."
        )
    elif max_lift <= 0.02 or n_aligned <= 2:
        verdict = (
            f"SOFT-FALSIFY: max lift {max_lift*100:+.1f}pp (≤ +2pp), {n_aligned}/6 "
            "特征方向对齐. winner 入场前 capitulation 信号不显著强于 loser → "
            "与 zhuang score 70 (横盘累积量) 互斥 / base rate 主导 / sample 压扁. "
            "不做 trigger 实现, 第 16 条证伪. (与 zhuang L8 fundamentals 同模式)"
        )
    else:
        verdict = (
            f"AMBIGUOUS: max lift {max_lift*100:+.1f}pp, {n_aligned}/6 对齐. "
            "信号 partial 有但未到 PROCEED 门槛. 让用户决定 cost/benefit."
        )

    print()
    print(verdict)

    out_json = OUT_DIR / "zhuang_capitulation_precheck_summary.json"
    out_json.write_text(json.dumps({
        "base_rate_winner": base_rate,
        "n_trades": len(df),
        "feature_summary": summary,
        "verdict": verdict,
    }, indent=2, ensure_ascii=False))
    print(f"\nSaved: {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
