#!/usr/bin/env python3
"""
zhuang L8 (was handoff #3): fundamentals quality gate 预检查.

driver: L7-A + L7-B 双向证伪 zhuang sleeve 参数 sweep, 未来 alpha 必须从外部信号来.
candidate: 入场加 ROE > 0 + 营业总收入增长率 > 0 过滤业绩差股.
风险: zhuang_l1_l2_l3 L2/L3 (信号 overlay) 已证负转移 — 庄股本就业绩烂,
      fundamentals gate 可能砍掉真正赚钱的 winner trades.

本预检查: 从 L7B-score70 (= L1-E, baseline) 的 58 笔 trades (含 winner) 拉 ROE
       和营收增速 as-of entry_date, 看 winner 中 ROE<0 / 营收增速<0 的占比.
- 占比 > 30% → gate 会显著误杀, 直接证伪, 不接 loader
- 占比 < 15% → 接完整 gate sweep, 1-2 hr 工程
- 中间区间 → 报告给用户决定

复用 equity_factor DataLoader.get_a_share_abstract + latest_indicator_value.

用法:
  python scripts/research/zhuang_l8_fundamentals_precheck.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_system.strategies.equity_factor.data.loader import DataLoader  # type: ignore

TRADES_PATH = ROOT / "data" / "backtest" / "_exp_L7B-score70-pos40" / "zhuang_a_share_2022-01-01_2024-12-31" / "trades.csv"
OUT_DIR = ROOT / "data" / "backtest" / "_l8_precheck"
OUT_DIR.mkdir(parents=True, exist_ok=True)

INDICATOR_ROE = "净资产收益率(ROE)"
INDICATOR_REV_GROWTH = "营业总收入增长率"
INDICATOR_NP_GROWTH = "归属母公司净利润增长率"


def fetch_fund_at(loader: DataLoader, code: str, asof: str) -> dict:
    """拉 abstract + 取 as-of ROE/营收增速/净利润增速."""
    try:
        df = loader.get_a_share_abstract(code)
    except Exception as e:
        return {"error": f"abstract_fetch: {e}"}
    out = {
        "roe": DataLoader.latest_indicator_value(df, INDICATOR_ROE, asof=asof, publication_lag_days=90),
        "rev_growth": DataLoader.latest_indicator_value(df, INDICATOR_REV_GROWTH, asof=asof, publication_lag_days=90),
        "np_growth": DataLoader.latest_indicator_value(df, INDICATOR_NP_GROWTH, asof=asof, publication_lag_days=90),
    }
    return out


def pct_bucket(series: pd.Series, threshold: float = 0.0, op: str = ">=") -> str:
    valid = series.dropna()
    if len(valid) == 0:
        return "n/a (all NaN)"
    if op == ">=":
        n = (valid >= threshold).sum()
    elif op == ">":
        n = (valid > threshold).sum()
    elif op == "<":
        n = (valid < threshold).sum()
    elif op == "<=":
        n = (valid <= threshold).sum()
    return f"{n}/{len(valid)} ({n / len(valid) * 100:.1f}%)"


def main():
    trades = pd.read_csv(TRADES_PATH, dtype={"code": str})
    trades["code"] = trades["code"].str.zfill(6)
    trades["entry_date"] = pd.to_datetime(trades["entry_date"]).dt.strftime("%Y-%m-%d")
    trades["winner"] = trades["pnl_pct"] > 0
    print(f"trades: {len(trades)}, winner: {trades['winner'].sum()}, loser: {(~trades['winner']).sum()}")
    print(f"win rate: {trades['winner'].mean() * 100:.1f}%")
    print(f"unique codes: {trades['code'].nunique()}")
    print()

    loader = DataLoader(cache_dir=ROOT / "data" / "cache", refresh_days=30)

    rows = []
    for i, t in trades.iterrows():
        code = t["code"]
        asof = t["entry_date"]
        fund = fetch_fund_at(loader, code, asof)
        rows.append({
            "code": code, "entry_date": asof, "pnl_pct": float(t["pnl_pct"]),
            "winner": bool(t["winner"]), **fund,
        })
        print(f"  [{i+1}/{len(trades)}] {code}@{asof} winner={t['winner']} "
              f"roe={fund.get('roe')} rev_g={fund.get('rev_growth')} np_g={fund.get('np_growth')}")

    df = pd.DataFrame(rows)
    df.to_csv(OUT_DIR / "winner_fundamentals.csv", index=False)

    print("\n=== overall coverage ===")
    print(f"ROE non-NaN: {df['roe'].notna().sum()}/{len(df)} ({df['roe'].notna().mean()*100:.1f}%)")
    print(f"rev_growth non-NaN: {df['rev_growth'].notna().sum()}/{len(df)} ({df['rev_growth'].notna().mean()*100:.1f}%)")
    print(f"np_growth non-NaN: {df['np_growth'].notna().sum()}/{len(df)} ({df['np_growth'].notna().mean()*100:.1f}%)")

    win = df[df["winner"]]
    lose = df[~df["winner"]]

    print("\n=== ROE 分布（threshold = 0 用作 gate）===")
    print(f"winner ROE > 0: {pct_bucket(win['roe'], 0, '>')}")
    print(f"winner ROE <= 0 (会被 gate 误杀): {pct_bucket(win['roe'], 0, '<=')}")
    print(f"loser ROE > 0 (gate 留下的 loser): {pct_bucket(lose['roe'], 0, '>')}")
    print(f"loser ROE <= 0 (gate 砍掉的 loser): {pct_bucket(lose['roe'], 0, '<=')}")

    print("\n=== 营收增速 分布（threshold = 0 用作 gate）===")
    print(f"winner rev_growth > 0: {pct_bucket(win['rev_growth'], 0, '>')}")
    print(f"winner rev_growth <= 0 (会被 gate 误杀): {pct_bucket(win['rev_growth'], 0, '<=')}")
    print(f"loser rev_growth > 0 (gate 留下的 loser): {pct_bucket(lose['rev_growth'], 0, '>')}")
    print(f"loser rev_growth <= 0 (gate 砍掉的 loser): {pct_bucket(lose['rev_growth'], 0, '<=')}")

    print("\n=== 联合 gate (ROE>0 AND rev_growth>0) 模拟 ===")
    both = (df["roe"] > 0) & (df["rev_growth"] > 0)
    win_both = (df["winner"]) & both
    lose_both = (~df["winner"]) & both
    win_drop = (df["winner"]) & (~both) & (df["roe"].notna()) & (df["rev_growth"].notna())
    lose_drop = (~df["winner"]) & (~both) & (df["roe"].notna()) & (df["rev_growth"].notna())
    print(f"keep winner: {win_both.sum()}/{win.shape[0]} ({win_both.sum() / win.shape[0] * 100:.1f}%)")
    print(f"keep loser: {lose_both.sum()}/{lose.shape[0]} ({lose_both.sum() / lose.shape[0] * 100:.1f}%)")
    print(f"drop winner (误杀): {win_drop.sum()}")
    print(f"drop loser (有效): {lose_drop.sum()}")
    print(f"误杀比 = drop_winner / drop_total = {win_drop.sum() / max(1, win_drop.sum() + lose_drop.sum()) * 100:.1f}%")

    # 关键 KPI: winner 中 ROE<=0 占比 + 联合 gate 后 win rate 改善
    win_roe_neg_pct = (win["roe"] <= 0).sum() / max(1, win["roe"].notna().sum()) * 100
    win_rev_neg_pct = (win["rev_growth"] <= 0).sum() / max(1, win["rev_growth"].notna().sum()) * 100

    base_winrate = trades["winner"].mean() * 100
    keep_total = win_both.sum() + lose_both.sum()
    new_winrate = win_both.sum() / max(1, keep_total) * 100 if keep_total > 0 else 0

    verdict = "ABORT (>30%)" if win_roe_neg_pct > 30 else "PROCEED (<15%)" if win_roe_neg_pct < 15 else "AMBIGUOUS (15-30%)"

    print("\n" + "=" * 60)
    print("L8 决策门")
    print("=" * 60)
    print(f"winner 中 ROE<=0 占比: {win_roe_neg_pct:.1f}%   → {verdict}")
    print(f"winner 中 营收增速<=0 占比: {win_rev_neg_pct:.1f}%")
    print(f"原 win rate: {base_winrate:.1f}%  →  gate 后 win rate: {new_winrate:.1f}%  (Δ {new_winrate - base_winrate:+.1f}pp)")
    print(f"原 trades: {len(trades)}  →  gate 后 trades: {keep_total}  (-{len(trades) - keep_total}, -{(len(trades) - keep_total) / len(trades) * 100:.1f}%)")

    summary = {
        "n_trades": int(len(trades)),
        "n_winner": int(trades["winner"].sum()),
        "n_unique_codes": int(trades["code"].nunique()),
        "fundamentals_coverage": {
            "roe": int(df["roe"].notna().sum()),
            "rev_growth": int(df["rev_growth"].notna().sum()),
            "np_growth": int(df["np_growth"].notna().sum()),
        },
        "winner_roe_neg_pct": round(win_roe_neg_pct, 1),
        "winner_rev_growth_neg_pct": round(win_rev_neg_pct, 1),
        "base_win_rate": round(base_winrate, 1),
        "gate_win_rate": round(new_winrate, 1),
        "gate_kept_trades": int(keep_total),
        "gate_dropped_winners": int(win_drop.sum()),
        "gate_dropped_losers": int(lose_drop.sum()),
        "verdict": verdict,
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\n[出口] {OUT_DIR / 'summary.json'}")
    print(f"[出口] {OUT_DIR / 'winner_fundamentals.csv'}")


if __name__ == "__main__":
    main()
