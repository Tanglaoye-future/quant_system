#!/usr/bin/env python3
"""
策略日报生成器.

读取 report/data/{quant,options,zhuang}.json → 渲染 HTML 报告

用法:
  python report/report_builder.py                    # 今日报告
  python report/report_builder.py --date 2026-05-10  # 指定日期
  python report/report_builder.py --open             # 生成后自动打开浏览器

各系统 JSON 输出路径（相对 quant_system/）：
  quant_system/scripts/daily_run.py     → report/data/quant.json
  options_system/scripts/daily_signal.py → report/data/options.json (via QUANT_REPORT_DATA 或相对路径)
  zhuang_system/scripts/scan_today.py   → report/data/zhuang.json  (via QUANT_REPORT_DATA 或相对路径)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from quant_system.config import PROJECT_ROOT

REPORT_DIR = PROJECT_ROOT / "report"   # repo_root/report/
DATA = REPORT_DIR / "data"             # repo_root/report/data/


def load(system: str) -> dict:
    """加载系统的最新 JSON 信号，不存在则返回空占位。"""
    path = DATA / f"{system}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"_missing": True, "system": system}


def pct(v, decimals=1):
    if v is None: return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v*100:.{decimals}f}%"

def fmt(v, decimals=2):
    if v is None: return "—"
    return f"{v:.{decimals}f}"

def color_class(v, positive_good=True):
    if v is None: return ""
    good = v >= 0 if positive_good else v <= 0
    return "pos" if good else "neg"


def render(q: dict, o: dict, z: dict, report_date: str) -> str:
    # ── quant helpers ──────────────────────────────────────────────────────
    q_signals = q.get("signals", [])
    # 按策略来源统计
    from collections import Counter
    q_src_counts = Counter(s.get("_source", "未知") for s in q_signals)
    q_status_text = "空仓待机" if not q_signals and not q.get("positions") else \
        f"{len(q_signals)}只信号 (HK {q_src_counts.get('HK 港股 · momentum',0)} · A_mom {q_src_counts.get('A 股 · momentum',0)} · A_mr {q_src_counts.get('A 股 · mean-reversion',0)})"
    q_status_badge = "badge-idle" if not q.get("signals") else "badge-pass"
    q_bench = q.get("benchmark_close", "—")
    q_ma60  = q.get("benchmark_ma60", "—")
    q_gate  = q.get("market_gate", None)
    q_gate_txt = ("通过 · close > MA60" if q_gate else "关闭 · close < MA60") if q_gate is not None else "—"
    q_gate_cls = "pos" if q_gate else "neg"
    q_positions = q.get("positions", [])
    q_missing = q.get("_missing", False)

    # ── options helpers ────────────────────────────────────────────────────
    o_status_text = "有信号" if o.get("signal") else "无信号"
    o_status_badge = "badge-pass" if o.get("signal") else "badge-warn"
    o_ivr   = o.get("ivr", None)
    o_mode  = o.get("iv_mode", "—")
    o_qqq   = o.get("qqq_price", None)
    o_rsi   = o.get("qqq_rsi", None)
    o_reason = o.get("reason", "—")
    o_signal = o.get("signal") or {}
    o_missing = o.get("_missing", False)

    # ── zhuang helpers ─────────────────────────────────────────────────────
    z_count  = z.get("candidates_count", 0)
    z_univ   = z.get("universe_size", "—")
    z_trend  = z.get("market_trend", None)
    z_date   = z.get("date", report_date)
    z_top    = z.get("top_candidates", [])
    z_max_score = z_top[0].get("total", 0) if z_top else 0
    z_status_badge = "badge-pass" if z_count > 0 else "badge-idle"
    z_missing = z.get("_missing", False)

    # ── quant signals rows ──────────────────────────────────────────────────
    def signal_rows(signals):
        if not signals:
            return "<tr><td colspan='6' style='color:var(--muted);text-align:center;padding:20px'>今日无买入信号</td></tr>"
        rows = ""
        for s in signals:
            source = s.get("_source", "")
            source_badge = f"<span class='badge badge-idle' style='font-size:11px'>{source}</span>" if source else ""
            rows += f"""
            <tr>
              <td><strong>{s.get('code','—')}</strong></td>
              <td>{s.get('name','—')}</td>
              <td>{source_badge}</td>
              <td class='{color_class(s.get("score",0))}'>{fmt(s.get('score',0))}</td>
              <td>{s.get('reason','—')}</td>
              <td class='pos'>{s.get('suggested_action','买入')}</td>
            </tr>"""
        return rows

    def position_rows(positions):
        if not positions:
            return "<tr><td colspan='6' style='color:var(--muted);text-align:center;padding:20px'>当前空仓</td></tr>"
        rows = ""
        for p in positions:
            pnl = p.get('pnl_pct')
            rows += f"""
            <tr>
              <td><strong>{p.get('code','—')}</strong></td>
              <td>{p.get('name','—')}</td>
              <td>{p.get('entry_date','—')}</td>
              <td>{p.get('hold_days','—')}日</td>
              <td class='{color_class(pnl)}'>{pct(pnl)}</td>
              <td>{p.get('action','持有')}</td>
            </tr>"""
        return rows

    # ── zhuang candidate rows ───────────────────────────────────────────────
    def zhuang_rows(candidates):
        if not candidates:
            return "<tr><td colspan='8' style='color:var(--muted);text-align:center;padding:20px'>无候选</td></tr>"
        rows = ""
        for i, c in enumerate(candidates[:15], 1):
            score = c.get('total', 0)
            score_color = "pos" if score >= 65 else ("warn" if score >= 55 else "")
            rows += f"""
            <tr>
              <td>{i}</td>
              <td><strong>{c.get('code','—')}</strong></td>
              <td>{fmt(c.get('ma_convergence',0),1)}</td>
              <td>{fmt(c.get('volume_asymmetry',0),1)}</td>
              <td>{fmt(c.get('price_consolidation',0),1)}</td>
              <td>{fmt(c.get('turnover_decline',0),1)}</td>
              <td>{fmt(c.get('vp_divergence',0),1)}</td>
              <td><span class='{score_color}' style='font-weight:700'>{fmt(score,1)}</span></td>
            </tr>"""
        return rows

    # ── options signal detail ───────────────────────────────────────────────
    o_signal_html = ""
    if o_signal:
        o_signal_html = f"""
        <div style="margin-top:12px;padding:14px;background:#0d1117;border:1px solid var(--border);border-radius:8px;">
          <div style="font-weight:600;margin-bottom:8px;color:var(--green)">📋 今日信号：{o_signal.get('type','—')}</div>
          <div class="signal-row"><span class="signal-key">结构</span><span>{o_signal.get('structure','—')}</span></div>
          <div class="signal-row"><span class="signal-key">买腿</span><span>{o_signal.get('buy_leg','—')}</span></div>
          <div class="signal-row"><span class="signal-key">卖腿</span><span>{o_signal.get('sell_leg','—')}</span></div>
          <div class="signal-row"><span class="signal-key">最大盈利</span><span class='pos'>{o_signal.get('max_profit','—')}</span></div>
          <div class="signal-row"><span class="signal-key">最大亏损</span><span class='neg'>{o_signal.get('max_loss','—')}</span></div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>量化策略日报 · {report_date}</title>
<style>
  :root {{
    --bg:#0d1117;--card:#161b22;--border:#30363d;
    --text:#e6edf3;--muted:#7d8590;--accent:#58a6ff;
    --green:#3fb950;--red:#f85149;--yellow:#d29922;
    --orange:#db6d28;--purple:#bc8cff;--cyan:#39d353;
    --pass:#1a7f37;--fail:#6e1c1c;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:'SF Pro Text',-apple-system,'Segoe UI',sans-serif;font-size:14px;line-height:1.6}}
  .wrap{{max-width:1200px;margin:0 auto;padding:32px 24px}}
  header{{border-bottom:1px solid var(--border);padding-bottom:24px;margin-bottom:32px;display:flex;justify-content:space-between;align-items:flex-end}}
  header h1{{font-size:22px;font-weight:600}}
  header .sub{{color:var(--muted);font-size:13px;margin-top:4px}}
  .badge{{display:inline-block;padding:2px 10px;border-radius:20px;font-size:12px;font-weight:600}}
  .badge-pass{{background:var(--pass);color:#56d364}}
  .badge-fail{{background:var(--fail);color:#ff7b72}}
  .badge-idle{{background:#21262d;color:var(--muted)}}
  .badge-warn{{background:#2d2108;color:var(--yellow)}}
  .section{{margin-bottom:40px}}
  .section-title{{font-size:18px;font-weight:600;margin-bottom:16px;display:flex;align-items:center;gap:10px}}
  .dot{{width:10px;height:10px;border-radius:50%;flex-shrink:0}}
  .dot-blue{{background:var(--accent)}}.dot-green{{background:var(--green)}}.dot-purple{{background:var(--purple)}}
  .card{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:20px 24px;margin-bottom:16px}}
  .card-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;padding-bottom:12px;border-bottom:1px solid var(--border)}}
  .card-title{{font-size:15px;font-weight:600}}
  .card-sub{{color:var(--muted);font-size:12px;margin-top:2px}}
  .metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin-bottom:16px}}
  .metric{{background:#0d1117;border:1px solid var(--border);border-radius:8px;padding:12px 14px}}
  .metric-label{{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px}}
  .metric-value{{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums}}
  .metric-sub{{color:var(--muted);font-size:11px;margin-top:3px}}
  .pos{{color:var(--green)}}.neg{{color:var(--red)}}.neu{{color:var(--accent)}}.warn{{color:var(--yellow)}}
  table{{width:100%;border-collapse:collapse;font-size:13px}}
  th{{text-align:left;padding:8px 12px;color:var(--muted);font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.4px;border-bottom:1px solid var(--border);background:#0d1117}}
  td{{padding:9px 12px;border-bottom:1px solid #21262d}}
  tr:last-child td{{border-bottom:none}}
  tr:hover td{{background:#1c2128}}
  .sys-bar{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:32px}}
  .sys-card{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:18px 20px}}
  .sys-name{{font-size:13px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}}
  .sys-status{{font-size:22px;font-weight:700;margin-bottom:10px}}
  .sys-desc{{font-size:12px;color:var(--muted)}}
  .table-wrap{{overflow-x:auto;border-radius:8px;border:1px solid var(--border)}}
  .signal-box{{background:#0d1117;border:1px solid var(--border);border-radius:8px;padding:16px 18px;margin-top:12px}}
  .signal-row{{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #21262d;font-size:13px}}
  .signal-row:last-child{{border-bottom:none}}
  .signal-key{{color:var(--muted)}}
  .chip{{display:inline-block;padding:1px 7px;border-radius:4px;font-size:11px;background:#1c2128;color:var(--muted)}}
  .chip-pass{{background:rgba(63,185,80,.12);color:var(--green)}}
  .chip-fail{{background:rgba(248,81,73,.12);color:var(--red)}}
  .chip-warn{{background:rgba(210,153,34,.12);color:var(--yellow)}}
  .tag{{display:inline-block;padding:2px 8px;background:#1c2128;color:var(--accent);border-radius:4px;font-size:11px;font-weight:500;margin-left:8px}}
  .ts{{color:var(--muted);font-size:11px;text-align:right;margin-top:6px}}
  footer{{margin-top:48px;padding-top:24px;border-top:1px solid var(--border);color:var(--muted);font-size:12px;display:flex;justify-content:space-between}}
</style>
</head>
<body>
<div class="wrap">

<header>
  <div>
    <h1>量化策略日报</h1>
    <div class="sub">生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')} &nbsp;|&nbsp; 三策略联合运行报告 &nbsp;|&nbsp; A股中线 · 美股期权 · 庄股小盘</div>
  </div>
  <div style="text-align:right">
    <div style="font-size:13px;color:var(--muted)">沪深300</div>
    <div style="font-size:18px;font-weight:700;color:{'var(--green)' if q_gate else 'var(--red)'}">
      {q_bench if q_bench != '—' else '—'}
    </div>
    <div style="font-size:12px;color:var(--muted);margin-top:2px">MA60: {q_ma60}</div>
  </div>
</header>

<!-- 系统概览 -->
<div class="sys-bar">
  <div class="sys-card">
    <div class="sys-name">quant_system · A股中线</div>
    <div class="sys-status neu">{q_status_text}</div>
    <div class="sys-desc">
      市况门{'通过' if q_gate else '关闭'} · 今日{len(q_signals)}只触发<br>
      持仓{len(q_positions)}只 · universe HS300
    </div>
  </div>
  <div class="sys-card">
    <div class="sys-name">options_system · QQQ期权</div>
    <div class="sys-status {'pos' if o_signal else 'warn'}">{o_status_text}</div>
    <div class="sys-desc">
      IVR={fmt(o_ivr,1) if o_ivr is not None else '—'} ({o_mode}) · QQQ ${fmt(o_qqq,2) if o_qqq else '—'}<br>
      RSI={fmt(o_rsi,1) if o_rsi is not None else '—'} · {o_reason[:30] if o_reason else '—'}
    </div>
  </div>
  <div class="sys-card">
    <div class="sys-name">zhuang_system · 庄股小盘</div>
    <div class="sys-status {'pos' if z_count>0 else 'neu'}">{z_count} 候选</div>
    <div class="sys-desc">
      universe {z_univ}只 (50–2000亿) · score≥45<br>
      最高分: {fmt(z_max_score,1)} · 入场门槛65分
    </div>
  </div>
</div>

<!-- QUANT SYSTEM -->
<div class="section">
  <div class="section-title"><span class="dot dot-blue"></span>quant_system <span class="tag">A股中线量化</span></div>

  {'<div style="padding:12px 16px;background:#21262d;border-radius:8px;color:var(--muted);font-size:13px;margin-bottom:12px;">⚠ 今日数据未读取到，请先运行 daily_run.py</div>' if q_missing else ''}

  <div class="card">
    <div class="card-header">
      <div><div class="card-title">今日运行结果</div><div class="card-sub">日期：{q.get('date', report_date)}</div></div>
      <span class="badge {q_status_badge}">{q_status_text}</span>
    </div>
    <div class="metrics">
      <div class="metric"><div class="metric-label">持仓数</div><div class="metric-value neu">{len(q_positions)}</div><div class="metric-sub">最大6仓</div></div>
      <div class="metric"><div class="metric-label">买入候选</div><div class="metric-value {'pos' if q_signals else 'neu'}">{len(q_signals)}</div><div class="metric-sub">今日信号</div></div>
      <div class="metric"><div class="metric-label">HS300</div><div class="metric-value {'pos' if q_gate else 'neg'}">{q_bench}</div><div class="metric-sub">MA60: {q_ma60}</div></div>
      <div class="metric"><div class="metric-label">M2市况门</div><div class="metric-value {'pos' if q_gate else 'neg'}">{'OK' if q_gate else 'CLOSE'}</div><div class="metric-sub">{'允许开仓' if q_gate else '禁止开仓'}</div></div>
    </div>
  </div>

  <div class="card">
    <div class="card-header"><div class="card-title">今日买入候选</div></div>
    <div class="table-wrap">
    <table>
      <thead><tr><th>代码</th><th>名称</th><th>策略</th><th>评分</th><th>入场理由</th><th>建议</th></tr></thead>
      <tbody>{signal_rows(q_signals)}</tbody>
    </table>
    </div>
  </div>

  <div class="card">
    <div class="card-header"><div class="card-title">当前持仓</div></div>
    <div class="table-wrap">
    <table>
      <thead><tr><th>代码</th><th>名称</th><th>入场日</th><th>持有天</th><th>浮盈</th><th>操作</th></tr></thead>
      <tbody>{position_rows(q_positions)}</tbody>
    </table>
    </div>
  </div>
</div>

<!-- OPTIONS SYSTEM -->
<div class="section">
  <div class="section-title"><span class="dot dot-green"></span>options_system <span class="tag">QQQ期权套利</span></div>

  {'<div style="padding:12px 16px;background:#21262d;border-radius:8px;color:var(--muted);font-size:13px;margin-bottom:12px;">⚠ 今日数据未读取到，请先运行 daily_signal.py</div>' if o_missing else ''}

  <div class="card">
    <div class="card-header">
      <div><div class="card-title">今日期权扫描</div><div class="card-sub">日期：{o.get('date', report_date)}</div></div>
      <span class="badge {o_status_badge}">{o_status_text}</span>
    </div>
    <div class="metrics">
      <div class="metric"><div class="metric-label">VXN</div><div class="metric-value warn">{fmt(o_ivr,2) if o_ivr else '—'}</div><div class="metric-sub">CBOE Nasdaq VIX</div></div>
      <div class="metric"><div class="metric-label">IVR排名</div><div class="metric-value warn">{fmt(o_ivr,1) if o_ivr else '—'}</div><div class="metric-sub">{o_mode}</div></div>
      <div class="metric"><div class="metric-label">QQQ价格</div><div class="metric-value pos">${fmt(o_qqq,2) if o_qqq else '—'}</div><div class="metric-sub">MA200跟踪中</div></div>
      <div class="metric"><div class="metric-label">RSI(14)</div><div class="metric-value {'neg' if o_rsi and o_rsi>75 else 'warn' if o_rsi and o_rsi>65 else 'pos'}">{fmt(o_rsi,1) if o_rsi else '—'}</div><div class="metric-sub">{'⚠ 超买' if o_rsi and o_rsi>75 else '正常区间'}</div></div>
    </div>
    <div class="signal-box">
      <div class="signal-row"><span class="signal-key">IV状态</span><span class="{'pos' if o_mode=='HIGH_IV' else 'warn'}">{o_mode} · IVR={fmt(o_ivr,1) if o_ivr else '—'}</span></div>
      <div class="signal-row"><span class="signal-key">QQQ趋势</span><span class="pos">上升趋势中</span></div>
      <div class="signal-row"><span class="signal-key">不操作原因</span><span class="neg">{o_reason}</span></div>
      <div class="signal-row"><span class="signal-key">今日结论</span><span class="{'pos' if o_signal else 'warn'}">{'有信号 · 参见下方详情' if o_signal else '无信号 · 继续观察'}</span></div>
    </div>
    {o_signal_html}
  </div>
</div>

<!-- ZHUANG SYSTEM -->
<div class="section">
  <div class="section-title"><span class="dot dot-purple"></span>zhuang_system <span class="tag">A股庄股小盘跟庄</span></div>

  {'<div style="padding:12px 16px;background:#21262d;border-radius:8px;color:var(--muted);font-size:13px;margin-bottom:12px;">⚠ 今日数据未读取到，请先运行 scan_today.py</div>' if z_missing else ''}

  <div class="card">
    <div class="card-header">
      <div><div class="card-title">吃货期扫描 · {z_date}</div><div class="card-sub">universe {z_univ}只 · 候选{z_count}只(≥45分) · 展示TOP 15</div></div>
      <span class="badge {z_status_badge}">{z_count} 候选</span>
    </div>
    <div class="metrics">
      <div class="metric"><div class="metric-label">Universe</div><div class="metric-value neu">{z_univ}</div><div class="metric-sub">50–2000亿</div></div>
      <div class="metric"><div class="metric-label">候选数(≥45)</div><div class="metric-value {'pos' if z_count>0 else 'neu'}">{z_count}</div><div class="metric-sub">今日</div></div>
      <div class="metric"><div class="metric-label">最高评分</div><div class="metric-value {'pos' if z_max_score>=65 else 'warn'}">{fmt(z_max_score,1)}</div><div class="metric-sub">入场门槛65</div></div>
      <div class="metric"><div class="metric-label">市场趋势</div><div class="metric-value {'pos' if z_trend else 'neg'}">{'金叉OK' if z_trend else '趋势未达'}</div><div class="metric-sub">CSI500 MA60+金叉</div></div>
    </div>
    <div class="table-wrap">
    <table>
      <thead><tr><th>#</th><th>代码</th><th>MA收敛</th><th>量价不对称</th><th>价格横盘</th><th>换手下降</th><th>量价背离</th><th>综合评分</th></tr></thead>
      <tbody>{zhuang_rows(z_top)}</tbody>
    </table>
    </div>
    <div style="margin-top:10px;color:var(--muted);font-size:12px">
      {'⚠ 最高分未达实盘门槛(65分)，今日仅监控，不建议入场。' if z_max_score < 65 else '✅ 存在达到实盘门槛的候选，请进一步人工确认。'}<br>
      权重：MA收敛×0.20 · 量价不对称×0.30 · 价格横盘×0.20 · 换手下降×0.15 · 量价背离×0.15
    </div>
  </div>
</div>

<footer>
  <div>生成：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} &nbsp;|&nbsp; Claude Sonnet 4.6 &nbsp;|&nbsp; report_builder.py v2.1</div>
  <div>本报告仅供研究参考，不构成投资建议</div>
</footer>

</div>
</body>
</html>"""


def load_quant_multi() -> dict:
    """加载 quant_system 的 3 个子策略 JSON，合并为统一 dict 传入 render。
    兼容旧版定量系统只输出一个 quant.json 的情况（降级读取）。"""
    sources = [
        ("quant_hk_share_bottomup_timing.json",   "HK 港股 · momentum"),
        ("quant_a_share_bottomup_timing.json",    "A 股 · momentum"),
        ("quant_a_share_mean_reversion.json",     "A 股 · mean-reversion"),
    ]
    # 旧版兼容：如果三个文件都不存在，fallback 到旧的 quant.json
    any_found = any((DATA / f).exists() for f, _ in sources)
    if not any_found and (DATA / "quant.json").exists():
        return load("quant")

    merged_signals = []
    merged_positions = []
    merged_market = ""
    merged_gate = None
    merged_gate_msg = ""
    merged_date = ""

    for filename, label in sources:
        path = DATA / filename
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        merged_date = data.get("date", merged_date)
        merged_market = merged_market or data.get("market", "")
        if data.get("market_gate") is not None:
            merged_gate = data["market_gate"]
            merged_gate_msg = data.get("market_gate_msg", "")
        for s in data.get("signals", []):
            s = dict(s)
            s.setdefault("name", "")
            s["_source"] = label  # strategy label for display
            merged_signals.append(s)
        for p in data.get("positions", []):
            p = dict(p)
            p.setdefault("name", "")
            p["_source"] = label
            merged_positions.append(p)

    return {
        "date": merged_date,
        "market": merged_market,
        "market_gate": merged_gate,
        "market_gate_msg": merged_gate_msg,
        "benchmark_close": "—",
        "benchmark_ma60": "—",
        "signals": merged_signals,
        "positions": merged_positions,
    }


def main():
    p = argparse.ArgumentParser(description="量化策略日报生成器")
    p.add_argument("--date", default=date.today().strftime("%Y-%m-%d"))
    p.add_argument("--open", action="store_true", dest="open_browser")
    args = p.parse_args()

    q = load_quant_multi()
    o = load("options")
    z = load("zhuang")

    html = render(q, o, z, args.date)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"strategy_report_{args.date}.html"
    out.write_text(html, encoding="utf-8")
    print(f"[report] 已生成 → {out}")

    if args.open_browser:
        subprocess.Popen(["open", str(out)])


if __name__ == "__main__":
    main()
