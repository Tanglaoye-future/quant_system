#!/usr/bin/env python
"""盘中实时风控 cron / loop —— PR5 of docs/specs/position_v2_harness.md §6。

用法：
  # 单次跑（适合 cron）
  venv/bin/python scripts/intraday/intraday_risk_check.py

  # 持续 loop（nohup 守护）
  nohup venv/bin/python scripts/intraday/intraday_risk_check.py --loop &

  # dry-run（不推、不写 DB）
  venv/bin/python scripts/intraday/intraday_risk_check.py --dry-run

凭证：
  TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...

阈值 / 策略 / 频率：见 config/intraday.yaml。
默认 enabled: false → 整个脚本 noop（不抛错，便于盘后跑调试）。
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from quant_system.db import AlertsSent  # noqa: E402
from quant_system.db.ingest import (  # noqa: E402
    _dualwrite_enabled,
    list_recent_portfolio_history_mvs,
)
from quant_system.db.session import session_scope  # noqa: E402
from quant_system.intraday import (  # noqa: E402
    AlertEvent,
    IntradayConfig,
    PortfolioSnapshot,
    PositionSnapshot,
    evaluate_alerts,
    is_in_trading_window,
)
from quant_system.notify import TelegramSender  # noqa: E402
from quant_system.strategies.equity_factor.journal import Journal  # noqa: E402
from quant_system.strategies.equity_factor.risk.monitor import compute_peak_drawdown  # noqa: E402

logger = logging.getLogger("intraday")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "intraday.yaml"
_JOURNAL_PATH = Path(__file__).resolve().parents[2] / "data" / "journal.db"


# ── data fetchers ────────────────────────────────────────────────────

def fetch_realtime_prices_a_share(codes: list[str]) -> dict[str, float]:
    """A 股实时价 via akshare.stock_zh_a_spot_em。失败 / 缺 code 静默跳过。

    回测 / 单测 可以 monkeypatch 本函数避免真网络。
    """
    if not codes:
        return {}
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        # akshare 列名是中文：'代码' / '最新价'
        mask = df["代码"].astype(str).isin(codes)
        sub = df[mask][["代码", "最新价"]]
        return {str(row["代码"]): float(row["最新价"]) for _, row in sub.iterrows()}
    except Exception as exc:
        logger.warning("fetch_realtime_prices_a_share failed: %s", exc)
        return {}


def _load_yaml() -> dict:
    if not _CONFIG_PATH.exists():
        return {}
    return yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}


# ── 主流程 ────────────────────────────────────────────────────────────

def _build_position_snapshots(
    journal: Journal,
    price_map: dict[str, float],
) -> list[PositionSnapshot]:
    """journal_trades open + 实时价 → PositionSnapshot list。"""
    snapshots: list[PositionSnapshot] = []
    for t in journal.list_open():
        code = t["symbol"]
        current = price_map.get(code)
        if current is None:
            continue
        strategy = t.get("strategy") or "equity_factor"
        snapshots.append(PositionSnapshot(
            strategy_name=strategy,
            symbol=code,
            market=t["market"],
            entry_price=float(t["entry_price"]),
            current_price=current,
            stop_loss=float(t["stop_loss_price"]) if t.get("stop_loss_price") else None,
            take_profit=float(t["take_profit_price"]) if t.get("take_profit_price") else None,
        ))
    return snapshots


def _build_portfolio_snapshots(
    positions: list[PositionSnapshot],
    asof: str,
) -> list[PortfolioSnapshot]:
    """按 strategy_name 分组 → 算 unrealized_pnl_pct + peak DD（查 portfolio_history）。

    intraday 不知道 size（journal_trades 有但 PositionSnapshot 没存）→
    简化用 entry_price 加权（与组合层 cost_basis 相同假设：单股 size 比例相等）；
    严格起见 size 应入 PositionSnapshot，留 TODO。
    """
    by_strat: dict[str, list[PositionSnapshot]] = {}
    for p in positions:
        by_strat.setdefault(p.strategy_name, []).append(p)
    snaps: list[PortfolioSnapshot] = []
    for strategy, plist in by_strat.items():
        if not plist:
            continue
        cost = sum(p.entry_price for p in plist)
        mv = sum(p.current_price for p in plist)
        pnl_pct = (mv / cost - 1.0) if cost > 0 else 0.0
        # market 从第一个 position 取（同 strategy 通常同 market；混合时退化为第一个）
        market = plist[0].market
        history_mvs = list_recent_portfolio_history_mvs(
            strategy_name=strategy, market=market, asof=asof, lookback_days=60,
        )
        peak, dd = compute_peak_drawdown(history_mvs, mv)
        snaps.append(PortfolioSnapshot(
            strategy_name=strategy,
            unrealized_pnl_pct=pnl_pct,
            drawdown_from_peak_pct=dd,
        ))
    return snaps


def _already_sent_today(
    asof_date: date,
    strategy_name: str,
    symbol: Optional[str],
    alert_type: str,
) -> bool:
    """alerts_sent UNIQUE (asof_date, strategy_name, symbol, alert_type) 去重检查。

    DB 不可达 → 当作"已发"避免重复（容错偏保守；恢复后下个周期自然重发）。
    """
    if not _dualwrite_enabled():
        return False  # 无 DB 路径，不去重（开发模式）
    try:
        from sqlalchemy import select
        with session_scope() as session:
            row = session.scalars(
                select(AlertsSent).where(
                    AlertsSent.asof_date == asof_date,
                    AlertsSent.strategy_name == strategy_name,
                    AlertsSent.symbol == symbol,
                    AlertsSent.alert_type == alert_type,
                )
            ).first()
            return row is not None
    except Exception as exc:
        logger.warning("_already_sent_today (%s/%s/%s) DB err: %s; treat as 'sent'",
                       strategy_name, symbol, alert_type, exc)
        return True


def _persist_alert(
    asof_ts: datetime,
    asof_date: date,
    event: AlertEvent,
    channel: str,
    delivered: bool,
    error: Optional[str],
) -> bool:
    """写一行 alerts_sent；env 关 / DB 不可达 → noop（True 返回，告警仍 stdout）。"""
    if not _dualwrite_enabled():
        return True
    try:
        with session_scope() as session:
            row = AlertsSent(
                asof_ts=asof_ts,
                asof_date=asof_date,
                strategy_name=event.strategy_name,
                symbol=event.symbol,
                alert_type=event.alert_type,
                payload=event.payload,
                channel=channel,
                delivered=delivered,
                error=error,
            )
            session.add(row)
        return True
    except Exception as exc:
        logger.warning("_persist_alert failed (%s/%s): %s",
                       event.strategy_name, event.alert_type, exc)
        return False


def run_once(dry_run: bool = False) -> int:
    """执行一次评估 + 推送。返触发条数。"""
    raw = _load_yaml()
    raw_alerts = raw.get("intraday_alerts") or {}
    cfg = IntradayConfig.from_yaml_dict(raw_alerts)
    if not cfg.enabled:
        logger.info("intraday_alerts.enabled=false; noop")
        return 0

    now = datetime.now()
    if not is_in_trading_window(now, cfg) and not dry_run:
        logger.info("not in trading window (%s); skip", now.strftime("%H:%M:%S"))
        return 0

    # 1. open positions
    journal = Journal(str(_JOURNAL_PATH))
    open_trades = journal.list_open()
    if not open_trades:
        logger.info("no open trades; noop")
        return 0
    codes = [t["symbol"] for t in open_trades if t.get("market") == "a_share"]

    # 2. realtime prices (currently A-share only; HK / US 后续扩)
    price_map = fetch_realtime_prices_a_share(codes)
    if not price_map:
        logger.warning("no realtime prices fetched (network / 非交易日); skip")
        return 0

    # 3. snapshots → evaluate
    positions = _build_position_snapshots(journal, price_map)
    portfolios = _build_portfolio_snapshots(positions, asof=now.strftime("%Y-%m-%d"))
    events = evaluate_alerts(positions, portfolios, cfg)
    logger.info("evaluated %d alerts (positions=%d portfolios=%d)",
                len(events), len(positions), len(portfolios))
    if not events:
        return 0

    # 4. 推送（已去重的才发）
    asof_date = now.date()
    sender = TelegramSender()
    channel = "telegram"
    sent_count = 0
    for ev in events:
        if _already_sent_today(asof_date, ev.strategy_name, ev.symbol, ev.alert_type):
            logger.debug("dedup: skip %s/%s/%s", ev.strategy_name, ev.symbol, ev.alert_type)
            continue
        if dry_run:
            logger.info("[dry-run] would send: %s", ev.message.replace("\n", " | "))
            sent_count += 1
            continue
        ok, err = sender.send(ev.message)
        if ok:
            sent_count += 1
            logger.info("sent %s/%s/%s via %s", ev.strategy_name, ev.symbol, ev.alert_type, channel)
        else:
            logger.warning("send failed %s/%s/%s: %s", ev.strategy_name, ev.symbol, ev.alert_type, err)
        _persist_alert(now, asof_date, ev, channel, delivered=ok, error=err)
    return sent_count


def run_loop(dry_run: bool = False) -> None:
    raw = _load_yaml()
    raw_alerts = raw.get("intraday_alerts") or {}
    cfg = IntradayConfig.from_yaml_dict(raw_alerts)
    interval_sec = max(60, cfg.poll_interval_minutes * 60)
    logger.info("entering loop (interval=%ds, enabled=%s)", interval_sec, cfg.enabled)
    while True:
        try:
            run_once(dry_run=dry_run)
        except Exception as exc:
            logger.exception("run_once unexpected error: %s", exc)
        time.sleep(interval_sec)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="持续 loop（推荐 nohup 守护）")
    parser.add_argument("--dry-run", action="store_true", help="评估 + 打印；不推送，不写 DB")
    args = parser.parse_args()
    if args.loop:
        run_loop(dry_run=args.dry_run)
        return 0
    return 0 if run_once(dry_run=args.dry_run) >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
