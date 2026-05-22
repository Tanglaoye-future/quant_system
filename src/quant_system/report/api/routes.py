"""Report API routes — reads report/data/*.json and serves via REST."""

import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/api/report")
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = PROJECT_ROOT / "report" / "data"


def _read_json(system: str) -> dict:
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
    return _merge_quant()


@router.get("/options")
def get_options():
    return _read_json("options")


@router.get("/zhuang")
def get_zhuang():
    return _read_json("zhuang")


@router.get("/summary")
def get_summary():
    return {
        "quant": _merge_quant(),
        "options": _read_json("options"),
        "zhuang": _read_json("zhuang"),
    }
