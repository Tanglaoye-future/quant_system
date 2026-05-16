"""M0: audit script accepts a minimal compliant run_dir (no live backtest)."""
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


def _minimal_run_dir(tmp: Path) -> Path:
    d = tmp / "run_m0"
    d.mkdir(parents=True)
    (d / "metrics.json").write_text(
        json.dumps({"metrics": {}, "admission_pass": True}, ensure_ascii=False),
        encoding="utf-8",
    )
    (d / "universe_filter_stats_sample.json").write_text("{}", encoding="utf-8")
    pd.DataFrame([{"code": "000001"}]).to_csv(d / "universe_filtered_sample.csv", index=False)
    pd.DataFrame([{"date": "2026-01-02", "equity": 1.0}]).to_csv(d / "equity.csv", index=False)
    pd.DataFrame([{"date": "2026-01-02", "n_positions": 0}]).to_csv(d / "positions.csv", index=False)
    pd.DataFrame(
        [{
            "screen_date": "2026-01-02",
            "factor_rank": 1,
            "symbol": "000001",
            "factor_score": 1.0,
            "queued_for_buy": False,
        }],
    ).to_csv(d / "entry_candidates.csv", index=False)
    pd.DataFrame([{"screen_date": "2026-01-02", "rank": 1, "symbol": "000001", "score": 1.0}]).to_csv(
        d / "ranking.csv", index=False,
    )
    pd.DataFrame(
        [{
            "decision_date": "2026-01-02",
            "planned_exec_date": "2026-01-05",
            "symbol": "000001",
            "reason": "trailing_stop: x",
            "event": "exit_signal",
            "exit_layer": "STOP_TRAIL",
        }],
    ).to_csv(d / "exit_events.csv", index=False)
    summary = {
        "closed_trades_by_exit_reason": {"a": 1},
        "exit_events_by_reason": {"b": 1},
        "closed_trades_by_exit_layer": {"STOP_TRAIL": 1},
        "exit_events_by_exit_layer": {"STOP_TRAIL": 1},
        "n_exit_events": 1,
        "n_closed_trades": 1,
    }
    (d / "exit_reason_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return d


def test_audit_m0_passes_on_minimal_dir(tmp_path: Path) -> None:
    run_dir = _minimal_run_dir(tmp_path)
    repo = Path(__file__).resolve().parents[2]
    r = subprocess.run(
        [sys.executable, str(repo / "scripts" / "backtest" / "audit_m0_outputs.py"), str(run_dir)],
        capture_output=True,
        text=True,
        cwd=str(repo),
    )
    assert r.returncode == 0, r.stdout + r.stderr
