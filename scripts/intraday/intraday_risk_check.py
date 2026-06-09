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
from datetime import date, datetime, timedelta
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
    BreakoutCandidateQuote,
    BreakoutConfig,
    IntradayConfig,
    PortfolioSnapshot,
    PositionSnapshot,
    Watchlist,
    evaluate_alerts,
    evaluate_breakout_alerts,
    is_in_trading_window,
    is_watchlist_stale,
    load_watchlist,
)
from quant_system.notify import TelegramSender  # noqa: E402
from quant_system.strategies.equity_factor.journal.journal import Journal  # noqa: E402
from quant_system.strategies.equity_factor.risk.monitor import compute_peak_drawdown  # noqa: E402

logger = logging.getLogger("intraday")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "intraday.yaml"
_JOURNAL_PATH = Path(__file__).resolve().parents[2] / "data" / "journal.db"
_WATCHLIST_EQUITY_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "intraday" / "equity_watchlist.json"
)


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


def fetch_realtime_quote_with_vol_ratio_a_share(
    codes: list[str],
) -> dict[str, dict[str, Optional[float]]]:
    """PR2/PR3: 拉实时价 + 量比 + 涨跌幅 (akshare spot_em).
    返回 {code: {price: float, vol_ratio: Optional[float], change_pct: Optional[float]}}.
    change_pct 是小数 (0.04 = +4%), 不是百分数. 缺失字段 None 不抛.
    """
    if not codes:
        return {}
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        mask = df["代码"].astype(str).isin(codes)
        wanted_cols = ["代码", "最新价"]
        if "量比" in df.columns:
            wanted_cols.append("量比")
        if "涨跌幅" in df.columns:
            wanted_cols.append("涨跌幅")
        sub = df.loc[mask, wanted_cols]
        out: dict[str, dict[str, Optional[float]]] = {}
        for _, row in sub.iterrows():
            code = str(row["代码"])
            try:
                price = float(row["最新价"])
            except (TypeError, ValueError):
                continue
            vol_ratio: Optional[float] = None
            change_pct: Optional[float] = None
            if "量比" in sub.columns:
                try:
                    v = float(row["量比"])
                    if v == v:
                        vol_ratio = v
                except (TypeError, ValueError):
                    pass
            if "涨跌幅" in sub.columns:
                try:
                    c = float(row["涨跌幅"])
                    if c == c:
                        change_pct = c / 100.0  # akshare 给百分数; 内部统一小数
                except (TypeError, ValueError):
                    pass
            out[code] = {
                "price": price,
                "vol_ratio": vol_ratio,
                "change_pct": change_pct,
            }
        return out
    except Exception as exc:
        logger.warning("fetch_realtime_quote_with_vol_ratio_a_share failed: %s", exc)
        return {}


def fetch_ma_long_a_share(codes: list[str], asof: date, n: int = 60) -> dict[str, float]:
    """每只票拉 ≈ 2n 个自然日的 daily 收盘 (qfq) → 取最后 n 条算 SMA。

    用 T-1 作为 end_date 避免 T 日盘中价污染 MA60 基线。
    失败 / 数据不足 静默 None。回测 / 单测 monkeypatch 本函数。
    """
    if not codes:
        return {}
    try:
        import akshare as ak
    except ImportError:
        logger.warning("akshare not available; ma_long fetch noop")
        return {}
    end = (asof - timedelta(days=1)).strftime("%Y%m%d")
    # 2n 自然日 + 30 天缓冲覆盖周末/节假日
    start = (asof - timedelta(days=n * 2 + 30)).strftime("%Y%m%d")
    out: dict[str, float] = {}
    for code in codes:
        try:
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=start, end_date=end, adjust="qfq",
            )
            if df is None or len(df) < n:
                continue
            closes = df["收盘"].dropna().astype(float).tail(n)
            if len(closes) < n:
                continue
            out[code] = float(closes.mean())
        except Exception as exc:
            logger.warning("fetch_ma_long(%s) failed: %s", code, exc)
    return out


def _load_yaml() -> dict:
    if not _CONFIG_PATH.exists():
        return {}
    return yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}


# ── 主流程 ────────────────────────────────────────────────────────────

def _build_position_snapshots(
    journal: Journal,
    quote_map: dict[str, dict[str, Optional[float]]],
    ma_long_map: Optional[dict[str, float]] = None,
) -> list[PositionSnapshot]:
    """journal_trades open + quote (price/vol/change) + MA60 → PositionSnapshot list.

    PR3 改: 输入从单纯 price_map 升级为 quote_map (统一 spot_em 单次调用),
    以同时填 volume_ratio / day_change_pct (zhuang_distribution_warning 用).
    """
    ma_long_map = ma_long_map or {}
    snapshots: list[PositionSnapshot] = []
    for t in journal.list_open():
        code = t["symbol"]
        q = quote_map.get(code)
        if q is None or q.get("price") is None:
            continue
        strategy = t.get("strategy") or "equity_factor"
        snapshots.append(PositionSnapshot(
            strategy_name=strategy,
            symbol=code,
            market=t["market"],
            entry_price=float(t["entry_price"]),
            current_price=float(q["price"]),
            stop_loss=float(t["stop_loss_price"]) if t.get("stop_loss_price") else None,
            take_profit=float(t["take_profit_price"]) if t.get("take_profit_price") else None,
            ma_long=ma_long_map.get(code),
            volume_ratio=q.get("vol_ratio"),
            day_change_pct=q.get("change_pct"),
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


def _evaluate_breakout_for_watchlist(
    watchlist: Watchlist,
    breakout_cfg: BreakoutConfig,
    open_symbols: set[str],
    quote_map: dict[str, dict[str, Optional[float]]],
    now: datetime,
) -> list[AlertEvent]:
    """PR2/PR3: 读 watchlist → 过滤已持仓 → 用上层共享的 quote_map → evaluate_breakout_alerts.

    PR3 改: quote_map 由 run_once 统一拉一次 (持仓 + 候选共用), 减半 spot_em 调用.
    """
    if not breakout_cfg.enabled:
        return []
    if is_watchlist_stale(watchlist, today=now.date(),
                          max_age_days=breakout_cfg.watchlist_max_age_days):
        logger.info("watchlist stale (asof=%s); skip breakout", watchlist.asof_date)
        return []
    candidates = [c for c in watchlist.candidates if c.symbol not in open_symbols]
    if not candidates:
        return []
    quotes: list[BreakoutCandidateQuote] = []
    for c in candidates:
        q = quote_map.get(c.symbol)
        if q is None or q.get("price") is None:
            continue
        quotes.append(BreakoutCandidateQuote(
            symbol=c.symbol,
            name=c.name,
            strategy_name=watchlist.strategy,
            market=watchlist.market,
            current_price=float(q["price"]),
            reference_high=c.reference_high,
            volume_ratio=q.get("vol_ratio"),
            entry_price_suggested=c.entry_price_suggested,
            stop_loss_suggested=c.stop_loss_suggested,
            take_profit_suggested=c.take_profit_suggested,
            factor_score=c.factor_score,
        ))
    return evaluate_breakout_alerts(quotes, breakout_cfg)


def run_once(dry_run: bool = False) -> int:
    """执行一次评估 + 推送。返触发条数。

    PR3 后流程:
    - 统一一次 spot_em 调用拿 (price + vol_ratio + change_pct) for 持仓 ∪ 候选
    - 持仓评估 (proximity / break_* / zhuang_distribution / portfolio_*)
    - 候选股突破评估 (daily_screen_breakout) — 共用 quote_map
    """
    raw = _load_yaml()
    raw_alerts = raw.get("intraday_alerts") or {}
    cfg = IntradayConfig.from_yaml_dict(
        raw_alerts, zhuang_raw=raw.get("zhuang_distribution"),
    )
    breakout_cfg = BreakoutConfig.from_yaml_dict(raw.get("breakout") or {})
    if not cfg.enabled and not breakout_cfg.enabled:
        logger.info("intraday_alerts + breakout 全 disabled; noop")
        return 0

    now = datetime.now()
    if not is_in_trading_window(now, cfg) and not dry_run:
        logger.info("not in trading window (%s); skip", now.strftime("%H:%M:%S"))
        return 0

    journal = Journal(str(_JOURNAL_PATH))
    open_trades = journal.list_open()
    open_symbols = {t["symbol"] for t in open_trades}
    a_share_open_codes = [t["symbol"] for t in open_trades if t.get("market") == "a_share"]

    # ── PR3: 统一 quote_map (持仓 + watchlist 候选共用一次 spot_em) ──
    wl: Optional[Watchlist] = None
    if breakout_cfg.enabled:
        wl = load_watchlist(_WATCHLIST_EQUITY_PATH)
        if wl is None:
            logger.info("equity watchlist not found at %s",
                        _WATCHLIST_EQUITY_PATH)
    watchlist_codes: list[str] = []
    if wl is not None and not is_watchlist_stale(
        wl, today=now.date(), max_age_days=breakout_cfg.watchlist_max_age_days,
    ):
        watchlist_codes = [c.symbol for c in wl.candidates if c.symbol not in open_symbols]
    all_codes = sorted(set(a_share_open_codes) | set(watchlist_codes))
    quote_map: dict[str, dict[str, Optional[float]]] = {}
    if all_codes:
        quote_map = fetch_realtime_quote_with_vol_ratio_a_share(all_codes)

    events: list[AlertEvent] = []

    # ── 持仓告警 (incl. PR3 zhuang_distribution_warning) ─────────────
    if cfg.enabled and a_share_open_codes and quote_map:
        ma_long_map = fetch_ma_long_a_share(a_share_open_codes, asof=now.date())
        positions = _build_position_snapshots(journal, quote_map, ma_long_map)
        portfolios = _build_portfolio_snapshots(
            positions, asof=now.strftime("%Y-%m-%d"),
        )
        pos_events = evaluate_alerts(positions, portfolios, cfg)
        logger.info("position alerts: %d (positions=%d portfolios=%d)",
                    len(pos_events), len(positions), len(portfolios))
        events.extend(pos_events)
    elif cfg.enabled and a_share_open_codes:
        logger.warning("no realtime quote for positions (network / 非交易日)")

    # ── PR2: 候选股突破 (watchlist) — 共用 quote_map ──────────────────
    if breakout_cfg.enabled and wl is not None:
        br_events = _evaluate_breakout_for_watchlist(
            wl, breakout_cfg, open_symbols, quote_map, now,
        )
        logger.info("breakout alerts: %d (watchlist asof=%s, n_cand=%d)",
                    len(br_events), wl.asof_date, len(wl.candidates))
        events.extend(br_events)

    if not events:
        return 0

    # ── 推送 (dedup + persist) ────────────────────────────────────────
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
