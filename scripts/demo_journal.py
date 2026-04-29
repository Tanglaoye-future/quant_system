"""
端到端验证 journal: 开 2 笔, 加快照, 平 1 笔, 出归因报告.
跑完会留 1 笔在 open / 1 笔在 closed, 方便后续模块对接.
"""
from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_system.config import load_config
from quant_system.journal.journal import Journal, TradeOpen


def main() -> None:
    cfg = load_config()
    j = Journal(cfg.journal_db_path)
    j.init_schema()

    # ------------ 开仓 1: 平安银行 (会被平仓) ------------
    t1 = TradeOpen(
        symbol="000001",
        market="a_share",
        entry_date="2026-04-20",
        entry_price=12.50,
        entry_size=1000,
        entry_score=0.813,
        reason_topdown="经济复苏期, 金融板块景气",
        reason_bottomup="PE_TTM 5.1, ROE 11% (年化), 营收增长 4.65%, 因子总分 HS300 第一",
        reason_catalyst="一季报披露在即, 管理层换届完成",
        reason_timing="20MA 上穿 60MA, RSI(14)=58, 突破日成交量 1.6x",
        stop_loss_price=11.80,
        take_profit_price=14.50,
        notes="计划持有 30-45 个交易日",
    )
    id1 = j.open_trade(t1)
    print(f"开仓 #{id1}: 平安银行 1000 股 @ 12.50, 止损 11.80, 止盈 14.50")

    # ------------ 开仓 2: 中联重科 (会留在 open) ------------
    t2 = TradeOpen(
        symbol="000157",
        market="a_share",
        entry_date="2026-04-22",
        entry_price=8.20,
        entry_size=1500,
        entry_score=0.170,
        reason_topdown="基建+一带一路再启动, 工程机械周期回暖",
        reason_bottomup="ROE 8.34%, 营收同比 +14.58%, PB 仅 1.19",
        reason_catalyst="出口数据连续 3 个月超预期",
        reason_timing="60 日新高 + 量能温和放大",
        stop_loss_price=7.50,
        take_profit_price=10.00,
    )
    id2 = j.open_trade(t2)
    print(f"开仓 #{id2}: 中联重科 1500 股 @ 8.20")

    # ------------ 持仓快照 (模拟每日盘后跑) ------------
    j.add_snapshot(id1, "2026-04-23", 12.85, risk_flag="normal")
    j.add_snapshot(id1, "2026-04-24", 13.20, risk_flag="normal", note="放量上攻")
    j.add_snapshot(id1, "2026-04-25", 13.55, risk_flag="normal")
    j.add_snapshot(id2, "2026-04-23", 8.15, risk_flag="normal")
    j.add_snapshot(id2, "2026-04-24", 8.05, risk_flag="drawdown", note="回踩 5 日线")
    j.add_snapshot(id2, "2026-04-25", 8.30, risk_flag="normal")
    print(f"已写入 6 条持仓快照")

    # ------------ 平仓 #1 (止盈) ------------
    j.close_trade(id1, exit_date="2026-05-15", exit_price=14.65, exit_reason="take_profit")
    print(f"平仓 #{id1}: 14.65 (触及止盈, 持有 25 天)")

    # ------------ 输出当前状态 ------------
    print()
    print("=== 当前未平仓 ===")
    for r in j.list_open():
        print(f"  #{r['id']} {r['symbol']} entry={r['entry_price']} "
              f"size={r['entry_size']} stop={r['stop_loss_price']} target={r['take_profit_price']}")

    print()
    print("=== 已平仓 ===")
    for r in j.list_closed():
        print(f"  #{r['id']} {r['symbol']} {r['entry_date']} -> {r['exit_date']} "
              f"({r['hold_days']} 天) 收益 {r['pnl_pct']*100:+.2f}% "
              f"({r['pnl']:+.2f}) reason={r['exit_reason']}")

    print()
    print("=== 归因汇总 ===")
    attr = j.attribution()
    for k, v in attr.items():
        if isinstance(v, float):
            if "rate" in k or "pct" in k:
                print(f"  {k:20s} = {v*100:+.2f}%")
            else:
                print(f"  {k:20s} = {v:.3f}")
        else:
            print(f"  {k:20s} = {v}")


if __name__ == "__main__":
    main()
