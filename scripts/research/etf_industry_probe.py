#!/usr/bin/env python3
"""ETF 行业轮动支线 probe (2026-06-17/18).

立项前 baseline probe — 不写策略代码 / 不立 spec, 只出数据回答 3 个硬问题:

  Q1 universe + 数据可用性: akshare 申万一级 28 行业能拉到哪些 ETF? 6Y 历史完整度?
  Q2 与 A_mom 相关性: 行业 ETF 月度收益 vs HS300 (A_mom 选股 universe) 相关性
                      硬否决线: 月度 corr ≥ 0.6 等于重复 alpha 不立项
  Q3 与 CB sleeve / v7 其他资产: 是否有 hedge 价值 (与 CB 负相关) 或同构 (与 HK/QQQ ≈ 1)

输出: print + memory/etf_industry_rotation_probe_2026-06.md (人工沉淀)

不依赖项目策略代码, 独立脚本.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import akshare as ak
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ── 主流行业 ETF 手选清单 (申万一级 28 个里挑流动性 + 6Y 历史最完整的) ──
# 这是 probe scope, 不是策略最终 universe. 后续若立项, universe 重新定义.
INDUSTRY_ETFS = [
    # (code, label, 主流行业归类)
    ("512800", "银行ETF",       "金融"),
    ("512000", "券商ETF",       "金融"),
    ("512170", "医疗ETF",       "医药生物"),
    ("159992", "创新药ETF",     "医药生物"),
    ("512760", "芯片ETF",       "电子"),
    ("515030", "新能车ETF",     "汽车/电力设备"),
    ("159928", "消费ETF",       "食品饮料"),
    ("512690", "酒ETF",         "食品饮料"),
    ("515790", "光伏ETF",       "电力设备"),
    ("512660", "军工ETF",       "国防军工"),
    ("159995", "芯片ETF广发",   "电子"),
    ("512480", "半导体ETF",     "电子"),
    ("515050", "5GETF",         "通信"),
    ("515880", "通信ETF",       "通信"),
    ("159819", "人工智能AIETF", "计算机"),
    ("515380", "地产ETF",       "房地产"),
    ("159996", "家电ETF",       "家用电器"),
    ("515210", "钢铁ETF",       "钢铁"),
    ("159930", "能源ETF",       "采掘/煤炭"),
    ("515220", "煤炭ETF",       "采掘/煤炭"),
]


def fetch_etf_monthly_returns(code: str, start: str, end: str) -> pd.Series:
    """akshare ETF 日线 → 月末收盘价 → 月度收益率."""
    try:
        df = ak.fund_etf_hist_em(symbol=code, period="daily",
                                  start_date=start.replace("-", ""),
                                  end_date=end.replace("-", ""),
                                  adjust="qfq")
    except Exception as e:
        print(f"  ⚠ {code} fetch failed: {e}")
        return pd.Series(dtype=float, name=code)
    if df is None or df.empty:
        return pd.Series(dtype=float, name=code)
    df = df.rename(columns={"日期": "date", "收盘": "close"})
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    # 月末 resample → 月度收益
    monthly = df["close"].resample("ME").last()
    returns = monthly.pct_change().dropna()
    returns.name = code
    return returns


def fetch_hs300_monthly_returns(start: str, end: str) -> pd.Series:
    """HS300 月度收益 (A_mom universe proxy)."""
    try:
        df = ak.stock_zh_index_daily(symbol="sh000300")
    except Exception as e:
        print(f"⚠ HS300 fetch failed: {e}")
        return pd.Series(dtype=float)
    df = df.rename(columns={"date": "date", "close": "close"})
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df.loc[start:end]
    monthly = df["close"].resample("ME").last()
    returns = monthly.pct_change().dropna()
    returns.name = "HS300"
    return returns


def fetch_csi500_monthly_returns(start: str, end: str) -> pd.Series:
    try:
        df = ak.stock_zh_index_daily(symbol="sh000905")
    except Exception:
        return pd.Series(dtype=float)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df.loc[start:end]
    monthly = df["close"].resample("ME").last()
    returns = monthly.pct_change().dropna()
    returns.name = "CSI500"
    return returns


def main() -> int:
    end = date.today().isoformat()
    start_6y = (date.today() - timedelta(days=365 * 6)).isoformat()
    start_4y = (date.today() - timedelta(days=365 * 4)).isoformat()

    print(f"\n{'='*70}")
    print(f"  ETF 行业轮动 probe  ({date.today()})")
    print(f"  窗口: 6Y={start_6y}→{end}, 4Y={start_4y}→{end}")
    print(f"  universe candidate: {len(INDUSTRY_ETFS)} 只主流行业 ETF (申万一级映射)")
    print(f"{'='*70}\n")

    # ── 1. 拉 HS300 / CSI500 月度收益 (A_mom proxy) ──
    print("[1/3] 拉 HS300 / CSI500 月度收益 (A_mom proxy)...")
    hs300 = fetch_hs300_monthly_returns(start_6y, end)
    csi500 = fetch_csi500_monthly_returns(start_6y, end)
    print(f"  HS300:  {len(hs300):>3} 月度数据 ({hs300.index.min().date() if len(hs300) else '—'}"
          f" → {hs300.index.max().date() if len(hs300) else '—'})")
    print(f"  CSI500: {len(csi500):>3} 月度数据")
    if len(hs300) < 24:
        print("⚠ HS300 月度数据不足 24, 相关性结论无意义, 退出")
        return 1

    # ── 2. 拉行业 ETF 6Y 月度收益 + 数据可用性 ──
    print(f"\n[2/3] 拉 {len(INDUSTRY_ETFS)} 只行业 ETF 6Y 月度收益...")
    etf_returns: dict[str, pd.Series] = {}
    coverage_table = []
    for code, label, industry in INDUSTRY_ETFS:
        r = fetch_etf_monthly_returns(code, start_6y, end)
        coverage = len(r)
        coverage_table.append((code, label, industry, coverage))
        if coverage >= 12:  # 至少 1 年数据才参与相关性
            etf_returns[f"{code}_{label}"] = r

    print(f"\n  代码     名称           行业            6Y 月数  可用?")
    print(f"  -------- -------------- --------------- -------  -----")
    for code, label, ind, n in coverage_table:
        ok = "✅" if n >= 60 else ("🟡" if n >= 24 else "❌")
        print(f"  {code:<8} {label[:14]:<14} {ind:<15} {n:>5}    {ok}")

    print(f"\n  采用 (≥12月) 共 {len(etf_returns)} 只 → 相关性分析")
    if not etf_returns:
        print("⚠ 没有任何 ETF 通过数据筛选, 退出")
        return 2

    # ── 3. 相关性矩阵: ETF vs HS300 / CSI500 ──
    print(f"\n[3/3] 相关性 (月度 returns, 共同窗口):\n")

    # 拼成 DataFrame, 自动对齐 index
    all_series = {"HS300": hs300, "CSI500": csi500, **etf_returns}
    rdf = pd.DataFrame(all_series).dropna()
    print(f"  共同窗口: {rdf.index.min().date()} → {rdf.index.max().date()}, n={len(rdf)} 月")

    if len(rdf) < 24:
        print("⚠ 共同窗口数据不足 24 月, 相关性结论谨慎对待")

    # 计算每个 ETF vs HS300 / CSI500 的 corr
    print(f"\n  ETF              vs HS300   vs CSI500  std    avg_ret(月)")
    print(f"  ---------------- --------- ---------- ------ ----------")
    rows = []
    for col in rdf.columns:
        if col in ("HS300", "CSI500"):
            continue
        s = rdf[col]
        c_hs = s.corr(rdf["HS300"])
        c_cs = s.corr(rdf["CSI500"])
        std = s.std()
        mean = s.mean()
        rows.append((col, c_hs, c_cs, std, mean))
        print(f"  {col:<16} {c_hs:>+8.3f}  {c_cs:>+8.3f}   {std:>6.3f} {mean:>+8.3%}")

    # 硬否决线 cross-check
    print(f"\n{'─'*70}")
    print(f"  硬否决线 cross-check (与 A_mom proxy HS300 corr ≥ 0.6 = 重复 alpha)")
    print(f"{'─'*70}")
    pass_etfs = [(label, c) for label, c, _, _, _ in rows if abs(c) < 0.6]
    fail_etfs = [(label, c) for label, c, _, _, _ in rows if abs(c) >= 0.6]
    print(f"  PASS (corr<0.6, 有独立 alpha 候选): {len(pass_etfs)}")
    for label, c in pass_etfs[:10]:
        print(f"    ✅ {label:<16} corr_HS300={c:+.3f}")
    print(f"  FAIL (corr≥0.6, 与 A_mom 重复 alpha): {len(fail_etfs)}")
    for label, c in fail_etfs:
        print(f"    ❌ {label:<16} corr_HS300={c:+.3f}")

    # 截面平均 corr
    avg_corr_hs = sum(abs(c) for _, c, _, _, _ in rows) / len(rows) if rows else 0
    print(f"\n  ETF universe 平均 |corr_HS300| = {avg_corr_hs:.3f}")
    if avg_corr_hs >= 0.6:
        print(f"  ⚠ 平均 corr ≥ 0.6 → 行业 ETF 整体与 A_mom 高度重合, 立项 alpha 风险大")
    else:
        print(f"  ✅ 平均 corr < 0.6 → 有部分行业 ETF 有独立 alpha 空间, 可考虑立项 spec")

    print(f"\n{'='*70}")
    print(f"  probe 完成. 决策依据见 memory/etf_industry_rotation_probe_2026-06.md")
    print(f"{'='*70}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
