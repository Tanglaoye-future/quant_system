"""
信号卡展示模块.

输出格式：终端彩色文本（可选），或纯文本（用于日志）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quant_system.strategies.options.broker.ibkr import SpreadQuote
    from quant_system.strategies.options.engine.monitor import PositionAlert
    from quant_system.strategies.options.iv.engine import IVSnapshot
    from quant_system.strategies.options.signals.momentum import MomentumSignal

_LINE = "═" * 58


def print_signal_card(
    iv: "IVSnapshot",
    momentum: "MomentumSignal",
    spread: "SpreadQuote",
    sizing: dict,
    account_net_liq: float,
) -> None:
    """打印完整交易信号卡."""

    grade_emoji = {"A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴"}.get(iv.signal_grade, "⚪")

    print(f"\n{_LINE}")
    print(f"  QQQ 期权交易信号  {momentum.date}")
    print(_LINE)

    # ── IV 环境 ───────────────────────────────────────────────────────────────
    print(f"\n【IV 环境】{grade_emoji} 评级 {iv.signal_grade}")
    print(f"  VXN 当前:  {iv.vxn_current:.2f}")
    print(f"  IVR:       {iv.ivr:.1f}  (52周: {iv.vxn_52w_low:.1f} – {iv.vxn_52w_high:.1f})")
    print(f"  模式:      {iv.mode.value}")

    # ── 动量信号 ──────────────────────────────────────────────────────────────
    bullish_str = "✅ 看涨" if momentum.bullish else "❌ 信号不足"
    print(f"\n【动量信号】{bullish_str}")
    print(f"  QQQ 价格:  ${momentum.price:.2f}")
    print(f"  MA200:     ${momentum.ma200:.2f}  {'↑上方' if momentum.above_ma200 else '↓下方'}")
    print(f"  RSI(14):   {momentum.rsi:.1f}  {'✅' if momentum.rsi_in_range else '❌'}")
    print(f"  3月动量:   {momentum.momentum_3m*100:+.1f}%  {'✅' if momentum.momentum_positive else '❌'}")
    if momentum.note and not momentum.bullish:
        print(f"  提示:      {momentum.note}")

    if not momentum.bullish:
        print(f"\n⚠️  动量条件不满足，建议等待。")
        print(_LINE)
        return

    # ── 期权结构 ──────────────────────────────────────────────────────────────
    ll = spread.long_leg
    sl = spread.short_leg
    print(f"\n【期权结构】Bull Call Spread")
    print(f"  到期日:    {spread.expiry_str}  ({ll.dte} DTE)")
    print()
    print(f"  ┌─ 买入腿 (Long Call)")
    print(f"  │  行权价: ${ll.strike:.1f}  Delta: {ll.delta:+.3f}")
    print(f"  │  报价:   ${ll.bid:.2f} / ${ll.ask:.2f}  (Mid ${ll.mid:.2f})")
    print(f"  │  IV:     {ll.iv*100:.1f}%  Theta: {ll.theta:.3f}/日")
    print(f"  │")
    print(f"  └─ 卖出腿 (Short Call)")
    print(f"     行权价: ${sl.strike:.1f}  Delta: {sl.delta:+.3f}")
    print(f"     报价:   ${sl.bid:.2f} / ${sl.ask:.2f}  (Mid ${sl.mid:.2f})")
    print(f"     IV:     {sl.iv*100:.1f}%  Theta: {sl.theta:.3f}/日")

    # ── 盈亏结构 ──────────────────────────────────────────────────────────────
    print(f"\n【盈亏结构】（每张合约 = 100 股）")
    print(f"  净权利金:    ${spread.net_debit:.2f}/股  = ${spread.net_debit*100:.0f}/张")
    print(f"  最大亏损:    ${spread.max_loss:.2f}/股   = ${spread.max_loss*100:.0f}/张")
    print(f"  最大盈利:    ${spread.max_profit:.2f}/股  = ${spread.max_profit*100:.0f}/张  ({spread.profit_ratio:.1f}×)")
    print(f"  盈亏平衡:    ${spread.breakeven:.2f}  (需涨 {(spread.breakeven/momentum.price-1)*100:.1f}%)")

    # ── 仓位建议 ──────────────────────────────────────────────────────────────
    print(f"\n【仓位建议】")
    print(f"  账户净值:    ${account_net_liq:,.0f}")
    print(f"  风险预算:    ${sizing['risk_budget']:,.0f}  ({sizing['risk_pct_actual']:.1f}%)")
    print(f"  建议张数:    {sizing['contracts']} 张")
    print(f"  实际成本:    ${sizing['total_risk']:,.0f}")

    # ── 出场规则 ──────────────────────────────────────────────────────────────
    tp_price = spread.net_debit * 2
    sl_price = spread.net_debit * 0.5
    print(f"\n【出场规则】")
    print(f"  止盈:  Mid ≥ ${tp_price:.2f}/股  (权利金翻倍 +100%)")
    print(f"  止损:  Mid ≤ ${sl_price:.2f}/股  (亏损 50%)")
    print(f"  时间:  剩余 21 DTE → 评估滚仓")

    # ── 下单参考 ──────────────────────────────────────────────────────────────
    print(f"\n【IBKR 下单参考】")
    print(f"  腿1 BUY  {sizing['contracts']} QQQ {spread.expiry_str} ${ll.strike:.1f}C  LMT {ll.ask:.2f}")
    print(f"  腿2 SELL {sizing['contracts']} QQQ {spread.expiry_str} ${sl.strike:.1f}C  LMT {sl.bid:.2f}")
    print(f"  净费用:  ~${spread.net_debit*sizing['contracts']*100:.0f}")

    print(f"\n{_LINE}\n")


def print_monitor_alerts(alerts: list["PositionAlert"]) -> None:
    """打印持仓监控提醒."""
    if not alerts:
        print("\n[监控] 无持仓需要处理。")
        return

    print(f"\n{_LINE}")
    print(f"  持仓监控提醒  {len(alerts)} 条")
    print(_LINE)

    priority = {"STOP_LOSS": 0, "TAKE_PROFIT": 1, "ROLL_SOON": 2, "HOLD": 3}
    alerts = sorted(alerts, key=lambda a: priority.get(a.code, 9))

    icons = {"STOP_LOSS": "🔴", "TAKE_PROFIT": "🟢", "ROLL_SOON": "🟡", "HOLD": "⚪"}

    for a in alerts:
        icon = icons.get(a.code, "⚪")
        print(f"\n{icon} [{a.code}]  {a.symbol} ${a.strike} {a.right}  到期: {a.expiry}  DTE: {a.dte}")
        print(f"   持仓: {a.position} 张  成本: ${a.avg_cost:.2f}  现价: ${a.current_mid:.2f}  PnL: {a.pnl_pct*100:+.1f}%")
        print(f"   {a.message}")

    print(f"\n{_LINE}\n")


def print_no_signal(iv: "IVSnapshot", momentum: "MomentumSignal") -> None:
    """当条件不满足时打印简短摘要."""
    print(f"\n{_LINE}")
    print(f"  QQQ 期权扫描  {momentum.date}  → 无信号")
    print(_LINE)
    print(f"  IVR: {iv.ivr:.1f} ({iv.mode.value})  |  QQQ: ${momentum.price:.2f}")
    reason = []
    if not momentum.above_ma200:
        reason.append(f"价格低于 MA200(${momentum.ma200:.2f})")
    if not momentum.rsi_in_range:
        reason.append(f"RSI({momentum.rsi:.1f}) 超出范围")
    if not momentum.momentum_positive:
        reason.append(f"3月动量({momentum.momentum_3m*100:.1f}%) 为负")
    if iv.signal_grade == "D":
        reason.append(f"IVR({iv.ivr:.1f}) 过高，期权偏贵")
    print(f"  原因: {' | '.join(reason) if reason else '综合评估不足'}")
    print(_LINE)
