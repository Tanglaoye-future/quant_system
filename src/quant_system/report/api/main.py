"""Quant report API server."""

from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from quant_system.report.api.routes import router as report_router, DATA_DIR, _read_json

app = FastAPI(title="Quant Report API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(report_router)


@app.get("/api/health")
def health():
    from quant_system.report.registry import resolve_matrix

    cells, _ = resolve_matrix()
    has_quant = any(c.has_data and c.strategy_kind in ("bottomup_timing", "mean_reversion") for c in cells)
    has_options = any(c.has_data and c.strategy_kind == "bull_call_spread" for c in cells)
    has_zhuang = any(c.has_data and c.strategy_kind == "zhuang" for c in cells)
    return {
        "status": "ok",
        "data_available": {
            "quant": has_quant,
            "options": has_options,
            "zhuang": has_zhuang,
        },
    }


@app.get("/api/markets")
def get_markets():
    """Aggregate market data — now backed by registry, same response shape.

    Old shape preserved for frontend backward compat during migration.
    New consumers should use GET /api/report/matrix (also aliased at /api/matrix).
    """
    from quant_system.report.registry import resolve_matrix

    _, groups = resolve_matrix()
    a_share = next((g for g in groups if g.market_name == "a_share"), None)
    hk_group = next((g for g in groups if g.market_name == "hk_share"), None)
    us_group = next((g for g in groups if g.market_name == "us_share"), None)

    def _cell_by_strategy(g, name):
        if g is None:
            return None
        for c in g.cells:
            if c.strategy_name == name:
                return c
        return None

    def _build_strategies(g) -> list[dict]:
        if g is None:
            return []
        result = []
        for c in g.cells:
            entry = {
                "key": c.strategy_name,
                "name": c.strategy_label,
                "status": "active" if c.status.value == "active" and c.has_data else
                         ("idle" if c.status.value == "active" else c.status.value),
                "missing": not c.has_data,
            }
            # 合并 metrics
            m = c.metrics
            if c.strategy_kind == "bottomup_timing" or c.strategy_kind == "mean_reversion":
                entry.update({
                    "signals": m.get("signals_count", 0),
                    "positions": m.get("positions_count", 0),
                    "gate_ok": m.get("market_gate"),
                })
            elif c.strategy_kind == "bull_call_spread":
                entry.update({
                    "ivr": m.get("ivr"), "iv_mode": m.get("iv_mode", "—"),
                    "grade": m.get("signal_grade", "—"),
                    "qqq_price": m.get("qqq_price"), "qqq_rsi": m.get("qqq_rsi"),
                    "reason": m.get("reason", ""),
                })
            elif c.strategy_kind == "zhuang":
                entry.update({
                    "candidates": m.get("candidates_count", 0),
                    "max_score": 0,
                    "gate_ok": None,
                })
            result.append(entry)
        return result

    return {
        "a_share": {
            "index": a_share.index_info if a_share else {},
            "strategies": _build_strategies(a_share),
        },
        "us": {
            "index": us_group.index_info if us_group else {},
            "strategies": _build_strategies(us_group),
        },
        "hk": {
            "index": hk_group.index_info if hk_group else {},
            "strategies": _build_strategies(hk_group),
        },
    }


@app.get("/api/matrix")
def get_matrix_alias():
    """Alias for GET /api/report/matrix — discovered strategy-market grid."""
    from quant_system.report.api.routes import get_matrix as _matrix
    return _matrix()
