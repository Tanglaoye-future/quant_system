"""Report API routes — DB-first（repo 层），DB 空/不可达时回退 report/data/*.json。"""

import json
import logging
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter

from quant_system.db.session import session_scope

router = APIRouter(prefix="/api/report")
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = PROJECT_ROOT / "report" / "data"

logger = logging.getLogger(__name__)


def _db_or_json(repo_fn: Callable, json_fn: Callable[[], dict]) -> dict:
    """过渡安全网：先试 DB（repo），无数据或连不上则回退 JSON reader。

    Phase 1 阶段 DB 为空，实际总是走 JSON —— 生产行为不变。
    Phase 2 daily 双写后 DB 有数据，自动切到 DB 路径。
    """
    try:
        with session_scope() as session:
            payload: Optional[dict] = repo_fn(session)
        if payload is not None:
            return payload
    except Exception as exc:  # DB 不可达 / 查询异常 —— 回退 JSON，不影响服务
        logger.warning("DB read failed (%s), falling back to JSON", exc)
    return json_fn()


def _read_json(system: str) -> dict:
    """Read a JSON file from report/data/. Public so main.py can use it for /api/markets."""
    path = DATA_DIR / f"{system}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"_missing": True, "system": system}


def _merge_quant() -> dict:
    sources = [
        ("quant_hk_share_bottomup_timing.json", "HK 港股 · momentum"),
        ("quant_a_share_bottomup_timing.json", "A 股 · momentum"),
        ("quant_a_share_mean_reversion.json", "A 股 · mean-reversion"),
    ]
    any_found = any((DATA_DIR / f).exists() for f, _ in sources)
    if not any_found and (DATA_DIR / "quant.json").exists():
        return _read_json("quant")

    merged_signals = []
    merged_positions = []
    merged_alerts = []  # 组合层 alerts，前缀策略 label 后合并
    merged_date = ""
    merged_market = ""
    merged_gate = None
    merged_gate_msg = ""

    for filename, label in sources:
        path = DATA_DIR / filename
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        merged_date = data.get("date", merged_date)
        merged_market = merged_market or data.get("market", "")
        if data.get("market_gate") is not None:
            merged_gate = data["market_gate"]
            merged_gate_msg = data.get("market_gate_msg", "")
        for s in data.get("signals", []):
            s = dict(s)
            s.setdefault("name", "")
            s["_source"] = label
            merged_signals.append(s)
        for p in data.get("positions", []):
            p = dict(p)
            p.setdefault("name", "")
            p["_source"] = label
            merged_positions.append(p)
        for a in data.get("portfolio_alerts", []) or []:
            merged_alerts.append(f"[{label}] {a}")

    return {
        "date": merged_date,
        "market": merged_market,
        "market_gate": merged_gate,
        "market_gate_msg": merged_gate_msg,
        "benchmark_close": "—",
        "benchmark_ma60": "—",
        "signals": merged_signals,
        "positions": merged_positions,
        "portfolio_alerts": merged_alerts,
    }


@router.get("/quant")
def get_quant():
    from quant_system.report import repositories

    return _db_or_json(repositories.quant_payload, _merge_quant)


@router.get("/options")
def get_options():
    from quant_system.report import repositories

    return _db_or_json(repositories.options_payload, lambda: _read_json("options"))


@router.get("/zhuang")
def get_zhuang():
    from quant_system.report import repositories

    return _db_or_json(repositories.zhuang_payload, lambda: _read_json("zhuang"))


@router.get("/cb")
def get_cb():
    """CB 双低 advisory (PR7 2026-06-16). advisory_only → 不入 DB, 直接读 JSON."""
    return _read_json("quant_cb")


@router.get("/passive")
def get_passive():
    """v7 配比里的被动持仓 (QQQ / GLD / BTC) spot snapshot. 不入 DB, 直接读 JSON."""
    return _read_json("passive_holdings")


@router.get("/summary")
def get_summary():
    return {
        "quant": get_quant(),
        "options": get_options(),
        "zhuang": get_zhuang(),
    }


# ── Panic / capitulation dashboard (Phase 3: frontend single-pane) ──────

@router.get("/panic")
def get_panic():
    """Return panic dashboard data (panic candidates, rebound, LHB, sentiment,
    sector rankings, sleeve overlap, history trend)."""
    payload = _read_json("panic_dashboard")

    # Merge history if available
    history_path = DATA_DIR / "panic_dashboard_history.json"
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
            payload["history"] = history
        except Exception:
            payload["history"] = payload.get("history", [])

    return payload


# ── T 信号 dashboard (spec docs/specs/intraday_t_execution_a_share.md PR5) ──
#
# 从 alerts_sent 表读今日 t_signal_sell / t_signal_buy 事件 + 最近 5 天上下文。
# 默认 yaml disabled → 表中 0 行 → 前端 0 条 (零行为差异 Backstop)。

@router.get("/t_signals")
def get_t_signals():
    """今日 T 信号 + 最近 5 天历史. 用于 dashboard TSignalCard."""
    from datetime import date, timedelta
    from sqlalchemy import select
    from quant_system.db import AlertsSent

    payload: dict = {"today": [], "history": []}
    try:
        today = date.today()
        five_days_ago = today - timedelta(days=5)
        with session_scope() as session:
            rows = session.scalars(
                select(AlertsSent)
                .where(AlertsSent.asof_date >= five_days_ago)
                .where(AlertsSent.alert_type.in_(["t_signal_sell", "t_signal_buy"]))
                .order_by(AlertsSent.asof_ts.desc())
            ).all()
            for r in rows:
                p = r.payload or {}
                row = {
                    "asof_ts": r.asof_ts.isoformat() if r.asof_ts else None,
                    "asof_date": r.asof_date.isoformat() if r.asof_date else None,
                    "strategy_name": r.strategy_name,
                    "symbol": r.symbol,
                    "alert_type": r.alert_type,
                    "side": p.get("side"),
                    "suggested_price": p.get("suggested_price"),
                    "qty_ratio": p.get("qty_ratio"),
                    "confidence": p.get("confidence"),
                    "reason": p.get("reason"),
                    "delivered": r.delivered,
                }
                if r.asof_date == today:
                    payload["today"].append(row)
                else:
                    payload["history"].append(row)
    except Exception as exc:
        logger.warning("get_t_signals DB read failed: %s", exc)
    payload["asof_today"] = date.today().isoformat()
    return payload


# ── Dynamic strategy-market matrix (Phase 2: registry-backed) ──────────

@router.get("/matrix")
def get_matrix():
    from quant_system.report.registry import resolve_matrix

    cells, groups = resolve_matrix()
    return {
        "markets": [
            {
                "market_name": g.market_name,
                "market_label": g.market_label,
                "display_order": g.display_order,
                "index": g.index_info,
                "cells": [
                    {
                        "strategy_name": c.strategy_name,
                        "strategy_label": c.strategy_label,
                        "strategy_kind": c.strategy_kind,
                        "status": c.status.value,
                        "has_data": c.has_data,
                        "data_date": c.data_date,
                        "config_enabled": c.config_enabled,
                        "blocker_reason": c.blocker_reason,
                        "metrics": c.metrics,
                    }
                    for c in g.cells
                ],
            }
            for g in groups
        ],
        "strategies": sorted({c.strategy_name for c in cells}),
    }
