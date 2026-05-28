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

    return {
        "date": merged_date,
        "market": merged_market,
        "market_gate": merged_gate,
        "market_gate_msg": merged_gate_msg,
        "benchmark_close": "—",
        "benchmark_ma60": "—",
        "signals": merged_signals,
        "positions": merged_positions,
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


@router.get("/summary")
def get_summary():
    return {
        "quant": get_quant(),
        "options": get_options(),
        "zhuang": get_zhuang(),
    }


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
