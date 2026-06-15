#!/usr/bin/env python
"""持仓中日内做 T 信号 cron / loop (spec docs/specs/intraday_t_execution_a_share.md).

用法:
  # 单次 (适合 cron / 调试)
  venv/bin/python scripts/intraday/intraday_t_signals.py

  # nohup 守护 (5min 轮询)
  nohup venv/bin/python scripts/intraday/intraday_t_signals.py --loop &

  # dry-run (不写 DB / 不推送, 仅 stdout)
  venv/bin/python scripts/intraday/intraday_t_signals.py --dry-run

凭证:
  TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...

阈值 / 白名单 / 频率 上限 → config/intraday.yaml::t_signals
默认 enabled: false → 整个脚本 noop (零行为差异, Backstop #5 严守)

6 条不变量 (spec §14) 由 evaluate_t_signals 纯函数保证, 本脚本仅做 IO 包装:
  - DB query alerts_sent → sent_today dict
  - 拉 spot_em (price + vol_ratio + change_pct) + 1min K 累计 VWAP
  - 写 alerts_sent + Telegram send (失败 stdout fallback)
"""
from __future__ import annotations

import argparse
import logging
import sys
import time as _time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

# 与 intraday_risk_check 同款: ALL akshare import 之前激活 curl_cffi TLS 绕过 (Clash 兼容)
import quant_system.intraday.akshare_cffi_patch  # noqa: F401

from quant_system.db import AlertsSent  # noqa: E402
from quant_system.db.ingest import _dualwrite_enabled  # noqa: E402
from quant_system.db.session import session_scope  # noqa: E402
from quant_system.intraday import (  # noqa: E402
    PositionSnapshot,
    TSignalConfig,
    TSignalEvent,
    evaluate_t_signals,
)
from quant_system.notify import TelegramSender  # noqa: E402
from quant_system.strategies.equity_factor.journal.journal import Journal  # noqa: E402

logger = logging.getLogger("intraday_t")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "intraday.yaml"


# ── data fetchers ────────────────────────────────────────────────────

def fetch_quote_a_share(codes: list[str]) -> dict[str, dict[str, Optional[float]]]:
    """spot_em 拉实时价 + 量比 + 涨跌幅 (与 intraday_risk_check 同款).

    单测 monkeypatch 本函数避免真网络.
    """
    if not codes:
        return {}
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        mask = df["代码"].astype(str).isin(codes)
        wanted = ["代码", "最新价"]
        if "量比" in df.columns: wanted.append("量比")
        if "涨跌幅" in df.columns: wanted.append("涨跌幅")
        sub = df.loc[mask, wanted]
        out: dict[str, dict[str, Optional[float]]] = {}
        for _, row in sub.iterrows():
            code = str(row["代码"])
            try:
                price = float(row["最新价"])
            except (TypeError, ValueError):
                continue
            vr: Optional[float] = None
            cp: Optional[float] = None
            if "量比" in sub.columns:
                try:
                    v = float(row["量比"])
                    if v == v: vr = v
                except (TypeError, ValueError):
                    pass
            if "涨跌幅" in sub.columns:
                try:
                    c = float(row["涨跌幅"])
                    if c == c: cp = c / 100.0
                except (TypeError, ValueError):
                    pass
            out[code] = {"price": price, "vol_ratio": vr, "change_pct": cp}
        return out
    except Exception as exc:
        logger.warning("fetch_quote_a_share failed: %s", exc)
        return {}


def fetch_vwap_today_a_share(
    codes: list[str], asof_date: date,
) -> dict[str, Optional[float]]:
    """1min K 起 09:30 累计 VWAP = Σ(typical_price × volume) / Σ(volume).
    typical_price = (高+低+收)/3. 失败 / 缺数据 fail-soft None.

    单测 monkeypatch 本函数; evaluate_t_signals 内 VWAP=None 走 base 0.5 不报错.
    """
    out: dict[str, Optional[float]] = {c: None for c in codes}
    if not codes:
        return out
    try:
        import akshare as ak
    except ImportError:
        logger.warning("akshare not available; vwap fetch noop")
        return out
    asof_str = asof_date.strftime("%Y-%m-%d")
    for code in codes:
        try:
            df = ak.stock_zh_a_hist_min_em(
                symbol=code, period="1",
                start_date=f"{asof_str} 09:30:00",
                end_date=f"{asof_str} 15:00:00",
            )
            if df is None or df.empty:
                continue
            tp = (
                df["最高"].astype(float)
                + df["最低"].astype(float)
                + df["收盘"].astype(float)
            ) / 3.0
            vol = df["成交量"].astype(float)
            tot = float(vol.sum())
            if tot <= 0:
                continue
            out[code] = float((tp * vol).sum() / tot)
        except Exception as exc:
            logger.warning("fetch_vwap_today(%s) failed: %s", code, exc)
    return out


def _load_yaml() -> dict:
    if not _CONFIG_PATH.exists():
        return {}
    return yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}


def _query_sent_today(
    asof_date: date,
    symbol_market_pairs: list[tuple[str, str]],
) -> dict[tuple[str, str], list[str]]:
    """alerts_sent 当日已发 alert 类型 dict.

    Schema 限制: AlertsSent 不存 market 字段, 用 symbol 匹配.
    A 股 symbol (6 位数) 与 HK / US 不冲突 (HK 1-5 位带 lead 0, US alpha) → 安全.
    """
    out: dict[tuple[str, str], list[str]] = {
        (s, m): [] for s, m in symbol_market_pairs
    }
    if not _dualwrite_enabled():
        return out
    try:
        from sqlalchemy import select
        sym_set = {s for s, _ in symbol_market_pairs}
        with session_scope() as session:
            rows = session.scalars(
                select(AlertsSent).where(AlertsSent.asof_date == asof_date)
            ).all()
            for r in rows:
                if r.symbol in sym_set:
                    for s, m in symbol_market_pairs:
                        if s == r.symbol:
                            out[(s, m)].append(r.alert_type)
                            break
        return out
    except Exception as exc:
        logger.warning("_query_sent_today DB err: %s", exc)
        return out


def _format_telegram(ev: TSignalEvent) -> str:
    emoji = "🔻" if ev.side == "SELL" else "🔺"
    return (
        f"{emoji} T 信号 <b>{ev.side}</b> {ev.symbol} "
        f"({ev.strategy_name}/{ev.market})\n"
        f"价 {ev.suggested_price:.2f}  qty {ev.qty_ratio*100:.0f}% "
        f"(base {ev.base_qty_ratio*100:.0f}%)  confidence={ev.confidence}\n"
        f"{ev.reason}\n"
        f"⚠ advisory only, 人工下单 (Backstop #4)"
    )


def _persist_and_notify(
    asof_ts: datetime,
    asof_date: date,
    ev: TSignalEvent,
    sender: Optional[TelegramSender],
    dry_run: bool,
) -> bool:
    alert_type = f"t_signal_{ev.side.lower()}"  # t_signal_sell / t_signal_buy
    msg = _format_telegram(ev)
    if dry_run:
        logger.info(
            "[dry-run] %s %s qty=%.2f confidence=%s reason=%s",
            alert_type, ev.symbol, ev.qty_ratio, ev.confidence, ev.reason,
        )
        print(msg)
        return True

    delivered = False
    error: Optional[str] = None
    if sender:
        try:
            sender.send(msg)
            delivered = True
        except Exception as exc:
            error = str(exc)[:200]
            logger.warning("Telegram send failed: %s", exc)
            print(msg)  # stdout fallback
    else:
        print(msg)
        delivered = True  # stdout 视作 delivered

    if _dualwrite_enabled():
        try:
            with session_scope() as session:
                session.add(AlertsSent(
                    asof_ts=asof_ts,
                    asof_date=asof_date,
                    strategy_name=ev.strategy_name,
                    symbol=ev.symbol,
                    alert_type=alert_type,
                    payload={
                        "side": ev.side,
                        "suggested_price": ev.suggested_price,
                        "qty_ratio": ev.qty_ratio,
                        "base_qty_ratio": ev.base_qty_ratio,
                        "reason": ev.reason,
                        "confidence": ev.confidence,
                        "asof": ev.asof,
                    },
                    channel="telegram" if sender else "stdout",
                    delivered=delivered,
                    error=error,
                ))
        except Exception as exc:
            logger.warning(
                "write alerts_sent failed (%s/%s): %s",
                ev.strategy_name, ev.symbol, exc,
            )
    return delivered


# ── 主流程 ────────────────────────────────────────────────────────────

def run_once(dry_run: bool = False) -> int:
    """单次评估 + 推送. 返事件条数.

    流程:
      1. 读 yaml → TSignalConfig; disabled 即 noop
      2. journal.list_open() → 过滤 a_share + 策略白名单
      3. spot_em quote_map + 1min VWAP map
      4. 构 PositionSnapshot list
      5. 查 alerts_sent → sent_today dict
      6. evaluate_t_signals → TSignalEvent list
      7. 逐事件 Telegram + alerts_sent
    """
    raw = _load_yaml()
    cfg = TSignalConfig.from_yaml_dict(raw.get("t_signals") or {})
    if not cfg.enabled:
        logger.info("t_signals disabled in yaml; noop")
        return 0

    now = datetime.now()
    asof_date = now.date()

    journal = Journal()
    opens = journal.list_open()
    relevant = [
        t for t in opens
        if t.get("market") == "a_share"
        and (t.get("strategy") or "equity_factor") in cfg.strategies
    ]
    if not relevant:
        logger.info("0 relevant a_share positions; noop")
        return 0

    codes = [t["symbol"] for t in relevant]
    quote_map = fetch_quote_a_share(codes)
    vwap_map = fetch_vwap_today_a_share(codes, asof_date)

    snapshots: list[PositionSnapshot] = []
    for t in relevant:
        c = t["symbol"]
        q = quote_map.get(c)
        if q is None or q.get("price") is None:
            continue
        snapshots.append(PositionSnapshot(
            strategy_name=t.get("strategy") or "equity_factor",
            symbol=c,
            market=t["market"],
            entry_price=float(t["entry_price"]),
            current_price=float(q["price"]),
            stop_loss=(
                float(t["stop_loss_price"]) if t.get("stop_loss_price") else None
            ),
            take_profit=(
                float(t["take_profit_price"]) if t.get("take_profit_price") else None
            ),
            volume_ratio=q.get("vol_ratio"),
            day_change_pct=q.get("change_pct"),
            vwap_today=vwap_map.get(c),
        ))
    if not snapshots:
        logger.info("no valid snapshots after quote fetch; noop")
        return 0

    sym_mkts = [(p.symbol, p.market) for p in snapshots]
    sent_today = _query_sent_today(asof_date, sym_mkts)

    events = evaluate_t_signals(snapshots, cfg, now, sent_today)
    if not events:
        logger.info(
            "0 t_signals triggered (positions=%d, sent_today_keys=%d)",
            len(snapshots), sum(len(v) for v in sent_today.values()),
        )
        return 0

    sender: Optional[TelegramSender] = None
    if not dry_run:
        try:
            sender = TelegramSender.from_env()
        except Exception as exc:
            logger.warning("Telegram env not set (%s); stdout fallback", exc)

    n = 0
    for ev in events:
        if _persist_and_notify(now, asof_date, ev, sender, dry_run):
            n += 1
    logger.info("t_signals: %d / %d events delivered", n, len(events))
    return n


def run_loop(dry_run: bool = False, poll_seconds: int = 300) -> None:
    """nohup 守护循环. 5min 轮询. 时段外仍跑 (evaluate_t_signals 内时段过滤负责 noop)."""
    while True:
        try:
            run_once(dry_run=dry_run)
        except Exception as exc:
            logger.error("run_once error: %s", exc)
        _time.sleep(poll_seconds)


def main() -> int:
    p = argparse.ArgumentParser(description="持仓中日内做 T 信号 advisory v1 (A 股)")
    p.add_argument("--loop", action="store_true", help="nohup 守护模式 5min 轮询")
    p.add_argument(
        "--dry-run", action="store_true",
        help="不写 DB / 不推 Telegram (仅 stdout)",
    )
    args = p.parse_args()
    if args.loop:
        run_loop(dry_run=args.dry_run)
        return 0
    run_once(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
