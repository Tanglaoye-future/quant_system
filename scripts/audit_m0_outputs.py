"""
M0 诊断产物审计：检查回测输出目录下 CSV/JSON 是否存在、列是否齐全、JSON 可解析。

用法:
  python scripts/audit_m0_outputs.py <run_dir>
  python scripts/audit_m0_outputs.py data/backtest/bottomup_timing_a_share_2026-01-01_2026-02-28
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path, help="回测输出目录（如 data/backtest/<strategy>_<market>_<start>_<end>）")
    args = parser.parse_args()
    run_dir = args.run_dir
    if not run_dir.is_dir():
        print(f"FAIL: not a directory: {run_dir.resolve()}", file=sys.stderr)
        return 2

    # universe filter files are A-share only; HK backtest legitimately omits them
    import json as _json
    _metrics_path = run_dir / "metrics.json"
    _is_hk = False
    if _metrics_path.exists():
        try:
            _is_hk = _json.loads(_metrics_path.read_text(encoding="utf-8")).get("market") == "hk_share"
        except Exception:
            pass

    required = {
        "metrics.json": None,
        **({"universe_filter_stats_sample.json": None,
            "universe_filtered_sample.csv": ["code"]} if not _is_hk else {}),
        "equity.csv": None,
        "positions.csv": None,
        "entry_candidates.csv": [
            "screen_date", "factor_rank", "symbol", "factor_score",
            "queued_for_buy",
        ],
        "ranking.csv": ["screen_date", "rank", "symbol", "score"],
        "exit_events.csv": ["decision_date", "symbol", "reason", "event", "exit_layer"],
        "exit_reason_summary.json": None,
    }
    optional = {"trades.csv": ["symbol", "exit_reason"]}

    errors: list[str] = []

    def need_cols(csv_path: Path, cols: list[str]) -> None:
        import pandas as pd
        try:
            df = pd.read_csv(csv_path, nrows=0)
        except Exception:
            # Empty file (e.g. universe_filtered_sample on a non-trading start date) — warn, don't fail
            print(f"  WARN: {csv_path.name} is empty (non-trading start date?), skipping column check")
            return
        missing = [c for c in cols if c not in df.columns]
        if missing:
            errors.append(f"{csv_path.name}: missing columns {missing}")

    for name, cols in required.items():
        p = run_dir / name
        if not p.exists():
            errors.append(f"missing file: {name}")
            continue
        if name.endswith(".json"):
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(obj, (dict, list)):
                    errors.append(f"{name}: JSON root type invalid")
                elif name == "exit_reason_summary.json" and isinstance(obj, dict):
                    for k in (
                        "closed_trades_by_exit_reason",
                        "exit_events_by_reason",
                        "closed_trades_by_exit_layer",
                        "exit_events_by_exit_layer",
                    ):
                        if k not in obj:
                            errors.append(f"{name}: missing key {k!r}")
                        elif not isinstance(obj[k], dict):
                            errors.append(f"{name}: key {k!r} must be object")
            except Exception as e:
                errors.append(f"{name}: JSON parse error {e}")
        elif cols is not None:
            need_cols(p, cols)

    for name, cols in optional.items():
        p = run_dir / name
        if p.exists() and cols is not None:
            need_cols(p, cols)

    if errors:
        print("M0 audit FAIL:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"M0 audit PASS: {run_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
