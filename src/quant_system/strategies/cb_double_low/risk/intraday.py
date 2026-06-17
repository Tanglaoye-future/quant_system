"""CB sleeve 实时风控 — PR10 (2026-06-17).

复用 quant_system.intraday.core.AlertEvent + alerts_sent 表 + Telegram channel.
不复用 PositionSnapshot — equity 语义 (entry_price/stop_loss/take_profit/ma_long) 与 CB 不同,
独立 CBPositionSnapshot 避免字段语义错位.

PR10 范围 (2 个 alert types):
  - cb_break_stop_loss: close < stop_loss_close (默认 85) → critical
      * 实时性高 (债底击穿信号), spot_em 一次拉全市场 cost O(1)
  - cb_redeem_imminent: last_trading_date ≤ N 天 (默认 30) → critical
      * redemption 表 daily refresh 即可, intraday 不重复拉

不在 PR10 范围:
  - cb_dual_low_exit (score > 180) — 慢信号, 已被 PR9 daily rebalance signal 每日覆盖,
    实时拉 conversion_premium_rate 需要 panel value_analysis 每 code 1 次 API (~10 min 跑完),
    cost/value 不划算; 留 daily.
  - portfolio 层 (unrealized_floor / peak_drawdown) — 留 PR11+ 接 CBDataLoader.get_spot_today
    汇总 mv. PR10 先做个券层风控.

CB 不做 T+0: 北极星 2026-06-15 risk-parity 豁免 — 不引入日内执行循环,
告警仅 "考虑减仓" advisory (与 zhuang_distribution_warning 模式对齐, Backstop #4).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd

from quant_system.intraday.core import AlertEvent
from quant_system.strategies.cb_double_low.journal import CB_MARKET, CB_STRATEGY


@dataclass
class CBPositionSnapshot:
    """CB 持仓盘中评估的最小形态.

    与 equity PositionSnapshot 不重合 (后者 entry_price/stop_loss/ma_long 都不对应 CB 语义).
    bond_code 是 journal_trades.symbol; bond_name 用于 Telegram 文案.
    """
    bond_code: str
    bond_name: str
    current_close: float
    redeem_last_trading_date: Optional[date] = None  # 强赎最后交易日 (None=非强赎)


@dataclass
class CBIntradayConfig:
    """CB 实时风控配置.

    stop_loss_close / exit_dual_low_threshold 不在此处定义 — 从 config/cb_double_low.yaml
    单源读取, 避免 PM 改一处忘另一处. 本类只持 enable + redeem 窗口 + 触发回退值.
    """
    enabled: bool = False
    poll_interval_minutes: int = 15  # CB 低波 + 月度 rebalance, 不需要 equity 的 5 min 节奏
    stop_loss_close: float = 85.0    # fallback if config/cb_double_low.yaml 缺
    redeem_within_days: int = 30
    strategies: list[str] = field(default_factory=lambda: [CB_STRATEGY])

    @classmethod
    def from_yaml_dict(
        cls,
        raw: dict,
        cb_strategy_yaml: Optional[dict] = None,
    ) -> "CBIntradayConfig":
        """从 config/intraday.yaml 的 cb_double_low section 构造.

        Args:
            raw: intraday yaml 的 cb_double_low section
            cb_strategy_yaml: config/cb_double_low.yaml 全文 (复用 strategy.stop_loss_close)
        """
        stop_loss = 85.0
        if cb_strategy_yaml:
            stop_loss = float(
                (cb_strategy_yaml.get("strategy") or {}).get("stop_loss_close", 85.0)
            )
        return cls(
            enabled=bool(raw.get("enabled", False)),
            poll_interval_minutes=int(raw.get("poll_interval_minutes", 15)),
            stop_loss_close=stop_loss,
            redeem_within_days=int(raw.get("redeem_within_days", 30)),
            strategies=list(raw.get("strategies") or [CB_STRATEGY]),
        )


def evaluate_cb_alerts(
    positions: list[CBPositionSnapshot],
    asof: date,
    cfg: CBIntradayConfig,
) -> list[AlertEvent]:
    """纯评估 → AlertEvent list. 不做去重 / DB / 推送 (主脚本职责).

    asof 用于强赎临近窗口判定 (last_trading_date <= asof + redeem_within_days).
    """
    events: list[AlertEvent] = []
    if not cfg.enabled:
        return events

    redeem_window_end = asof + timedelta(days=cfg.redeem_within_days)

    for p in positions:
        # 1. cb_break_stop_loss — close 击穿 85 (债底信号失守, critical)
        if p.current_close > 0 and p.current_close < cfg.stop_loss_close:
            breach_pct = (cfg.stop_loss_close - p.current_close) / cfg.stop_loss_close
            events.append(AlertEvent(
                strategy_name=CB_STRATEGY,
                symbol=p.bond_code,
                alert_type="cb_break_stop_loss",
                severity="critical",
                payload={
                    "bond_code": p.bond_code,
                    "bond_name": p.bond_name,
                    "current_close": p.current_close,
                    "stop_loss_close": cfg.stop_loss_close,
                    "breach_pct": breach_pct,
                },
                message=(
                    f"🛑 [CB 止损] <b>{p.bond_code} {p.bond_name}</b>\n"
                    f"现价 {p.current_close:.2f} &lt; 止损线 {cfg.stop_loss_close:.2f} "
                    f"({breach_pct*100:+.2f}%)\n"
                    f"⚠ 债底信号失守, 考虑减仓 (非自动平仓)"
                ),
            ))

        # 2. cb_redeem_imminent — 强赎临近 (last_trading_date 在 N 天内)
        if (
            p.redeem_last_trading_date is not None
            and asof <= p.redeem_last_trading_date <= redeem_window_end
        ):
            days_to_redeem = (p.redeem_last_trading_date - asof).days
            events.append(AlertEvent(
                strategy_name=CB_STRATEGY,
                symbol=p.bond_code,
                alert_type="cb_redeem_imminent",
                severity="critical",
                payload={
                    "bond_code": p.bond_code,
                    "bond_name": p.bond_name,
                    "current_close": p.current_close,
                    "last_trading_date": str(p.redeem_last_trading_date),
                    "days_to_redeem": days_to_redeem,
                },
                message=(
                    f"⏰ [CB 强赎临近] <b>{p.bond_code} {p.bond_name}</b>\n"
                    f"最后交易日 {p.redeem_last_trading_date} (剩 {days_to_redeem} 天)\n"
                    f"现价 {p.current_close:.2f} — 立即转股或卖出, 避免强赎价 (~100) 损失"
                ),
            ))

    return events


def fetch_cb_realtime_close(codes: list[str]) -> dict[str, dict]:
    """一次拉全市场 CB spot, 过滤持仓 codes.

    akshare bond_zh_hs_cov_spot() ≈ 0.5-1s 拉 1000+ 只全表.
    返回 dict[bond_code, {close, bond_name}].
    """
    if not codes:
        return {}
    import akshare as ak  # 延迟 import 避免单测/导入耗时
    try:
        raw = ak.bond_zh_hs_cov_spot()
    except Exception:
        return {}
    rename = {"code": "bond_code", "name": "bond_name", "trade": "close"}
    df = raw.rename(columns=rename).copy()
    df["bond_code"] = df["bond_code"].astype(str)
    code_set = set(str(c) for c in codes)
    df = df[df["bond_code"].isin(code_set)]
    out: dict[str, dict] = {}
    for _, row in df.iterrows():
        try:
            close = float(row["close"])
        except (ValueError, TypeError):
            continue
        if close <= 0:
            continue
        out[str(row["bond_code"])] = {
            "close": close,
            "bond_name": str(row.get("bond_name", "")),
        }
    return out


def build_cb_position_snapshots(
    holdings_journal_rows: list[dict],
    spot_map: dict[str, dict],
    redemption_df: Optional[pd.DataFrame],
) -> list[CBPositionSnapshot]:
    """journal.list_open(cb_a) 行 + spot + redemption → snapshot list.

    spot 缺 (今天非交易日 / akshare 挂) → 该 code 跳过 (评估不到, 不发误告警).
    redemption_df 缺 → redeem_last_trading_date=None, 仅评估 stop_loss.
    """
    redeem_map: dict[str, date] = {}
    if redemption_df is not None and not redemption_df.empty:
        for _, row in redemption_df.iterrows():
            ltd = row.get("last_trading_date")
            if pd.notna(ltd):
                code = str(row["bond_code"])
                redeem_map[code] = pd.Timestamp(ltd).date()

    out: list[CBPositionSnapshot] = []
    for t in holdings_journal_rows:
        if t.get("market") != CB_MARKET:
            continue
        code = str(t["symbol"])
        spot = spot_map.get(code)
        if spot is None:
            continue  # spot 缺, 跳过这只
        # bond_name 优先 notes (build_cb_trade_open 默认填 notes=bond_name), 否则 spot 兜底
        bond_name = (t.get("notes") or "").strip() or spot["bond_name"]
        out.append(CBPositionSnapshot(
            bond_code=code,
            bond_name=bond_name,
            current_close=spot["close"],
            redeem_last_trading_date=redeem_map.get(code),
        ))
    return out
