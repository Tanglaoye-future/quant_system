"""
zhuang 全维度参数 sweep — 6 类别 × 多变体，3y 快扫 → 8y 验证 → combo.

类别:
  B1: take_profit_pct (8% / 10% / 12% / 15%)
  B2: stop_loss_atr_mult (1.0 / 1.5 / 2.0)
  B3: max_stop_loss_pct (4% / 6% / 8%)
  B4: min_stop_distance_pct (0% / 3% / 5%)
  B5: momentum_stop_pct (3% / 5% / 7%)
  B6: score-tier sizing 阈值

Phase 1: 3y 快扫所有变体
Phase 2: 每类别 top-1 上 8y 验证
Phase 3: 正向改进合并 combo 确认

Resume: 检查 _sweep/ 下已有结果自动跳过.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from quant_system.strategies.zhuang.data.loader import ZhuangDataLoader
from quant_system.strategies.zhuang.engine.backtest import ZhuangBacktester

ROOT = Path(__file__).resolve().parent.parent.parent
SWEEP_DIR = ROOT / "data" / "backtest" / "_sweep"


def load_config() -> dict:
    with open(ROOT / "config" / "zhuang.yaml") as f:
        return yaml.safe_load(f)


def run_variant(
    cfg: dict, loader: ZhuangDataLoader, tag: str,
    start: str, end: str, universe: list, px_cache: dict, verbose: bool = False,
) -> dict | None:
    """Run single variant. Returns metrics dict or None if already done."""
    out_dir = SWEEP_DIR / tag
    metrics_path = out_dir / "metrics.json"
    if metrics_path.exists():
        try:
            with open(metrics_path) as f:
                m = json.load(f)
            if m.get("total_trades", 0) > 0:
                if verbose:
                    print(f"  [skip] {tag} — already done")
                return m
        except Exception:
            pass

    bt = ZhuangBacktester(cfg, loader)
    metrics = bt.run(
        start=start, end=end, universe=universe,
        verbose=verbose, px_cache=px_cache,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    clean = {}
    for k, v in metrics.items():
        clean[k] = v.item() if hasattr(v, "item") else v
    with open(metrics_path, "w") as f:
        json.dump(clean, f, indent=2)

    return metrics


def fmt_metrics(m: dict) -> str:
    sh = m.get("sharpe_ratio", 0)
    ret = m.get("total_return", 0)
    dd = m.get("max_drawdown", 0)
    wr = m.get("win_rate", 0)
    n = m.get("total_trades", 0)
    return f"Sharpe={sh:.4f}  Ret={ret*100:+.2f}%  DD={dd*100:.2f}%  WR={wr*100:.1f}%  N={n}"


def print_table(results: list[dict], title: str):
    print(f"\n{'='*110}")
    print(f"  {title}")
    print(f"{'='*110}")
    header = f"{'Tag':<40s} {'Sharpe':>7s} {'TotRet%':>8s} {'AnnRet%':>8s} {'DD%':>7s} {'WR%':>6s} {'N':>5s}"
    print(header)
    print("-" * 110)
    for r in results:
        m = r["metrics"]
        tag = r["tag"][:40]
        sh = m.get("sharpe_ratio", 0)
        ret = m.get("total_return", 0)
        ann = m.get("annualized_return", 0)
        dd = m.get("max_drawdown", 0)
        wr = m.get("win_rate", 0)
        n = m.get("total_trades", 0)
        print(f"{tag:<40s} {sh:7.4f} {ret*100:+8.2f}% {ann*100:+8.2f}% {dd*100:7.2f}% {wr*100:6.1f}% {n:5d}")


# ── Variant definitions ─────────────────────────────────────────────────────

def make_variants(base_cfg: dict) -> list[dict]:
    """Return list of {tag, category, overrides}. Category '' = baseline."""
    variants = []

    # Baseline
    variants.append({"tag": "B0_baseline", "category": "", "overrides": {}})

    # B1: Take-Profit
    for tp in [0.08, 0.10, 0.12, 0.15]:
        if tp == 0.10:
            continue  # baseline already has 10%
        variants.append({
            "tag": f"B1_tp{tp*100:.0f}pct", "category": "B1_take_profit",
            "overrides": {"take_profit_pct": tp},
        })

    # B2: ATR Multiplier
    for atr in [1.0, 2.0]:
        variants.append({
            "tag": f"B2_atr{atr:.1f}", "category": "B2_atr_mult",
            "overrides": {"stop_loss_atr_mult": atr},
        })

    # B3: Max Stop-Loss
    for ms in [0.04, 0.08]:
        variants.append({
            "tag": f"B3_maxstop{ms*100:.0f}pct", "category": "B3_max_stop",
            "overrides": {"max_stop_loss_pct": ms},
        })

    # B4: Min Stop Distance
    for md in [0.0, 0.05]:
        variants.append({
            "tag": f"B4_mindist{md*100:.0f}pct", "category": "B4_min_dist",
            "overrides": {"min_stop_distance_pct": md},
        })

    # B5: Momentum Stop
    for mom in [0.03, 0.07]:
        variants.append({
            "tag": f"B5_mom{mom*100:.0f}pct", "category": "B5_mom_stop",
            "overrides": {"momentum_stop_pct": mom},
        })

    # B6: Score-Tiered Sizing
    tier_variants = [
        ("B6a_lower70", [70.0, 80.0], [0.03, 0.05, 0.08]),
        ("B6b_raise85", [75.0, 85.0], [0.03, 0.05, 0.08]),
        ("B6c_reduceMid", [75.0, 80.0], [0.02, 0.04, 0.08]),
        ("B6d_extreme", [70.0, 85.0], [0.02, 0.05, 0.10]),
    ]
    for tag, thresholds, pcts in tier_variants:
        variants.append({
            "tag": tag, "category": "B6_tiered_sizing",
            "overrides": {
                "tiered_score_thresholds": thresholds,
                "tiered_position_pcts": pcts,
            },
        })

    return variants


def apply_overrides(cfg: dict, overrides: dict) -> dict:
    c = copy.deepcopy(cfg)
    strat = c.setdefault("strategy", {})
    for k, v in overrides.items():
        strat[k] = v
    # For tiered lists, set directly to avoid yaml serialization issues
    if "tiered_score_thresholds" in overrides:
        strat["tiered_score_thresholds"] = overrides["tiered_score_thresholds"]
    if "tiered_position_pcts" in overrides:
        strat["tiered_position_pcts"] = overrides["tiered_position_pcts"]
    return c


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    base_cfg = load_config()
    variants = make_variants(base_cfg)

    print("=" * 60)
    print("  ZHANG FULL SWEEP — Phase 1: 3y fast scan")
    print(f"  {len(variants)} variants across 6 categories + baseline")
    print("=" * 60)

    # ── Phase 1: 3y sweep ──────────────────────────────────────────────
    start_3y = "2022-01-01"
    end_3y = "2024-12-31"

    print("\n[init] Preloading universe + px_cache (3y window)...")
    loader = ZhuangDataLoader(base_cfg, refresh_days=999, market="a_share")
    universe = loader.get_universe(start_3y)
    print(f"[init] universe size = {len(universe)}")

    px_cache: dict[str, pd.DataFrame] = {}
    for i, code in enumerate(universe, 1):
        df = loader.get_daily(code, start_3y, end_3y)
        if not df.empty:
            px_cache[code] = df
        if i % 500 == 0:
            print(f"  [init] loaded {i}/{len(universe)}")
    print(f"[init] px_cache ready: {len(px_cache)} stocks")

    phase1_results = []
    for v in variants:
        cfg = apply_overrides(base_cfg, v["overrides"])
        tag = v["tag"]
        is_baseline = (v["category"] == "")

        if is_baseline:
            print(f"\n{'─'*60}")
            print(f"  [{tag}] BASELINE (current config)")
            print(f"{'─'*60}")
        else:
            print(f"\n  [{tag}] {v.get('category','')}: {v['overrides']}")

        metrics = run_variant(cfg, loader, tag, start_3y, end_3y, universe, px_cache, verbose=True)
        if metrics:
            print(f"  => {fmt_metrics(metrics)}")
            phase1_results.append({"tag": tag, "category": v["category"], "overrides": v["overrides"], "metrics": metrics})

    # Print Phase 1 summary by category
    baseline = next((r for r in phase1_results if r["tag"] == "B0_baseline"), None)
    if baseline:
        print(f"\n{'='*60}")
        print(f"  BASELINE: {fmt_metrics(baseline['metrics'])}")
        print(f"{'='*60}")

    for cat in ["B1_take_profit", "B2_atr_mult", "B3_max_stop",
                "B4_min_dist", "B5_mom_stop", "B6_tiered_sizing"]:
        cat_results = [r for r in phase1_results if r["category"] == cat]
        if cat_results:
            print_table(cat_results, cat)

    # ── Phase 2: 8y verify ────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  PHASE 2: 8y verify (top-1 per category)")
    print(f"{'='*60}")

    # Select top-1 per category by 3y Sharpe
    phase2_variants = []
    for cat in ["B1_take_profit", "B2_atr_mult", "B3_max_stop",
                "B4_min_dist", "B5_mom_stop", "B6_tiered_sizing"]:
        cat_results = [r for r in phase1_results if r["category"] == cat]
        if cat_results:
            best = max(cat_results, key=lambda r: r["metrics"].get("sharpe_ratio", -999))
            # Only include if it beats baseline
            base_sharpe = baseline["metrics"]["sharpe_ratio"] if baseline else 0
            best_sharpe = best["metrics"].get("sharpe_ratio", 0)
            print(f"  {cat}: best={best['tag']} (3y Sharpe {best_sharpe:.4f} vs baseline {base_sharpe:.4f})")
            if best_sharpe > base_sharpe + 0.002:
                phase2_variants.append(best)
                print(f"    → PROMOTED to Phase 2")
            else:
                print(f"    → SKIPPED (no improvement)")

    start_8y = "2018-01-01"
    end_8y = "2026-06-09"

    if phase2_variants:
        print("\n[init] Preloading px_cache for 8y window...")
        loader8 = ZhuangDataLoader(base_cfg, refresh_days=999, market="a_share")
        universe8 = loader8.get_universe(start_8y)
        print(f"[init] universe size = {len(universe8)}")

        px_cache8: dict[str, pd.DataFrame] = {}
        for i, code in enumerate(universe8, 1):
            df = loader8.get_daily(code, start_8y, end_8y)
            if not df.empty:
                px_cache8[code] = df
            if i % 500 == 0:
                print(f"  [init] loaded {i}/{len(universe8)}")
        print(f"[init] px_cache8 ready: {len(px_cache8)} stocks")

        # Run baseline 8y first if not done
        bl_8y_tag = "B0_baseline_8y"
        bl_8y = run_variant(base_cfg, loader8, bl_8y_tag, start_8y, end_8y, universe8, px_cache8, verbose=True)
        if bl_8y:
            print(f"  BASELINE 8y: {fmt_metrics(bl_8y)}")

        phase2_results = []
        for v in phase2_variants:
            cfg = apply_overrides(base_cfg, v["overrides"])
            tag8 = v["tag"] + "_8y"
            print(f"\n  [{tag8}]")
            m = run_variant(cfg, loader8, tag8, start_8y, end_8y, universe8, px_cache8, verbose=True)
            if m:
                print(f"  => {fmt_metrics(m)}")
                phase2_results.append({**v, "tag_8y": tag8, "metrics_8y": m})

        print_table(
            [{"tag": "B0_baseline_8y", "metrics": bl_8y}] +
            [{"tag": r["tag_8y"], "metrics": r["metrics_8y"]} for r in phase2_results],
            "Phase 2: 8y Verification"
        )

        # ── Phase 3: Combo ────────────────────────────────────────────
        pos8 = [r for r in phase2_results
                if r["metrics_8y"].get("sharpe_ratio", 0) > bl_8y.get("sharpe_ratio", 0) + 0.002]
        if len(pos8) >= 2:
            print(f"\n{'='*60}")
            print(f"  PHASE 3: Combo sweep ({len(pos8)} positive dimensions)")
            print(f"{'='*60}")

            combo_overrides = {}
            combo_name_parts = ["combo"]
            for r in pos8:
                for k, v in r["overrides"].items():
                    combo_overrides[k] = v
                combo_name_parts.append(r["tag"])

            combo_tag = "_".join(combo_name_parts)

            # 3y combo
            cfg3 = apply_overrides(base_cfg, combo_overrides)
            m3 = run_variant(cfg3, loader, combo_tag + "_3y", start_3y, end_3y, universe, px_cache, verbose=True)
            if m3:
                print(f"  COMBO 3y: {fmt_metrics(m3)}")
                print(f"  BASELINE 3y: {fmt_metrics(baseline['metrics'])}")

            # 8y combo
            cfg8 = apply_overrides(base_cfg, combo_overrides)
            m8 = run_variant(cfg8, loader8, combo_tag + "_8y", start_8y, end_8y, universe8, px_cache8, verbose=True)
            if m8:
                print(f"  COMBO 8y: {fmt_metrics(m8)}")
                print(f"  BASELINE 8y: {fmt_metrics(bl_8y)}")
    else:
        print("\n  No variants promoted to Phase 2 — all categories flat or negative.")

    # ── Save final summary ─────────────────────────────────────────────
    summary = {
        "phase1": [{"tag": r["tag"], "category": r["category"],
                     "metrics": {k: v.item() if hasattr(v, "item") else v
                                 for k, v in r["metrics"].items()}}
                   for r in phase1_results],
    }
    out = SWEEP_DIR / "full_sweep_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary saved to {out}")


if __name__ == "__main__":
    main()
