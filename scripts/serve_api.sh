#!/bin/bash
# Start the quant report API server
cd "$(dirname "$0")/.."
PYTHONPATH="$PWD/src" venv/bin/uvicorn quant_system.report.api.main:app --reload --host 0.0.0.0 --port 8000
