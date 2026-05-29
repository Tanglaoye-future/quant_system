"""Compute 侧写库层 —— daily 脚本双写(JSON + DB)的 DB 半边（三层解耦 Phase 2）。

与 report.repositories（读半边）对称：repositories 把 DB 行还原成 JSON 形状，
本模块把**写 JSON 的同一份 payload dict** 落成 DB 行 —— 两边同源，天然一致。

dual-write 经 maybe_ingest_* 入口，受 QUANT_PG_DUALWRITE env 开关控制（默认开）；
DB 不可达时只 logger.warning 不抛出 —— daily 以 JSON 为主，不被 DB 拖垮。

字段映射遵循 [[db-decouple-phase0-2026-05]] 约定（与 repositories 反向）：
- Signal:   归一列 code/name/score/reason/action；其余 → payload
- Position: 归一列 code/name/action/entry_date/hold_days/pnl_pct；其余 → payload
- options:  date/market 外全部标量 → metrics
- zhuang:   候选 code+total(→score)，因子分项 → payload；汇总 → metrics
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_system.db.models import Position, Signal, StrategyRun
from quant_system.db.session import session_scope

logger = logging.getLogger(__name__)

_SIGNAL_COLS = {"code", "name", "score", "reason", "action"}
_POSITION_COLS = {"code", "name", "action", "entry_date", "hold_days", "pnl_pct"}


def _parse_date(value: Any) -> Optional[date]:
    if value is None or value == "" or value == "—":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _replace_run(session: Session, run_date: date, strategy_name: Optional[str], market: str) -> None:
    """幂等：删掉同 (run_date, strategy_name, market) 的旧跑批（级联清 signals/positions），再插新。"""
    existing = session.scalars(
        select(StrategyRun).where(
            StrategyRun.run_date == run_date,
            StrategyRun.strategy_name == strategy_name,
            StrategyRun.market == market,
        )
    ).all()
    for run in existing:
        session.delete(run)
    if existing:
        session.flush()


def ingest_quant(session: Session, payload: dict[str, Any]) -> StrategyRun:
    """equity_factor daily payload（bottomup_timing / mean_reversion）→ DB。"""
    run_date = _parse_date(payload["date"])
    strategy_name = payload.get("strategy_name") or payload.get("strategy")
    market = payload["market"]
    _replace_run(session, run_date, strategy_name, market)

    metrics = {
        k: payload[k]
        for k in ("strategy", "benchmark_close", "benchmark_ma60")
        if k in payload
    }
    run = StrategyRun(
        run_date=run_date,
        strategy_name=strategy_name,
        strategy_kind=payload["strategy_kind"],
        market=market,
        market_gate=payload.get("market_gate"),
        market_gate_msg=payload.get("market_gate_msg"),
        metrics=metrics,
        status="ok",
    )
    for s in payload.get("signals", []):
        run.signals.append(
            Signal(
                code=s["code"],
                name=s.get("name"),
                score=s.get("score"),
                reason=s.get("reason"),
                action=s.get("action"),
                payload={k: v for k, v in s.items() if k not in _SIGNAL_COLS},
            )
        )
    for p in payload.get("positions", []):
        run.positions.append(
            Position(
                code=p["code"],
                name=p.get("name"),
                entry_date=_parse_date(p.get("entry_date")),
                hold_days=p.get("hold_days"),
                pnl_pct=p.get("pnl_pct"),
                action=p.get("action"),
                payload={k: v for k, v in p.items() if k not in _POSITION_COLS},
            )
        )
    session.add(run)
    return run


def ingest_options(session: Session, payload: dict[str, Any]) -> StrategyRun:
    """options daily payload（bull_call_spread）→ DB。date/market 外全进 metrics。"""
    run_date = _parse_date(payload["date"])
    market = payload["market"]
    strategy_name = payload.get("underlying")
    _replace_run(session, run_date, strategy_name, market)

    metrics = {k: v for k, v in payload.items() if k not in ("date", "market")}
    run = StrategyRun(
        run_date=run_date,
        strategy_name=strategy_name,
        strategy_kind="bull_call_spread",
        market=market,
        metrics=metrics,
        status="ok",
    )
    session.add(run)
    return run


def ingest_zhuang(session: Session, payload: dict[str, Any]) -> StrategyRun:
    """zhuang daily payload → DB。候选落 signals，汇总进 metrics。"""
    run_date = _parse_date(payload["date"])
    market = payload.get("market", "a_share")
    strategy_name = "zhuang"
    _replace_run(session, run_date, strategy_name, market)

    metrics = {
        "universe_size": payload.get("universe_size"),
        "candidates_count": payload.get("candidates_count"),
        "market_trend": payload.get("market_trend"),
    }
    run = StrategyRun(
        run_date=run_date,
        strategy_name=strategy_name,
        strategy_kind="zhuang",
        market=market,
        metrics=metrics,
        status="ok",
    )
    for c in payload.get("top_candidates", []):
        run.signals.append(
            Signal(
                code=c["code"],
                score=c.get("total"),
                payload={k: v for k, v in c.items() if k not in ("code", "total")},
            )
        )
    for p in payload.get("positions", []):
        run.positions.append(
            Position(
                code=p["code"],
                name=p.get("name"),
                entry_date=_parse_date(p.get("entry_date")),
                hold_days=p.get("hold_days"),
                pnl_pct=p.get("pnl_pct"),
                action=p.get("action"),
                payload={k: v for k, v in p.items() if k not in _POSITION_COLS},
            )
        )
    session.add(run)
    return run


# ── dual-write 入口（daily 脚本调用）─────────────────────────────────────

def _dualwrite_enabled() -> bool:
    return os.environ.get("QUANT_PG_DUALWRITE", "1").lower() not in ("0", "false", "no", "off")


def _maybe(fn: Callable[[Session, dict], StrategyRun], payload: dict[str, Any], label: str) -> bool:
    """env 开 → 试写 DB；失败只告警不抛（JSON 仍为准）。返回是否成功写入。"""
    if not _dualwrite_enabled():
        return False
    try:
        with session_scope() as session:
            fn(session, payload)
        logger.info("dual-write %s → Postgres ok", label)
        return True
    except Exception as exc:
        logger.warning("dual-write %s → Postgres failed (%s); JSON 仍为准", label, exc)
        return False


def maybe_ingest_quant(payload: dict[str, Any]) -> bool:
    return _maybe(ingest_quant, payload, "quant")


def maybe_ingest_options(payload: dict[str, Any]) -> bool:
    return _maybe(ingest_options, payload, "options")


def maybe_ingest_zhuang(payload: dict[str, Any]) -> bool:
    return _maybe(ingest_zhuang, payload, "zhuang")
