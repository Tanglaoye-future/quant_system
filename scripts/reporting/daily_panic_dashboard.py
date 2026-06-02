#!/usr/bin/env python3
"""
Daily panic / 反向情绪 dashboard — 辅助人工 T 决策, 不进 backtest 体系.

driver: [[capitulation_strategy_falsified_2026-06]] 4 重证伪后用户选项 A.
       不是 strategy / 不入 v5 / 不动 yaml / 不动 daily 三策略串联.
       执行决策仍归用户, dashboard 仅多提供参考维度.

Section 1: Panic candidates  — HS300 + CSI1000 (akshare 可得 universe)
                                当日跌幅 ≤ -5% / ≤ -7% + 量比 > 1.5/2.0
Section 2: 反包候选 (T-1 panic + T 开盘高于昨收 1%) — 给人工 T+1 早盘参考
Section 3: LHB 机构净买 top — 最近 5 个交易日机构净买额 top 20
Section 4: 大盘情绪 — 财新 + CCTV news 关键词 (个股 news akshare 死, 用大盘代)
Section 5: Sleeve overlap — zhuang / A_mom 当前候选名单 ∩ panic 候选

输出: report/panic_dashboard_<date>.html + report/data/panic_dashboard.json

用法:
  python scripts/reporting/daily_panic_dashboard.py                    # 今日
  python scripts/reporting/daily_panic_dashboard.py --date 2026-06-02  # 指定
  python scripts/reporting/daily_panic_dashboard.py --open             # 生成后开浏览器
  python scripts/reporting/daily_panic_dashboard.py --quick            # 跳过大盘 news
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import akshare as ak
import numpy as np
import pandas as pd

from quant_system.strategies.equity_factor.data.loader import DataLoader

REPORT_DIR = ROOT / "report"
DATA_DIR = REPORT_DIR / "data"

PANIC_THRESHOLDS = (-0.05, -0.07)   # 跌幅阈值
VOL_RATIO_THRESHOLDS = (1.5, 2.0)
REBOUND_PCT = 0.01                  # T 开盘 > 昨收 1%
LHB_LOOKBACK_DAYS = 5
LHB_TOP_N = 20

SENTIMENT_BULL_KEYWORDS = ["反弹", "回升", "利好", "刺激", "扩张", "提振", "新高", "突破", "积极"]
SENTIMENT_BEAR_KEYWORDS = ["崩盘", "暴跌", "破发", "重挫", "利空", "退市", "下跌", "回调", "恐慌", "抛售", "亏损"]

A_SHARE_UNIVERSES = (("hs300", "000300"), )   # CSI1000 universe loader 未接入, 这里只用 hs300
# CSI1000 ticker 列表通过 akshare 直接拉, 不走 loader.get_universe


# ───────────────────────── Universe helpers ─────────────────────────

def fetch_universe_codes(loader: DataLoader, include_csi1000: bool = False) -> dict[str, list[str]]:
    """返回 {'hs300': [...], 'csi1000': [...]} 的成分股代码列表.

    CSI1000 默认不扫 (1000 ticker daily fetch 太重, 实测 ~10 min 远程 + 限流 risk).
    --include-csi1000 才开启, 调用方先确认 daily cache 已 prefetch.
    """
    out: dict[str, list[str]] = {"hs300": [], "csi1000": []}
    try:
        hs300 = loader.get_universe("a_share", "hs300")
        out["hs300"] = [str(c).zfill(6) for c in hs300["code"].tolist()]
    except Exception as e:
        print(f"[universe] HS300 ERROR: {e}", file=sys.stderr)

    if not include_csi1000:
        return out

    # 3 次 retry 防瞬时网络断
    for attempt in range(3):
        try:
            df = ak.index_stock_cons_csindex(symbol="000852")
            out["csi1000"] = [str(c).zfill(6) for c in df["成分券代码"].tolist()]
            break
        except Exception as e:
            if attempt == 2:
                print(f"[universe] CSI1000 ERROR after 3 retries: {e}", file=sys.stderr)
            else:
                time.sleep(2)
    return out


# ───────────────────────── Section 1+2: Panic + Rebound ─────────────────────────

@dataclass
class PanicCandidate:
    code: str
    universe: str
    drop_pct: float
    vol_ratio: float
    close: float
    dd_from_20d_high: float

@dataclass
class ReboundCandidate:
    code: str
    universe: str
    prior_drop_pct: float            # T-1
    prior_vol_ratio: float
    today_open_vs_prior_close: float  # T open / T-1 close - 1


def scan_panic_and_rebound(
    loader: DataLoader, codes_by_uni: dict[str, list[str]], target_date: str,
) -> tuple[list[PanicCandidate], list[ReboundCandidate]]:
    """扫每只股票最近 22 个交易日, 找 T (target_date) 的 panic / T (today) 的反包候选.

    'panic' = 当日 (target_date) 跌幅 ≤ -5% + 量比 > 1.5
    '反包候选' = T-1 panic 且 T (target_date) 开盘 > T-1 close × 1.01
    """
    panic_list: list[PanicCandidate] = []
    rebound_list: list[ReboundCandidate] = []
    end_dt = pd.to_datetime(target_date)
    start_dt = end_dt - pd.Timedelta(days=60)  # 留够 22 交易日 + buffer
    start_str = start_dt.strftime("%Y-%m-%d")

    for universe, codes in codes_by_uni.items():
        for code in codes:
            try:
                px = loader.get_daily("a_share", code, start_str, target_date)
            except Exception:
                continue
            if len(px) < 21:
                continue
            px = px.copy().reset_index(drop=True)
            px["ret"] = px["close"].pct_change()
            px["vol_ma20"] = px["volume"].rolling(20).mean()
            px["vol_ratio"] = px["volume"] / px["vol_ma20"]

            # T 行 = target_date 行 (允许 ≤ target_date 最后一行)
            tgt_rows = px[px["date"] <= target_date]
            if tgt_rows.empty:
                continue
            t_idx = tgt_rows.index[-1]
            t_row = px.loc[t_idx]
            t_ret = float(t_row["ret"]) if pd.notna(t_row["ret"]) else None
            t_vr = float(t_row["vol_ratio"]) if pd.notna(t_row["vol_ratio"]) else None

            # Panic (today)
            if t_ret is not None and t_vr is not None \
               and t_ret <= PANIC_THRESHOLDS[0] and t_vr >= VOL_RATIO_THRESHOLDS[0]:
                prior_20 = px.iloc[max(0, t_idx - 20):t_idx]
                high20 = float(prior_20["close"].max()) if len(prior_20) else float("nan")
                dd = (float(t_row["close"]) / high20 - 1.0) if high20 and high20 > 0 else float("nan")
                panic_list.append(PanicCandidate(
                    code=code, universe=universe,
                    drop_pct=t_ret, vol_ratio=t_vr,
                    close=float(t_row["close"]),
                    dd_from_20d_high=dd,
                ))

            # 反包 (today T, prior T-1 panic + today open jump > 1%)
            if t_idx >= 1:
                prev = px.loc[t_idx - 1]
                prev_ret = float(prev["ret"]) if pd.notna(prev["ret"]) else None
                prev_vr = float(prev["vol_ratio"]) if pd.notna(prev["vol_ratio"]) else None
                if prev_ret is not None and prev_vr is not None \
                   and prev_ret <= PANIC_THRESHOLDS[0] and prev_vr >= VOL_RATIO_THRESHOLDS[0]:
                    # T open
                    t_open = float(t_row["open"]) if pd.notna(t_row["open"]) else None
                    prev_close = float(prev["close"])
                    if t_open is not None and prev_close > 0:
                        gap = t_open / prev_close - 1.0
                        if gap >= REBOUND_PCT:
                            rebound_list.append(ReboundCandidate(
                                code=code, universe=universe,
                                prior_drop_pct=prev_ret,
                                prior_vol_ratio=prev_vr,
                                today_open_vs_prior_close=gap,
                            ))

    # 排序: panic 按 drop_pct 升序 (最 panic 在前); 反包按 gap 降序
    panic_list.sort(key=lambda x: x.drop_pct)
    rebound_list.sort(key=lambda x: -x.today_open_vs_prior_close)
    return panic_list, rebound_list


# ───────────────────────── Section 3: LHB 机构净买 ─────────────────────────

@dataclass
class LHBRow:
    code: str
    name: str
    date: str
    jg_net_buy_yuan: float
    reason: str
    pct_change: float | None = None


def fetch_lhb_top(target_date: str, lookback_days: int = LHB_LOOKBACK_DAYS, top_n: int = LHB_TOP_N) -> list[LHBRow]:
    """拉最近 lookback_days 个 *自然* 日的 LHB 机构净买, 按净额 top_n."""
    end_dt = pd.to_datetime(target_date)
    start_dt = end_dt - pd.Timedelta(days=lookback_days + 3)  # buffer for weekends
    try:
        df = ak.stock_lhb_jgmmtj_em(
            start_date=start_dt.strftime("%Y%m%d"),
            end_date=end_dt.strftime("%Y%m%d"),
        )
    except Exception as e:
        print(f"[LHB] ERROR: {e}", file=sys.stderr)
        return []
    if df is None or df.empty:
        return []

    jg_col = "机构买入净额" if "机构买入净额" in df.columns else "机构净买额"
    df["机构净买"] = pd.to_numeric(df[jg_col], errors="coerce")
    df = df.dropna(subset=["机构净买"])
    df = df.sort_values("机构净买", ascending=False).head(top_n)

    rows: list[LHBRow] = []
    for _, r in df.iterrows():
        rows.append(LHBRow(
            code=str(r.get("代码", "")).zfill(6),
            name=str(r.get("名称", "")),
            date=str(r.get("上榜日期", "")),
            jg_net_buy_yuan=float(r["机构净买"]),
            reason=str(r.get("上榜原因", "")),
            pct_change=float(r["涨跌幅"]) if "涨跌幅" in r and pd.notna(r["涨跌幅"]) else None,
        ))
    return rows


# ───────────────────────── Section 4: 大盘情绪 ─────────────────────────

@dataclass
class SentimentScore:
    source: str
    n_items: int
    n_bull: int
    n_bear: int
    score: float       # bull - bear, normalized [-1, 1]
    samples_bull: list[str] = field(default_factory=list)
    samples_bear: list[str] = field(default_factory=list)


def score_keywords(text: str) -> tuple[int, int]:
    bull = sum(1 for kw in SENTIMENT_BULL_KEYWORDS if kw in text)
    bear = sum(1 for kw in SENTIMENT_BEAR_KEYWORDS if kw in text)
    return bull, bear


def fetch_market_sentiment(target_date: str, quick: bool = False) -> list[SentimentScore]:
    """大盘情绪 (财新 + CCTV)."""
    out: list[SentimentScore] = []
    if quick:
        return out

    # 财新
    try:
        df = ak.stock_news_main_cx()
        if df is not None and not df.empty:
            n_bull = n_bear = 0
            samples_bull: list[str] = []
            samples_bear: list[str] = []
            for _, r in df.iterrows():
                text = str(r.get("summary", ""))
                b, br = score_keywords(text)
                n_bull += b
                n_bear += br
                if b > 0 and len(samples_bull) < 3:
                    samples_bull.append(text[:60])
                if br > 0 and len(samples_bear) < 3:
                    samples_bear.append(text[:60])
            denom = max(1, n_bull + n_bear)
            score = (n_bull - n_bear) / denom
            out.append(SentimentScore(
                source="财新 (caixin)", n_items=len(df),
                n_bull=n_bull, n_bear=n_bear, score=score,
                samples_bull=samples_bull, samples_bear=samples_bear,
            ))
    except Exception as e:
        print(f"[sentiment] 财新 ERROR: {e}", file=sys.stderr)

    # CCTV
    try:
        cctv_date = pd.to_datetime(target_date).strftime("%Y%m%d")
        df = ak.news_cctv(date=cctv_date)
        if df is not None and not df.empty:
            n_bull = n_bear = 0
            samples_bull: list[str] = []
            samples_bear: list[str] = []
            for _, r in df.iterrows():
                text = str(r.get("title", "")) + " " + str(r.get("content", ""))[:500]
                b, br = score_keywords(text)
                n_bull += b
                n_bear += br
                if b > 0 and len(samples_bull) < 3:
                    samples_bull.append(str(r.get("title", ""))[:60])
                if br > 0 and len(samples_bear) < 3:
                    samples_bear.append(str(r.get("title", ""))[:60])
            denom = max(1, n_bull + n_bear)
            score = (n_bull - n_bear) / denom
            out.append(SentimentScore(
                source=f"CCTV 新闻联播 ({cctv_date})", n_items=len(df),
                n_bull=n_bull, n_bear=n_bear, score=score,
                samples_bull=samples_bull, samples_bear=samples_bear,
            ))
    except Exception as e:
        print(f"[sentiment] CCTV ERROR: {e}", file=sys.stderr)

    return out


# ───────────────────────── Section 5: Sleeve overlap ─────────────────────────

@dataclass
class SleeveOverlap:
    sleeve: str
    candidates: list[str]     # codes from sleeve daily output
    overlap_with_panic: list[str]
    overlap_with_rebound: list[str]


def load_sleeve_candidates(json_path: Path, code_keys: tuple[str, ...]) -> list[str]:
    """从 report/data/<sleeve>.json 抽 candidate code list."""
    if not json_path.exists():
        return []
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    codes: list[str] = []
    # 适配多种 schema (zhuang.top_candidates / quant.signals / .candidates)
    for key in code_keys:
        v = data.get(key)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    c = item.get("code") or item.get("ticker")
                    if c:
                        codes.append(str(c).zfill(6))
                elif isinstance(item, str):
                    codes.append(str(item).zfill(6))
    return codes


def compute_sleeve_overlap(
    panic_codes: list[str], rebound_codes: list[str], data_dir: Path,
) -> list[SleeveOverlap]:
    sleeves: list[SleeveOverlap] = []
    panic_set = set(panic_codes)
    rebound_set = set(rebound_codes)

    sources = [
        ("zhuang", data_dir / "zhuang.json", ("top_candidates", "candidates", "signals")),
        ("A_mom (equity_momentum)", data_dir / "quant_a_share_equity_momentum.json",
         ("signals", "candidates", "positions")),
        ("A_mr (mean_reversion)", data_dir / "quant_a_share_mean_reversion.json",
         ("signals", "candidates", "positions")),
    ]
    for name, p, keys in sources:
        cands = load_sleeve_candidates(p, keys)
        sleeves.append(SleeveOverlap(
            sleeve=name,
            candidates=cands,
            overlap_with_panic=sorted(set(cands) & panic_set),
            overlap_with_rebound=sorted(set(cands) & rebound_set),
        ))
    return sleeves


# ───────────────────────── Render: HTML + JSON ─────────────────────────

def _pct(v: float | None, decimals=2) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "—"
    return f"{v*100:+.{decimals}f}%"

def _yi(v: float) -> str:
    if abs(v) >= 1e8:
        return f"{v/1e8:+.2f} 亿"
    if abs(v) >= 1e4:
        return f"{v/1e4:+.0f} 万"
    return f"{v:+.0f}"


def render_html(payload: dict, report_date: str) -> str:
    panic = payload["panic"]
    rebound = payload["rebound"]
    lhb = payload["lhb"]
    sentiment = payload["sentiment"]
    overlaps = payload["sleeve_overlap"]
    gen_at = payload["generated_at"]

    panic_rows = "\n".join(
        f"<tr><td><strong>{p['code']}</strong></td>"
        f"<td>{p['universe']}</td>"
        f"<td class='neg'>{_pct(p['drop_pct'])}</td>"
        f"<td>{p['vol_ratio']:.2f}×</td>"
        f"<td>{p['close']:.2f}</td>"
        f"<td class='neg'>{_pct(p['dd_from_20d_high'])}</td></tr>"
        for p in panic[:30]
    ) or "<tr><td colspan='6' class='muted center'>今日无 panic 候选</td></tr>"

    rebound_rows = "\n".join(
        f"<tr><td><strong>{r['code']}</strong></td>"
        f"<td>{r['universe']}</td>"
        f"<td class='neg'>{_pct(r['prior_drop_pct'])}</td>"
        f"<td>{r['prior_vol_ratio']:.2f}×</td>"
        f"<td class='pos'>{_pct(r['today_open_vs_prior_close'])}</td></tr>"
        for r in rebound[:30]
    ) or "<tr><td colspan='5' class='muted center'>今日无反包候选</td></tr>"

    def _jg_class(v: float) -> str:
        return "pos" if v > 0 else "neg"
    lhb_rows = "\n".join(
        f"<tr><td><strong>{r['code']}</strong></td>"
        f"<td>{r['name']}</td>"
        f"<td class='muted'>{r['date']}</td>"
        f"<td class='{_jg_class(r['jg_net_buy_yuan'])}'>{_yi(r['jg_net_buy_yuan'])}</td>"
        f"<td>{'+' if (r.get('pct_change') or 0) >= 0 else ''}{(r.get('pct_change') or 0):.1f}%</td>"
        f"<td class='muted'>{r['reason'][:30]}</td></tr>"
        for r in lhb
    ) or "<tr><td colspan='6' class='muted center'>无机构净买数据</td></tr>"

    senti_html = ""
    for s in sentiment:
        cls = "pos" if s["score"] > 0.1 else ("neg" if s["score"] < -0.1 else "muted")
        bull = "<br>".join(f"• {x}" for x in s["samples_bull"]) or "—"
        bear = "<br>".join(f"• {x}" for x in s["samples_bear"]) or "—"
        senti_html += f"""
        <div class='card'>
          <div class='card-header'>
            <span><strong>{s['source']}</strong> · {s['n_items']} items</span>
            <span class='{cls}' style='font-size:18px;font-weight:700'>{s['score']:+.2f}</span>
          </div>
          <div class='senti-body'>
            <div>多 keywords: <strong class='pos'>{s['n_bull']}</strong></div>
            <div>空 keywords: <strong class='neg'>{s['n_bear']}</strong></div>
            <div class='muted' style='margin-top:6px;font-size:11px'><strong>多样本:</strong><br>{bull}</div>
            <div class='muted' style='margin-top:6px;font-size:11px'><strong>空样本:</strong><br>{bear}</div>
          </div>
        </div>"""
    if not senti_html:
        senti_html = "<div class='muted center'>--quick 模式或 news 接口失败</div>"

    overlap_html = ""
    for o in overlaps:
        panic_str = ", ".join(o["overlap_with_panic"]) or "无"
        rebound_str = ", ".join(o["overlap_with_rebound"]) or "无"
        overlap_html += f"""
        <tr>
          <td><strong>{o['sleeve']}</strong></td>
          <td class='muted'>{len(o['candidates'])}</td>
          <td class='{'pos' if o['overlap_with_panic'] else 'muted'}'>{panic_str}</td>
          <td class='{'pos' if o['overlap_with_rebound'] else 'muted'}'>{rebound_str}</td>
        </tr>"""
    if not overlap_html:
        overlap_html = "<tr><td colspan='4' class='muted center'>无 sleeve JSON 数据</td></tr>"

    return f"""<!doctype html>
<html lang='zh'><head><meta charset='utf-8'>
<title>Panic Dashboard · {report_date}</title>
<style>
  :root {{ --bg:#FAFAFA; --card:#FFF; --border:#E5E5EA; --text:#1D1D1F; --muted:#86868B;
           --pos:#34C759; --neg:#FF3B30; --warn:#FF9500; }}
  body {{ background:var(--bg); color:var(--text); font: 14px/1.5 -apple-system, BlinkMacSystemFont, system-ui, sans-serif; margin:0; padding:24px; }}
  h1 {{ font-size:28px; margin:0 0 6px; }}
  .subtitle {{ color: var(--muted); margin-bottom:24px; font-size:13px; }}
  section {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:16px 20px; margin-bottom:16px; }}
  section h2 {{ font-size:18px; margin: 0 0 10px; }}
  table {{ width:100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--border); }}
  th {{ font-weight:600; color: var(--muted); background: #FAFAFA; }}
  .pos {{ color: var(--pos); }} .neg {{ color: var(--neg); }} .muted {{ color: var(--muted); }}
  .center {{ text-align:center; padding:18px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:12px; }}
  .card {{ background:#FAFAFA; border:1px solid var(--border); border-radius:8px; padding:12px; }}
  .card-header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; font-size:13px; }}
  .senti-body div {{ margin-bottom:4px; }}
  .footer {{ color: var(--muted); font-size:11px; margin-top:24px; text-align:center; }}
</style></head><body>

<h1>🔥 Panic / Capitulation Dashboard</h1>
<div class='subtitle'>报告日期: <strong>{report_date}</strong> · 生成于 {gen_at} · 辅助人工 T 决策, 不进 backtest / 不动 v5</div>

<section>
  <h2>① Panic candidates (今日跌 ≥ 5% + 量比 ≥ 1.5)</h2>
  <table><thead><tr><th>代码</th><th>universe</th><th>跌幅</th><th>量比</th><th>收盘</th><th>距 20d 高</th></tr></thead>
  <tbody>{panic_rows}</tbody></table>
  <div class='muted' style='font-size:11px;margin-top:6px'>共 {len(panic)} 候选, 显示前 30</div>
</section>

<section>
  <h2>② 反包候选 (T-1 panic + 今日开盘 > 昨收 1%)</h2>
  <table><thead><tr><th>代码</th><th>universe</th><th>T-1 跌幅</th><th>T-1 量比</th><th>T 开盘 gap</th></tr></thead>
  <tbody>{rebound_rows}</tbody></table>
  <div class='muted' style='font-size:11px;margin-top:6px'>共 {len(rebound)} 候选 (反包率历史 ~3% 极低)</div>
</section>

<section>
  <h2>③ LHB 机构净买 top {LHB_TOP_N} (最近 {LHB_LOOKBACK_DAYS} 日)</h2>
  <table><thead><tr><th>代码</th><th>名称</th><th>上榜日</th><th>机构净买</th><th>涨跌</th><th>上榜原因</th></tr></thead>
  <tbody>{lhb_rows}</tbody></table>
  <div class='muted' style='font-size:11px;margin-top:6px'>
    LHB 数据 T+1 公布 = 滞后 confirmation, 不作 entry trigger ([[capitulation_strategy_falsified_2026-06]])
  </div>
</section>

<section>
  <h2>④ 大盘情绪 (财新 + CCTV 关键词)</h2>
  <div class='grid'>{senti_html}</div>
  <div class='muted' style='font-size:11px;margin-top:8px'>
    个股新闻 akshare stock_news_em 死亡 (ArrowInvalid), 这里仅大盘情绪. score 范围 [-1, +1], 正多空少
  </div>
</section>

<section>
  <h2>⑤ Sleeve overlap (zhuang / A_mom / A_mr 当前候选 ∩ panic/反包)</h2>
  <table><thead><tr><th>Sleeve</th><th>候选 #</th><th>∩ panic</th><th>∩ rebound</th></tr></thead>
  <tbody>{overlap_html}</tbody></table>
  <div class='muted' style='font-size:11px;margin-top:6px'>有 overlap 的股票 = 既被 sleeve 选中又有 panic / 反包信号, 优先级高</div>
</section>

<div class='footer'>quant_system · daily_panic_dashboard · 不入 v5 组合 / 不动 yaml / 执行决策仍归用户</div>
</body></html>
"""


def _payload(panic, rebound, lhb, sentiment, overlaps) -> dict:
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "panic": [asdict(p) for p in panic],
        "rebound": [asdict(r) for r in rebound],
        "lhb": [asdict(r) for r in lhb],
        "sentiment": [asdict(s) for s in sentiment],
        "sleeve_overlap": [asdict(o) for o in overlaps],
    }


def main():
    p = argparse.ArgumentParser(description="Daily panic / capitulation dashboard 辅助人工 T")
    p.add_argument("--date", default=date.today().strftime("%Y-%m-%d"))
    p.add_argument("--open", action="store_true", dest="open_browser")
    p.add_argument("--quick", action="store_true", help="跳过大盘 news (节省 5-10s)")
    p.add_argument("--include-csi1000", action="store_true",
                   help="扫 CSI1000 1000 ticker (默认 off, 需先 prefetch daily cache)")
    args = p.parse_args()

    target = args.date
    t0 = time.time()
    print(f"=== panic_dashboard {target} ===")

    loader = DataLoader(cache_dir=ROOT / "data/cache", refresh_days=999)

    print("[1/5] universe fetch...")
    codes_by_uni = fetch_universe_codes(loader, include_csi1000=args.include_csi1000)
    n_total = sum(len(v) for v in codes_by_uni.values())
    print(f"  hs300={len(codes_by_uni['hs300'])}  csi1000={len(codes_by_uni['csi1000'])}  total={n_total}")

    print("[2/5] panic + 反包 scan...")
    panic, rebound = scan_panic_and_rebound(loader, codes_by_uni, target)
    print(f"  panic={len(panic)}  rebound={len(rebound)}")

    print("[3/5] LHB 机构净买...")
    lhb = fetch_lhb_top(target)
    print(f"  lhb top={len(lhb)}")

    print("[4/5] 大盘情绪...")
    sentiment = fetch_market_sentiment(target, quick=args.quick)
    print(f"  sources={len(sentiment)}")

    print("[5/5] sleeve overlap...")
    overlaps = compute_sleeve_overlap(
        [p.code for p in panic],
        [r.code for r in rebound],
        DATA_DIR,
    )
    print(f"  sleeves={len(overlaps)}")

    payload = _payload(panic, rebound, lhb, sentiment, overlaps)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    json_path = DATA_DIR / "panic_dashboard.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    html_path = REPORT_DIR / f"panic_dashboard_{target}.html"
    html_path.write_text(render_html(payload, target), encoding="utf-8")

    print(f"\nelapsed: {time.time()-t0:.1f}s")
    print(f"  JSON → {json_path}")
    print(f"  HTML → {html_path}")
    if args.open_browser:
        subprocess.Popen(["open", str(html_path)])


if __name__ == "__main__":
    main()
