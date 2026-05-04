---
name: quant_system M0–M终 milestones and audit standards
description: Mandatory M-node milestone definitions, audit checklists, and anti-patterns for every code change in quant_system. Auto-relevant when touching strategy/backtest/timing/config.yaml/universe/factors/daily_run.
type: project
---

**Source**: `.cursor/skills/quant-system-milestones/SKILL.md` + `reference.md` in repo.

Apply this whenever the user: changes strategy/universe/timing/backtest/config.yaml/diagnostics, mentions an M-node, asks about acceptance/audit/reproducibility/no-lookahead.

---

## Milestone Definitions

| Node | Definition | Key files |
|------|-----------|-----------|
| **M0** | Fixed output dir `data/backtest/<strategy>_<market>_<start>_<end>/`; all diagnostic files present; `audit_m0_outputs.py` PASS | `scripts/backtest.py`, `engine/backtest.py` (BacktestDiagnostics), `scripts/audit_m0_outputs.py` |
| **M1** | Tradeable universe: liquidity/market cap/price/ROE/debt/listing/suspension/limit-up hard gates; per-rule rejection counts by asof | `universe/filter.py`, `engine/strategy.py`, `data/loader.py` |
| **M2** | Market regime gate (index > MA) + single-stock RSI with ATR adjustment, optional green bar/median volume/structure breakout | `timing/regime.py`, `timing/signals.py`, `config.yaml → strategy.timing` |
| **M3** | RSI band width explicitly tied to index gap vs MA and volatility; multi-period RSI consistency on top of M2 | `timing/signals.py` (m3_*), `timing/regime.py` (build_timing_regime_context) |
| **M4** | Factor dispersion penalty, turnover penalty, industry/risk-budget constraints in portfolio entry | `bottomup/factors.py`, `bottomup/portfolio.py`, `engine/strategy.py`, `config.yaml → factors.m4` |
| **M5** | Exit layering (`exit_taxonomy.py`), optional regime force-exit (`m5_regime_exit_enabled`); RiskMonitor aligned with backtest | `timing/exit_taxonomy.py`, `signals.py`, `engine/strategy.py`, `risk/monitor.py` |
| **M终** | Research/backtest/admission/daily_run script boundaries clear; major changes require regression interval + audit record | `scripts/daily_run.py`, `scripts/backtest.py` |

---

## Universal Audit (every diff)

- **Causal chain**: who writes config → who reads → who enforces → what breaks with wrong value. Cannot answer all 4 → do not merge.
- **asof**: All financial/announcement/index data used in signals must be `<= asof`. Prove it.
- **Performance/IO**: No unbounded per-stock network requests in full-universe loops; must cache.
- **Tests**: Changes to strategy core logic require running existing tests in `tests/`.

## M0 Artifact Contract

All files required in `data/backtest/<strategy>_<market>_<start>_<end>/`:

| File | Required columns/keys |
|------|-----------------------|
| `entry_candidates.csv` | `screen_date`, `factor_rank`, `symbol`, `factor_score`, `queued_for_buy` |
| `ranking.csv` | `screen_date`, `rank`, `symbol`, `score` |
| `exit_events.csv` | `decision_date`, `symbol`, `reason`, `event`, **`exit_layer`** |
| `exit_reason_summary.json` | `closed_trades_by_exit_reason`, `exit_events_by_reason`, **`closed_trades_by_exit_layer`**, **`exit_events_by_exit_layer`** |
| `metrics.json` | `metrics`, `admission_pass` |

CSV column renames = breaking change → update audit script + all consumers.

## Anti-patterns (one-veto in audit)

- New `config.yaml` field with no grep-able reader in code
- Using un-truncated financial/announcement dates in backtest decisions
- Per-stock network request in full-universe loop without cache key
- Changing `entry_signal_from_enriched` but forgetting `entry_signal` (or vice versa) without documentation

## Key Commands

```powershell
# Unit tests (M终)
powershell -File scripts/run_acceptance.ps1

# Short HS300 backtest (primary acceptance; fixed output dir, overwrites same interval)
python scripts/backtest.py --start 2026-01-01 --end 2026-02-28 --refresh-days 999

# M0 artifact audit (no run_id subdir)
python scripts/audit_m0_outputs.py data/backtest/<strategy>_<market>_<start>_<end>
```

## Config Quick-Reference

| Section | Purpose |
|---------|---------|
| `strategy.timing` | M2 (`m2_*`) + M3 (`m3_*`) + M5 (`m5_regime_exit_enabled`) via `timing_config_from_yaml_node` |
| `factors.m4` | M4: dispersion/turnover penalty + industry/risk-budget via `m4_config_from_yaml` |
| `markets.*.universe` | `hs300` (A-share) / `hs100` (HK HSCHK100) |
| `backtest.benchmark_symbol` | A-share benchmark; HK prefers `markets.<market>.benchmark` |

## Agent Workflow (apply each session)

1. Map user request → M-node
2. Open relevant module(s) + `config.yaml` before changing
3. After change: run `run_acceptance.ps1` (pytest) + short backtest + `audit_m0_outputs.py`
4. Report: which M-node touched, acceptance commands used, output dir

**Why:** Skill was authored in `.cursor/skills/quant-system-milestones/` to enforce consistent audit across all contributors. Same standards apply in Claude Code.
**How to apply:** At start of any coding session in this repo, recall this milestone map. Before merging any change, run through the universal audit checklist and the node-specific checklist for the M touched.
