"""
持仓监控模块.

每日运行：检查现有期权仓位，输出需要操作的提醒。

出场规则（与 config 对齐）：
  - 权利金盈利 ≥ 100% → 止盈
  - 权利金亏损 ≥ 50%  → 止损
  - 剩余 DTE ≤ 21     → 评估滚仓
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from quant_system.strategies.options.broker.ibkr import IBKRClient


# ── PR3 阈值（spec §4 + monitor.py 默认 50%/7DTE 对齐）────────────────────
_DTE_BREACH = 7
_LOSS_BREACH_PCT = -0.50


def _parse_expiry(expiry: str) -> Optional[date]:
    """IBKR lastTradeDateOrContractMonth 格式 'YYYYMMDD' or 'YYYYMM' → date。"""
    try:
        return datetime.strptime(expiry[:8], "%Y%m%d").date()
    except Exception:
        return None


def compute_breach_alerts(days_to_exp: int, pnl_pct: Optional[float]) -> list[str]:
    """spec §4.7：DTE<7 / loss>50% 两条触发；可扩展。"""
    alerts: list[str] = []
    if days_to_exp < _DTE_BREACH:
        alerts.append("DTE<7")
    if pnl_pct is not None and pnl_pct <= _LOSS_BREACH_PCT:
        alerts.append("loss>50%")
    return alerts


def aggregate_bull_call_spreads(
    positions: list[dict[str, Any]],
    asof: Optional[date] = None,
    spread_quote_lookup: Optional[Any] = None,
) -> list[dict[str, Any]]:
    """把 IBKR 单 leg 持仓聚合成 BCS spread JSON 行。

    规则（spec §4 + monitor.py 现状）：
    - 仅 Call leg；同 expiry 配对 — 多头(position>0)=long_leg(低 strike)，空头(position<0)=short_leg(高 strike)
    - 1 expiry 可有 1 个 spread（多 expiry 各自一组）；若 leg 数不匹配则跳过该 expiry
    - debit_paid = (long_avg_cost - short_avg_cost) / 100  per share（IBKR avgCost 是每 contract）
    - max_profit = (short_strike - long_strike - debit_paid) × 100
    - max_loss   = debit_paid × 100
    - contracts  = min(|long.position|, |short.position|)
    - current_value: 若提供 `spread_quote_lookup(long_strike, short_strike, expiry_str)` callable
      返回 spread mid (long_mid - short_mid)；否则 None
    - pnl_pct = (current_value - debit_paid) / debit_paid（None when current_value/debit 缺失）
    - breach_alerts via `compute_breach_alerts`
    - asof 缺省今天

    返回与 spec §4.4 example 对齐的 dict list（DB upsert + JSON 双用）。
    """
    asof = asof or date.today()
    # 按 expiry 分组
    by_expiry: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for p in positions:
        if str(p.get("right", "")).upper() != "C":
            continue
        exp = str(p.get("expiry", ""))[:8]
        if not exp:
            continue
        bucket = by_expiry.setdefault(exp, {"long": [], "short": []})
        if p.get("position", 0) > 0:
            bucket["long"].append(p)
        elif p.get("position", 0) < 0:
            bucket["short"].append(p)

    spreads: list[dict[str, Any]] = []
    for exp_str, legs in by_expiry.items():
        if not legs["long"] or not legs["short"]:
            continue
        # 取最低 strike 多头 + 最高 strike 空头作为 BCS pair
        long_leg = min(legs["long"], key=lambda x: float(x["strike"]))
        short_leg = max(legs["short"], key=lambda x: float(x["strike"]))
        long_strike = float(long_leg["strike"])
        short_strike = float(short_leg["strike"])
        if short_strike <= long_strike:
            continue  # 非 BCS 结构

        contracts = int(min(abs(long_leg.get("position", 0)), abs(short_leg.get("position", 0))))
        if contracts <= 0:
            continue
        # IBKR avgCost 是 per contract（每股 × 100），转每股 debit
        long_cost_share = float(long_leg.get("avg_cost", 0.0)) / 100.0
        short_cost_share = float(short_leg.get("avg_cost", 0.0)) / 100.0
        debit_paid = long_cost_share - short_cost_share

        expiry_date = _parse_expiry(exp_str)
        if expiry_date is None:
            continue
        days_to_exp = (expiry_date - asof).days

        max_profit = (short_strike - long_strike - debit_paid) * 100
        max_loss = debit_paid * 100

        current_value: Optional[float] = None
        if spread_quote_lookup is not None:
            try:
                current_value = spread_quote_lookup(long_strike, short_strike, exp_str)
            except Exception:
                current_value = None

        if current_value is not None and debit_paid > 0:
            pnl_pct: Optional[float] = round((current_value - debit_paid) / debit_paid, 4)
        else:
            pnl_pct = None

        alerts = compute_breach_alerts(days_to_exp, pnl_pct)

        spreads.append({
            "long_strike": long_strike,
            "short_strike": short_strike,
            "expiry": expiry_date.isoformat(),
            "contracts": contracts,
            "debit_paid": round(debit_paid, 4),
            "max_profit": round(max_profit, 2),
            "max_loss": round(max_loss, 2),
            "current_value": round(current_value, 4) if current_value is not None else None,
            "days_to_exp": days_to_exp,
            "pnl_pct": pnl_pct,
            "breach_alerts": alerts,
        })
    return spreads


@dataclass
class PositionAlert:
    code: str           # HOLD / TAKE_PROFIT / STOP_LOSS / ROLL_SOON
    symbol: str
    expiry: str
    strike: float
    right: str
    position: int       # 持仓张数（正=多，负=空）
    avg_cost: float     # 平均成本（每股）
    current_mid: float  # 当前中间价
    pnl_pct: float      # 盈亏百分比
    dte: int
    message: str


def check_positions(
    client: "IBKRClient",
    symbol: str = "QQQ",
    profit_target_mult: float = 2.0,
    stop_loss_mult: float = 0.50,
    dte_warning: int = 21,
) -> list[PositionAlert]:
    """
    拉取当前期权持仓，返回需要操作的提醒列表.
    """
    positions = client.get_option_positions(symbol)
    if not positions:
        return []

    alerts: list[PositionAlert] = []
    today = datetime.now().date()

    for pos in positions:
        expiry = pos["expiry"]
        strike = pos["strike"]
        right = pos["right"]
        avg_cost = pos["avg_cost"] / 100  # IBKR 返回的是每合约成本，除以100得每股
        position_size = pos["position"]

        # 计算 DTE
        try:
            exp_dt = datetime.strptime(expiry[:8], "%Y%m%d").date()
            dte = (exp_dt - today).days
        except Exception:
            dte = 0

        # 获取当前报价
        quote = client.get_option_quote(symbol, expiry[:8], strike, right)
        if quote is None:
            continue

        current_mid = quote.mid
        if avg_cost <= 0 or current_mid <= 0:
            continue

        # 对于多头头寸（买入期权）
        if position_size > 0:
            pnl_pct = (current_mid - avg_cost) / avg_cost

            if pnl_pct >= profit_target_mult - 1.0:
                code = "TAKE_PROFIT"
                msg = f"盈利 {pnl_pct*100:+.1f}% ≥ 目标 {(profit_target_mult-1)*100:.0f}% → 建议平仓止盈"
            elif pnl_pct <= -(1.0 - stop_loss_mult):
                code = "STOP_LOSS"
                msg = f"亏损 {pnl_pct*100:+.1f}% ≥ 止损线 {(1-stop_loss_mult)*100:.0f}% → 立即平仓"
            elif dte <= dte_warning:
                code = "ROLL_SOON"
                msg = f"剩余 {dte} DTE ≤ {dte_warning} → 评估滚仓至下一个月"
            else:
                code = "HOLD"
                msg = f"持仓正常  PnL {pnl_pct*100:+.1f}%  DTE {dte}"

            alerts.append(PositionAlert(
                code=code, symbol=symbol, expiry=expiry[:8],
                strike=strike, right=right, position=position_size,
                avg_cost=avg_cost, current_mid=current_mid,
                pnl_pct=round(pnl_pct, 4), dte=dte, message=msg,
            ))

    return alerts
