"""
端到端验证 risk/monitor.py:
  1. 多开 1 笔健康持仓 (000001 平安银行) 让组合不止 1 只
  2. 跑 RiskMonitor.daily_check 一次, 写 snapshot + 更新 trailing stop
  3. 输出每只持仓的 HOLD/EXIT + 组合层面摘要
"""
from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_system.config import load_config
from quant_system.data.loader import DataLoader
from quant_system.journal.journal import Journal, TradeOpen
from quant_system.risk.monitor import RiskMonitor


def ensure_demo_position(j: Journal) -> None:
    """如果 000001 还没在持仓里, 补一笔, 让风控 demo 不止看到一只 EXIT."""
    open_codes = {t["symbol"] for t in j.list_open()}
    if "000001" in open_codes:
        return
    j.open_trade(TradeOpen(
        symbol="000001", market="a_share",
        entry_date="2026-04-01", entry_price=12.50, entry_size=1000,
        entry_score=0.813,
        reason_topdown="经济复苏期, 金融板块景气",
        reason_bottomup="PE 5.1, ROE 11%, 估值低 + 动量正",
        reason_catalyst="一季报披露在即",
        reason_timing="MA20 上穿 MA60, RSI 58, 量比 1.6",
        stop_loss_price=11.80, take_profit_price=14.50,
        notes="demo_risk 自动补的健康持仓",
    ))


def main() -> None:
    cfg = load_config()
    loader = DataLoader(cfg.cache_dir, refresh_days=cfg.get("data", "refresh_days", default=1))
    j = Journal(cfg.journal_db_path)
    j.init_schema()

    ensure_demo_position(j)

    monitor = RiskMonitor(loader=loader, journal=j)
    positions, port = monitor.daily_check(write_snapshots=True)

    print("=" * 78)
    print("逐笔风控")
    print("=" * 78)
    for p in positions:
        print()
        print(f"  #{p.trade_id} {p.symbol}  入场 {p.entry_date} @ {p.entry_price:.2f} x {p.entry_size}")
        print(f"    最新: {p.current_price:.2f}  ({p.current_date}, 持有 {p.hold_days} 天)")
        print(f"    浮动盈亏: {p.pnl_pct*100:+.2f}%  ({p.pnl_amount:+.2f} 元)")
        prev = f"{p.prev_stop:.2f}" if p.prev_stop is not None else "(无)"
        delta = "↑" if (p.prev_stop is not None and p.new_stop > p.prev_stop) else "—"
        print(f"    Trailing stop: {prev}  ->  {p.new_stop:.2f}  {delta}")
        print(f"    >> {p.action}: {p.reason}")

    print()
    print("=" * 78)
    print("组合摘要")
    print("=" * 78)
    print(f"  持仓数:        {port.n_positions}")
    print(f"  总成本:        {port.cost_basis:>12.2f}")
    print(f"  总市值:        {port.market_value:>12.2f}")
    print(f"  总浮盈:        {port.unrealized_pnl:>+12.2f}  ({port.unrealized_pnl_pct*100:+.2f}%)")
    print(f"  单只最大占比:  {port.max_single_weight*100:.1f}%")
    print(f"  最差单只浮亏:  {port.worst_drawdown_pct*100:+.2f}%")
    print(f"  EXIT 信号笔数: {port.n_at_risk}/{port.n_positions}")


if __name__ == "__main__":
    main()
