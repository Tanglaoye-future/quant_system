#!/usr/bin/env python3
"""
v5 实盘月度 KPI 报告 — 为 2026-06-30 第一次 checkpoint 提前准备的脚手架.

读 journal_trades (equity_factor) + zhuang_trades (zhuang), 按 sleeve 聚合
当月 closed trades, 输出 markdown 报告.

v5 sleeve 映射 (见 memory/deployment_plan_2026-05.md):
  HK 25%      market='hk_share'  任意 strategy
  A_mom 10%   market='a_share' AND strategy='equity_momentum'
  A_mr 10%    market='a_share' AND strategy='mean_reversion'
  zhuang 40%  zhuang_trades 表全部
  QQQ 5%      buy-and-hold, 不进 journal (报告里手填或外部数据接)
  GLD 10%     buy-and-hold, 不进 journal

KPI 模板见 memory/v5_efficient_frontier_2026-05.md "3 月实盘验证 KPI checklist".

触发条件 (memory/v5_efficient_frontier_2026-05.md):
  - 任 sleeve win rate < 30% (滚动 30d) → 暂停建议
  - 组合月收益 < -2% → 立即诊断
  - 跨账户 60d 滚动 ρ > 0.50 → 重评配比

用法:
  python scripts/reporting/monthly_kpi_report.py --month 2026-06
  python scripts/reporting/monthly_kpi_report.py --month 2026-06 --aum-cny 1000000
  python scripts/reporting/monthly_kpi_report.py --mock   # dry-run 用 mock 数据
"""
from __future__ import annotations

import argparse
import calendar
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


# ---------------- v5 deployment plan ----------------

V5_WEIGHTS = {
    "HK": 0.25,
    "A_mom": 0.10,
    "A_mr": 0.10,
    "zhuang": 0.40,
    "QQQ": 0.05,
    "GLD": 0.10,
}

# 触发条件
ALERT_WIN_RATE_BELOW = 0.30
ALERT_PORTFOLIO_RETURN_BELOW = -0.02   # 月收益 < -2%
ALERT_CROSS_CORR_ABOVE = 0.50
ALERT_ZHUANG_AUM_OVER = 30_000_000     # zhuang 40% capacity 上限 30M RMB

# 各 sleeve 期望 (回测同期方向)
EXPECTED_SLEEVE_MTD_SHARPE_MIN = {
    "HK": 0.8,
    "A_mom": 0.3,
    "zhuang": 1.5,
}


# ---------------- data classes ----------------

@dataclass
class SleeveStats:
    name: str
    weight: float
    n_closed: int = 0
    n_winner: int = 0
    sum_pnl: float = 0.0          # 累计 PnL (currency units)
    mean_pnl_pct: float = 0.0     # 平均 trade 收益率
    notes: list[str] = None        # 异常告警

    def __post_init__(self):
        if self.notes is None:
            self.notes = []

    @property
    def win_rate(self) -> Optional[float]:
        return self.n_winner / self.n_closed if self.n_closed > 0 else None


# ---------------- core ----------------

def month_window(month_str: str) -> tuple[date, date]:
    """parse 'YYYY-MM' -> (first_day, last_day)"""
    y, m = month_str.split("-")
    y, m = int(y), int(m)
    last = calendar.monthrange(y, m)[1]
    return date(y, m, 1), date(y, m, last)


def _classify_equity_sleeve(trade: dict[str, Any]) -> Optional[str]:
    """journal_trades → HK / A_mom / A_mr / None"""
    market = trade.get("market")
    strat = trade.get("strategy")
    if market == "hk_share":
        return "HK"
    if market == "a_share":
        if strat == "equity_momentum":
            return "A_mom"
        if strat == "mean_reversion":
            return "A_mr"
    return None


def aggregate_equity(equity_journal, start: date, end: date) -> dict[str, SleeveStats]:
    """读 equity_factor Journal 当月 exit_date 内的 closed → HK/A_mom/A_mr 聚合"""
    sleeves = {k: SleeveStats(name=k, weight=V5_WEIGHTS[k]) for k in ["HK", "A_mom", "A_mr"]}
    closed = equity_journal.list_closed()
    for t in closed:
        ex = t.get("exit_date")
        if not ex:
            continue
        ex_d = ex if isinstance(ex, date) else datetime.fromisoformat(str(ex)).date()
        if not (start <= ex_d <= end):
            continue
        sname = _classify_equity_sleeve(t)
        if sname is None:
            continue
        s = sleeves[sname]
        s.n_closed += 1
        pnl = t.get("pnl") or 0.0
        pnl_pct = t.get("pnl_pct") or 0.0
        if pnl_pct > 0:
            s.n_winner += 1
        s.sum_pnl += pnl
        s.mean_pnl_pct += pnl_pct
    for s in sleeves.values():
        if s.n_closed:
            s.mean_pnl_pct /= s.n_closed
    return sleeves


def aggregate_zhuang(zhuang_journal, start: date, end: date) -> SleeveStats:
    s = SleeveStats(name="zhuang", weight=V5_WEIGHTS["zhuang"])
    closed = zhuang_journal.list_closed()
    for t in closed:
        ex = t.get("exit_date")
        if not ex:
            continue
        ex_d = ex if isinstance(ex, date) else datetime.fromisoformat(str(ex)).date()
        if not (start <= ex_d <= end):
            continue
        s.n_closed += 1
        pnl = t.get("pnl") or 0.0
        pnl_pct = t.get("pnl_pct") or 0.0
        if pnl_pct > 0:
            s.n_winner += 1
        s.sum_pnl += pnl
        s.mean_pnl_pct += pnl_pct
    if s.n_closed:
        s.mean_pnl_pct /= s.n_closed
    return s


def evaluate_alerts(sleeves: dict[str, SleeveStats], portfolio_ret: float,
                    zhuang_aum: float) -> list[str]:
    alerts: list[str] = []
    for name, s in sleeves.items():
        if s.win_rate is not None and s.win_rate < ALERT_WIN_RATE_BELOW and s.n_closed >= 5:
            alerts.append(f"⚠️  {name} win rate {s.win_rate*100:.1f}% < {ALERT_WIN_RATE_BELOW*100:.0f}% (n={s.n_closed}) — 建议暂停 sleeve")
    if portfolio_ret < ALERT_PORTFOLIO_RETURN_BELOW:
        alerts.append(f"🚨 组合月收益 {portfolio_ret*100:.2f}% < {ALERT_PORTFOLIO_RETURN_BELOW*100:.0f}% — 立即触发深度诊断")
    if zhuang_aum > ALERT_ZHUANG_AUM_OVER:
        alerts.append(f"⚠️  zhuang AUM 利用率 {zhuang_aum/1e6:.1f}M > 30M cap — 把 zhuang 权重压回 20-25%")
    return alerts


def render_markdown(month_str: str, sleeves: dict[str, SleeveStats], aum_cny: float,
                    portfolio_ret: float, alerts: list[str]) -> str:
    start, end = month_window(month_str)
    lines = [
        f"# v5 实盘月度 KPI 报告 — {month_str}",
        f"",
        f"- 窗口: {start} → {end}",
        f"- 起始 AUM: ¥{aum_cny:,.0f}",
        f"- v5 weights: HK 25 / A_mom 10 / A_mr 10 / zhuang 40 / QQQ 5 / GLD 10",
        f"",
        f"## 各 sleeve closed trades 摘要",
        f"",
        f"| sleeve | weight | n closed | n winner | win rate | sum pnl (¥) | mean trade % |",
        f"|---|---|---|---|---|---|---|",
    ]
    for name, s in sleeves.items():
        wr = f"{s.win_rate*100:.1f}%" if s.win_rate is not None else "n/a"
        lines.append(f"| {name} | {s.weight*100:.0f}% | {s.n_closed} | {s.n_winner} | {wr} | "
                     f"{s.sum_pnl:,.0f} | {s.mean_pnl_pct*100:+.2f}% |")
    lines += [
        f"",
        f"## 组合层 KPI",
        f"",
        f"- 当月 closed PnL 合计: ¥{sum(s.sum_pnl for s in sleeves.values()):,.0f}",
        f"- 组合月收益 (vs AUM): **{portfolio_ret*100:+.2f}%**",
        f"- 回测同期方向参考: v5 年化 8.6% / 12 ≈ +0.7%/月; 偏离 ±5pp 触发诊断",
        f"",
        f"## 未跟踪 sleeve (buy-and-hold)",
        f"",
        f"- QQQ (5%): 月度收益请手填 (yfinance/IBKR 对账单)",
        f"- GLD (10%): 月度收益请手填",
        f"",
        f"## 跨账户 60d 滚动 ρ",
        f"",
        f"- ⚠️  当前脚本仅聚合 closed trades, 不提供 daily equity series",
        f"- 严格 ρ 需要 daily snapshots 聚合 (TODO: Phase 2 — 接 JournalSnapshot daily price 算)",
        f"- 目标: <0.30 正常 / >0.50 重评配比",
        f"",
        f"## 告警 / 决策建议",
        f"",
    ]
    if alerts:
        for a in alerts:
            lines.append(f"- {a}")
    else:
        lines.append(f"- 无触发告警, 维持 v5 部署")
    lines += [
        f"",
        f"## 备注",
        f"",
        f"- 触发暂停 sleeve: win rate < 30% (n≥5) 或 sleeve 月收益 < -5%",
        f"- 触发深度诊断: 组合月收益 < -2%",
        f"- 触发再平衡: 季度边界 (2026-08-30) 或权重偏离 ±5pp",
        f"- 完整 checklist: memory/v5_efficient_frontier_2026-05.md",
    ]
    return "\n".join(lines) + "\n"


def run_report(month_str: str, aum_cny: float, equity_journal, zhuang_journal,
               qqq_ret: float = 0.0, gld_ret: float = 0.0) -> str:
    start, end = month_window(month_str)
    eq_sleeves = aggregate_equity(equity_journal, start, end)
    zh = aggregate_zhuang(zhuang_journal, start, end)
    sleeves = {**eq_sleeves, "zhuang": zh}

    # 组合月收益 = closed pnl / aum + buy-and-hold sleeve 月收益 × weight
    closed_pnl_total = sum(s.sum_pnl for s in sleeves.values())
    portfolio_ret = closed_pnl_total / aum_cny if aum_cny > 0 else 0.0
    portfolio_ret += qqq_ret * V5_WEIGHTS["QQQ"] + gld_ret * V5_WEIGHTS["GLD"]

    # zhuang AUM 估算: 当月 sum_pnl 仅是已平仓收益, 不代表 deployed AUM
    # 简化: 用 sleeve 权重估算 deployed AUM (40% × aum)
    zhuang_aum = aum_cny * V5_WEIGHTS["zhuang"]

    alerts = evaluate_alerts(sleeves, portfolio_ret, zhuang_aum)
    md = render_markdown(month_str, sleeves, aum_cny, portfolio_ret, alerts)
    return md


# ---------------- entry ----------------

def _mock_journals():
    """dry-run: 内存 SQLite 注入 mock trades 验证渲染"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from quant_system.db.models import Base
    from quant_system.strategies.equity_factor.journal.journal import Journal, TradeOpen
    from quant_system.strategies.zhuang.journal.journal import (
        ZhuangJournal,
        TradeOpen as ZhuangTradeOpen,
    )

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sm = sessionmaker(bind=engine, expire_on_commit=False)
    j = Journal(sessionmaker=sm)
    zj = ZhuangJournal(sessionmaker=sm)

    # 注入 HK 1 winner / 1 loser
    tid = j.open_trade(TradeOpen(symbol="00700", market="hk_share",
                                 strategy="equity_hk_momentum",
                                 entry_date="2026-06-05", entry_price=300.0,
                                 entry_size=100, entry_score=8.0,
                                 stop_loss_price=270.0))
    j.close_trade(tid, exit_date="2026-06-15", exit_price=330.0, exit_reason="target")
    tid = j.open_trade(TradeOpen(symbol="00939", market="hk_share",
                                 strategy="equity_hk_momentum",
                                 entry_date="2026-06-10", entry_price=5.0,
                                 entry_size=10000, entry_score=7.0,
                                 stop_loss_price=4.5))
    j.close_trade(tid, exit_date="2026-06-20", exit_price=4.6, exit_reason="stop_loss")

    # A_mom 1 winner
    tid = j.open_trade(TradeOpen(symbol="601939", market="a_share",
                                 strategy="equity_momentum",
                                 entry_date="2026-06-08", entry_price=10.0,
                                 entry_size=1000, entry_score=8.0,
                                 stop_loss_price=9.0))
    j.close_trade(tid, exit_date="2026-06-25", exit_price=11.0, exit_reason="target")

    # zhuang 2 winners 1 loser
    for code, ep, xp, ed_in, ed_out in [
        ("600575", 4.0, 4.4, "2026-06-03", "2026-06-13"),
        ("000601", 3.0, 3.2, "2026-06-12", "2026-06-22"),
        ("002500", 5.0, 4.5, "2026-06-18", "2026-06-28"),
    ]:
        tid = zj.open_trade(ZhuangTradeOpen(code=code, market="a_share",
                                            entry_date=ed_in, entry_price=ep,
                                            entry_size=1000,
                                            accumulation_score=75.0,
                                            phase="A",
                                            stop_loss_price=ep * 0.95))
        zj.close_trade(tid, exit_date=ed_out, exit_price=xp,
                       exit_reason="take_profit")

    return j, zj


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--month", default=None,
                   help="YYYY-MM (default = 上月)")
    p.add_argument("--aum-cny", type=float, default=1_000_000.0,
                   help="起始 AUM CNY (default 1M)")
    p.add_argument("--qqq-return", type=float, default=0.0,
                   help="QQQ 当月收益 (decimal, 手填)")
    p.add_argument("--gld-return", type=float, default=0.0,
                   help="GLD 当月收益 (decimal, 手填)")
    p.add_argument("--output-dir", default="report",
                   help="markdown 输出目录")
    p.add_argument("--mock", action="store_true",
                   help="dry-run: 用内存 SQLite + mock trades, 不连 PG")
    args = p.parse_args()

    if args.month is None:
        today = date.today()
        # 默认上月
        if today.month == 1:
            args.month = f"{today.year - 1}-12"
        else:
            args.month = f"{today.year}-{today.month - 1:02d}"

    if args.mock:
        eq_j, zh_j = _mock_journals()
    else:
        from quant_system.strategies.equity_factor.journal.journal import Journal
        from quant_system.strategies.zhuang.journal.journal import ZhuangJournal
        eq_j = Journal()
        zh_j = ZhuangJournal()

    md = run_report(args.month, args.aum_cny, eq_j, zh_j,
                    qqq_ret=args.qqq_return, gld_ret=args.gld_return)

    out_dir = ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"monthly_kpi_{args.month}.md"
    out_path.write_text(md, encoding="utf-8")
    print(md)
    print(f"\n[出口] {out_path}")


if __name__ == "__main__":
    main()
