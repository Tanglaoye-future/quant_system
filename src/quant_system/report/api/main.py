"""Quant report API server."""

from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from quant_system.report.api.routes import router as report_router, DATA_DIR

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
