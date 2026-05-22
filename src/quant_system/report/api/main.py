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
    quant_files = [
        "quant_a_share_bottomup_timing.json",
        "quant_hk_share_bottomup_timing.json",
        "quant_a_share_mean_reversion.json",
    ]
    has_quant = any((DATA_DIR / f).exists() for f in quant_files)
    has_options = (DATA_DIR / "options.json").exists()
    has_zhuang = (DATA_DIR / "zhuang.json").exists()
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
    """Aggregate all JSON data by market (A股 / 美股 / 港股) with index + strategy summaries."""
    a_mom = _read_json("quant_a_share_bottomup_timing")
    a_mr = _read_json("quant_a_share_mean_reversion")
    hk_mom = _read_json("quant_hk_share_bottomup_timing")
    opt = _read_json("options")
    zhuang = _read_json("zhuang")

    return {
        "a_share": {
            "index": {
                "name": "沪深300",
                "symbol": "000300",
                "close": a_mom.get("benchmark_close", "—"),
                "ma60": a_mom.get("benchmark_ma60", "—"),
                "regime": "ok" if a_mom.get("market_gate") else ("closed" if a_mom.get("market_gate") is False else "unknown"),
                "regime_msg": a_mom.get("market_gate_msg", ""),
            },
            "strategies": [
                {
                    "key": "equity_mom",
                    "name": "中线 momentum",
                    "status": "active" if len(a_mom.get("signals", [])) > 0 else "idle",
                    "signals": len(a_mom.get("signals", [])),
                    "positions": len(a_mom.get("positions", [])),
                    "gate_ok": a_mom.get("market_gate"),
                    "missing": a_mom.get("_missing", False),
                },
                {
                    "key": "equity_mr",
                    "name": "中线 mean-reversion",
                    "status": "active" if len(a_mr.get("signals", [])) > 0 else "idle",
                    "signals": len(a_mr.get("signals", [])),
                    "positions": len(a_mr.get("positions", [])),
                    "gate_ok": None,
                    "missing": a_mr.get("_missing", False),
                },
                {
                    "key": "zhuang",
                    "name": "庄股跟庄",
                    "status": "active" if zhuang.get("candidates_count", 0) > 0 else "idle",
                    "candidates": zhuang.get("candidates_count", 0),
                    "max_score": (zhuang.get("top_candidates") or [{}])[0].get("total", 0) if zhuang.get("top_candidates") else 0,
                    "gate_ok": zhuang.get("market_trend"),
                    "missing": zhuang.get("_missing", False),
                },
            ],
        },
        "us": {
            "index": {
                "name": "QQQ",
                "symbol": "QQQ",
                "close": opt.get("qqq_price"),
                "ma200": opt.get("qqq_ma200"),
                "regime": "bullish" if opt.get("qqq_bullish") else "bearish",
                "regime_msg": "",
            },
            "strategies": [
                {
                    "key": "options",
                    "name": "期权 Bull Call Spread",
                    "status": "signal" if opt.get("signal") else ("ready" if opt.get("qqq_bullish") else "waiting"),
                    "ivr": opt.get("ivr"),
                    "iv_mode": opt.get("iv_mode", "—"),
                    "grade": opt.get("signal_grade", "—"),
                    "qqq_price": opt.get("qqq_price"),
                    "qqq_rsi": opt.get("qqq_rsi"),
                    "reason": opt.get("reason", ""),
                    "missing": opt.get("_missing", False),
                },
            ],
        },
        "hk": {
            "index": {
                "name": "恒生中国100",
                "symbol": "HSCHK100",
                "close": hk_mom.get("benchmark_close", "—"),
                "ma": hk_mom.get("benchmark_ma60", "—"),
                "regime": "ok" if hk_mom.get("market_gate") else ("closed" if hk_mom.get("market_gate") is False else "unknown"),
                "regime_msg": hk_mom.get("market_gate_msg", ""),
            },
            "strategies": [
                {
                    "key": "equity_mom",
                    "name": "中线 momentum",
                    "status": "active" if len(hk_mom.get("signals", [])) > 0 else "idle",
                    "signals": len(hk_mom.get("signals", [])),
                    "positions": len(hk_mom.get("positions", [])),
                    "gate_ok": hk_mom.get("market_gate"),
                    "missing": hk_mom.get("_missing", False),
                },
            ],
        },
    }
