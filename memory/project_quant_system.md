---
name: quant_system project overview
description: Overview of the quant_system repo — a Chinese A-share & HK quantitative trading system with modular milestones M0-M5
type: project
---

**Repo path**: `C:\Users\Lenovo\workspace\01_Projects\quant_system\repo`

The quant_system is a quantitative trading system targeting Chinese A-share (HS300) and Hong Kong (HSCHK100) markets for mid-term holding (20–60 trading days) with manual order execution.

**Core package structure** (`quant_system/`):
- `data/loader.py` — UnifiedDataLoader, akshare sole data source, 1-day parquet cache
- `universe/filter.py` — UniverseFilter: liquidity/quality/listing/suspension hard gates
- `bottomup/factors.py` — 5-factor Z-score (PE/PB/ROE/RevGrowth/3M-Momentum)
- `bottomup/portfolio.py` — M4Config: industry concentration + risk budget reordering
- `timing/signals.py` — Entry (trend+momentum+volume), exit (ATR trail, MA60, TP, RSI, time), M2/M3
- `timing/regime.py` — MarketRegimeGate (M2), TimingRegimeContext (M3)
- `timing/exit_taxonomy.py` — exit_layer enum mapping
- `engine/backtest.py` — T+1 A-stock backtester with slippage/fees/diagnostics
- `engine/strategy.py` — BottomupTimingStrategy (M2 gate, M4 reorder, M5 force exit)
- `engine/metrics.py` — Sharpe, drawdown, win rate, admission check
- `journal/journal.py` — SQLite trade log (4-dimension entry reasons)
- `risk/monitor.py` — Daily position risk snapshot + exit assessment
- `catalyst/monitor.py` — Earnings, dragon-tiger, limit-up board
- `topdown/macro.py` — CPI/PPI regime + sector rotation

**Key scripts**:
- `scripts/backtest.py` — Full backtest, output to `data/backtest/<strategy>_<market>_<start>_<end>/`
- `scripts/daily_run.py` — Production workflow: risk → catalyst → screen → buy list
- `scripts/audit_m0_outputs.py` — Automated M0 artifact audit
- `scripts/run_acceptance.ps1` — Full pytest suite

**Why:** Active research project building toward M-terminal (M终). Each milestone has specific audit standards that must pass before merging changes.
**How to apply:** Always map user requests to an M-node before writing code; run acceptance tests + M0 audit after changes.
