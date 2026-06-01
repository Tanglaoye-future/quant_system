#!/usr/bin/env python3
"""
Capitulation 变体 A 预检查: 放量大阴反包 + 龙虎榜机构净买.

driver: 用户描述 "散户绝望卖出时吃货" 策略, 但 akshare 跌停板撬开数据
        4y 历史封死 (近 30 日限制). 改用可得数据替代:
  - 放量大阴 (单日跌幅 ≤ -7% + 量比 > 1.5)
  - 次日反包 (T+1 close > T 日 high)
  - 龙虎榜机构净买 (T+1 ~ T+3 上 LHB 且机构净买 > 0)

风险 (paradox 4 模式 + A_mr 历史):
  - 信号互斥 / 重复: 类似 A_mr v1 SwingReversion (dip+bounce), v1 4y FAIL
    Sharpe -0.27
  - Base rate spurious: A 股下跌后第二天反包是普遍现象 (1/3 概率), winner
    不一定来自这条信号
  - Sample size: HS300 全年 -7% 阴线 ~ 50-200 个, 加反包过滤后 ~20-60,
    再加机构净买 ~ 10-30, 统计意义弱

本预检查 (2024 一整年, HS300 300 ticker):
  1. 全扫 -7% panic 事件
  2. 反包过滤 (T+1 close > T day high)
  3. 机构净买叠加 (T+1/T+2/T+3 LHB 出现 + 净买 > 0)
  4. 5d/10d hold from T+1 close, pnl 分布 vs HS300 整体 base rate
  5. PROCEED / AMBIGUOUS / SOFT-FALSIFY

复用 equity_factor DataLoader (akshare qfq daily, HS300 universe).

用法:
  python scripts/research/capitulation_variant_a_precheck.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import akshare as ak
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_system.strategies.equity_factor.data.loader import DataLoader  # type: ignore

YEAR = 2024
START = f"{YEAR}-01-01"
END = f"{YEAR}-12-31"

PANIC_DROP_PCT = -0.07     # 单日跌幅 ≤ -7%
VOL_SPIKE_X = 1.5          # 量比 > 1.5× 20d 均量
HOLD_DAYS = (5, 10)        # 测两个持有期
OUT_DIR = ROOT / "data" / "backtest" / "_capit_var_a"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def fetch_lhb_year(year: int) -> pd.DataFrame:
    """拉一年龙虎榜 detail. 按月分批以避免 timeout."""
    parts = []
    for m in range(1, 13):
        sd = f"{year}{m:02d}01"
        ed = f"{year}{m:02d}31"
        try:
            df = ak.stock_lhb_detail_em(start_date=sd, end_date=ed)
            if df is not None and len(df) > 0:
                parts.append(df)
        except Exception as e:
            print(f"LHB {sd}-{ed} ERROR: {e}", file=sys.stderr)
    if not parts:
        return pd.DataFrame()
    full = pd.concat(parts, ignore_index=True)
    return full


def main() -> int:
    t0 = time.time()
    loader = DataLoader(cache_dir=ROOT / "data/cache", refresh_days=999)
    uni = loader.get_universe("a_share", "hs300")
    hs300_codes = set(c.zfill(6) for c in uni["code"].tolist())
    print(f"HS300 size: {len(hs300_codes)}")

    # 1. 拉年度龙虎榜并预处理
    print(f"Fetching LHB {YEAR}...")
    lhb = fetch_lhb_year(YEAR)
    print(f"LHB rows: {len(lhb)}, cols: {lhb.columns.tolist()[:10]}")
    lhb_jg = ak.stock_lhb_jgmmtj_em(start_date=f"{YEAR}0101", end_date=f"{YEAR}1231")
    print(f"LHB 机构 rows: {len(lhb_jg)}")

    # 标准化日期 + code
    if "上榜日" in lhb.columns:
        lhb["date"] = pd.to_datetime(lhb["上榜日"]).dt.strftime("%Y-%m-%d")
        lhb["code"] = lhb["代码"].astype(str).str.zfill(6)
        lhb_net = lhb[["date", "code", "龙虎榜净买额"]].copy()
        lhb_net["净买额"] = pd.to_numeric(lhb_net["龙虎榜净买额"], errors="coerce")
        lhb_net = lhb_net.dropna(subset=["净买额"])
    else:
        lhb_net = pd.DataFrame(columns=["date", "code", "净买额"])
    print(f"LHB normalized: {len(lhb_net)}")

    if "上榜日期" in lhb_jg.columns:
        lhb_jg["date"] = pd.to_datetime(lhb_jg["上榜日期"]).dt.strftime("%Y-%m-%d")
        lhb_jg["code"] = lhb_jg["代码"].astype(str).str.zfill(6)
        jg_col = "机构买入净额" if "机构买入净额" in lhb_jg.columns else "机构净买额"
        lhb_jg["机构净买"] = pd.to_numeric(lhb_jg[jg_col], errors="coerce")
        lhb_jg_n = lhb_jg[["date", "code", "机构净买"]].dropna(subset=["机构净买"])
    else:
        lhb_jg_n = pd.DataFrame(columns=["date", "code", "机构净买"])
    print(f"LHB 机构 normalized: {len(lhb_jg_n)}")

    # 2. 扫 HS300 -7% panic events
    events = []  # 每个: (code, T_date, T_high, T_close, T_vol_ratio)
    for i, code in enumerate(sorted(hs300_codes)):
        try:
            px = loader.get_daily("a_share", code, START, END)
        except Exception:
            continue
        if px.empty or len(px) < 25:
            continue
        px = px.copy().reset_index(drop=True)
        px["ret"] = px["close"].pct_change()
        px["vol_ma20"] = px["volume"].rolling(20).mean()
        px["vol_ratio"] = px["volume"] / px["vol_ma20"]
        # mask 出 -7% + 量比 > 1.5
        mask = (px["ret"] <= PANIC_DROP_PCT) & (px["vol_ratio"] > VOL_SPIKE_X)
        for idx in np.where(mask.values)[0]:
            # 必须有 T+1 (反包判断) + 后续 HOLD_DAYS (pnl)
            if idx + max(HOLD_DAYS) >= len(px):
                continue
            t_date = px.loc[idx, "date"]
            t_high = float(px.loc[idx, "high"])
            t_close = float(px.loc[idx, "close"])
            t_vol_ratio = float(px.loc[idx, "vol_ratio"])
            tplus1_close = float(px.loc[idx + 1, "close"])
            wrapped = tplus1_close > t_high   # 反包
            # 5d / 10d hold pnl from T+1 close
            pnls = {}
            for h in HOLD_DAYS:
                exit_close = float(px.loc[idx + h, "close"]) if idx + h < len(px) else float("nan")
                pnls[f"pnl_{h}d"] = (exit_close / tplus1_close - 1.0) if exit_close == exit_close else float("nan")
            events.append({
                "code": code, "T_date": t_date,
                "T_drop_pct": float(px.loc[idx, "ret"]),
                "T_vol_ratio": t_vol_ratio,
                "wrapped": wrapped,
                **pnls,
            })

    ev_df = pd.DataFrame(events)
    print(f"\nPanic events (T 日 -7% + 量比>1.5): {len(ev_df)}")
    if len(ev_df) == 0:
        print("ABORT: no events")
        return 1

    # 反包子集
    wrapped = ev_df[ev_df["wrapped"]]
    print(f"  其中 T+1 反包: {len(wrapped)} ({len(wrapped)/len(ev_df)*100:.1f}%)")

    # 叠加机构净买
    if len(lhb_jg_n) > 0:
        # T+1 ~ T+3 内有机构净买 > 0
        ev_df["T_date_dt"] = pd.to_datetime(ev_df["T_date"])
        lhb_jg_pos = lhb_jg_n[lhb_jg_n["机构净买"] > 0].copy()
        lhb_jg_pos["date_dt"] = pd.to_datetime(lhb_jg_pos["date"])
        # 对每个 event, 查 T+1 ~ T+3 是否有 jg 净买
        jg_matched = []
        for _, ev in ev_df.iterrows():
            t = ev["T_date_dt"]
            mask = (
                (lhb_jg_pos["code"] == ev["code"]) &
                (lhb_jg_pos["date_dt"] >= t + pd.Timedelta(days=1)) &
                (lhb_jg_pos["date_dt"] <= t + pd.Timedelta(days=5))  # 给反包 + 上榜窗口
            )
            jg_matched.append(int(mask.any()))
        ev_df["jg_buy_within_5d"] = jg_matched
        wrapped["T_date_dt"] = pd.to_datetime(wrapped["T_date"])
        wrapped = wrapped.merge(
            ev_df[["code", "T_date", "jg_buy_within_5d"]],
            on=["code", "T_date"], how="left",
        )
    else:
        ev_df["jg_buy_within_5d"] = 0
        wrapped["jg_buy_within_5d"] = 0

    # 3. 统计
    summary = {}
    base_5d_mean = float(ev_df["pnl_5d"].mean())
    base_10d_mean = float(ev_df["pnl_10d"].mean())
    base_5d_win = float((ev_df["pnl_5d"] > 0).mean())
    base_10d_win = float((ev_df["pnl_10d"] > 0).mean())

    print(f"\n=== panic events 整体 (n={len(ev_df)}) ===")
    print(f"  5d hold mean pnl: {base_5d_mean*100:+.2f}%  win%: {base_5d_win*100:.1f}%")
    print(f"  10d hold mean pnl: {base_10d_mean*100:+.2f}%  win%: {base_10d_win*100:.1f}%")

    print(f"\n=== 反包子集 (n={len(wrapped)}) ===")
    if len(wrapped) > 5:
        w5 = float(wrapped["pnl_5d"].mean())
        w10 = float(wrapped["pnl_10d"].mean())
        w5_win = float((wrapped["pnl_5d"] > 0).mean())
        w10_win = float((wrapped["pnl_10d"] > 0).mean())
        print(f"  5d:  mean={w5*100:+.2f}% (Δ vs base={(w5-base_5d_mean)*100:+.2f}pp)  win%={w5_win*100:.1f}% (Δ {(w5_win-base_5d_win)*100:+.1f}pp)")
        print(f"  10d: mean={w10*100:+.2f}% (Δ vs base={(w10-base_10d_mean)*100:+.2f}pp)  win%={w10_win*100:.1f}% (Δ {(w10_win-base_10d_win)*100:+.1f}pp)")
        summary["wrapped"] = {
            "n": len(wrapped), "mean_5d": w5, "mean_10d": w10,
            "win_5d": w5_win, "win_10d": w10_win,
        }

    # 反包 + 机构净买
    wrapped_jg = wrapped[wrapped.get("jg_buy_within_5d", 0) == 1]
    print(f"\n=== 反包 + T+1~T+5 机构净买 (n={len(wrapped_jg)}) ===")
    if len(wrapped_jg) > 3:
        wj5 = float(wrapped_jg["pnl_5d"].mean())
        wj10 = float(wrapped_jg["pnl_10d"].mean())
        wj5_win = float((wrapped_jg["pnl_5d"] > 0).mean())
        wj10_win = float((wrapped_jg["pnl_10d"] > 0).mean())
        print(f"  5d:  mean={wj5*100:+.2f}% (Δ vs base={(wj5-base_5d_mean)*100:+.2f}pp)  win%={wj5_win*100:.1f}% (Δ {(wj5_win-base_5d_win)*100:+.1f}pp)")
        print(f"  10d: mean={wj10*100:+.2f}% (Δ vs base={(wj10-base_10d_mean)*100:+.2f}pp)  win%={wj10_win*100:.1f}% (Δ {(wj10_win-base_10d_win)*100:+.1f}pp)")
        summary["wrapped_jg"] = {
            "n": len(wrapped_jg), "mean_5d": wj5, "mean_10d": wj10,
            "win_5d": wj5_win, "win_10d": wj10_win,
        }
    else:
        print(f"  sample 太小 ({len(wrapped_jg)}), 统计意义弱")

    # 4. verdict
    n_wj = len(wrapped_jg)
    wj_lift_5d = (summary.get("wrapped_jg", {}).get("mean_5d", base_5d_mean) - base_5d_mean) if n_wj > 3 else 0.0
    w_lift_5d = (summary.get("wrapped", {}).get("mean_5d", base_5d_mean) - base_5d_mean) if len(wrapped) > 5 else 0.0
    print()
    if n_wj < 5:
        verdict = (
            f"SOFT-FALSIFY: 反包+机构净买子集 n={n_wj} < 5, sample 压扁,"
            " 没有统计意义. 4y backtest 也会面临 sample size 问题. 不做."
        )
    elif wj_lift_5d >= 0.015 and w_lift_5d >= 0.005:
        verdict = (
            f"PROCEED: wrapped+jg 5d lift +{wj_lift_5d*100:.2f}pp vs base, "
            f"wrapped 5d lift +{w_lift_5d*100:.2f}pp. 信号有差异. 投 1-2 sess 独立 sleeve."
        )
    elif abs(wj_lift_5d) < 0.005 and abs(w_lift_5d) < 0.005:
        verdict = (
            f"SOFT-FALSIFY: wrapped+jg 5d lift {wj_lift_5d*100:+.2f}pp, wrapped lift "
            f"{w_lift_5d*100:+.2f}pp 均 < 0.5pp. 信号无 alpha 提升, 与 base rate 同."
            " (类似 A_mr v1/v2 形态, 4y FAIL 模式同)"
        )
    else:
        verdict = (
            f"AMBIGUOUS: wrapped 5d lift {w_lift_5d*100:+.2f}pp, wrapped+jg "
            f"{wj_lift_5d*100:+.2f}pp. 信号 partial 有, 让用户决定 cost/benefit."
        )

    print(verdict)
    print(f"\nelapsed: {time.time()-t0:.0f}s")
    out_json = OUT_DIR / "variant_a_precheck_summary.json"
    out_json.write_text(json.dumps({
        "n_events": len(ev_df),
        "n_wrapped": len(wrapped),
        "n_wrapped_jg": int(n_wj),
        "base_5d_mean": base_5d_mean, "base_10d_mean": base_10d_mean,
        "base_5d_win": base_5d_win, "base_10d_win": base_10d_win,
        "summary": summary,
        "verdict": verdict,
    }, indent=2, ensure_ascii=False))
    print(f"Saved: {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
