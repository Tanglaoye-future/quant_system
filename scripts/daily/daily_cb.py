#!/usr/bin/env python3
"""CB 双低 daily 入口 (PR7, 2026-06-16) — advisory only.

每日盘后跑一次, 输出:
1. 今日双低 top N entry candidates (CB sleeve 月度 rebalance 参考)
2. 已知强赎 / 距强赎 < 30 天的债 (force exit 候选)
3. 配比建议 (CB 5% 占 v7 总资产, 等权 1/N)

PR7 不接 journal / portfolio_history (留后续 PR), advisory 由 PM 人工执行.

用法:
  python scripts/daily/daily_cb.py                # 默认读 config/cb_double_low.yaml
  python scripts/daily/daily_cb.py --no-write     # 干跑, 不写 report/data
  python scripts/daily/daily_cb.py --top 30       # 输出 top 30 而非 yaml 默认
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

_REPORT_DATA = _REPO_ROOT / "report" / "data"
_DEFAULT_CONFIG = _REPO_ROOT / "config" / "cb_double_low.yaml"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from quant_system.strategies.cb_double_low.data.loader import CBDataLoader  # noqa: E402
from quant_system.strategies.cb_double_low.engine.strategy import (  # noqa: E402
    CBDoubleLowConfig,
    compute_target_portfolio,
)
from quant_system.strategies.cb_double_low.universe.filter import (  # noqa: E402
    UniverseFilterConfig,
    filter_universe,
)


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _build_config(cfg_yaml: dict) -> CBDoubleLowConfig:
    s = cfg_yaml.get("strategy", {})
    f = cfg_yaml.get("filter", {})
    filt = UniverseFilterConfig(
        min_close=float(f.get("min_close", 80.0)),
        min_scale_remain_yi=float(f.get("min_scale_remain_yi", 1.0)),
        min_years_to_maturity=float(f.get("min_years_to_maturity", 0.5)),
        min_rating=f.get("min_rating"),
        min_conversion_premium=s.get("min_conversion_premium"),
    )
    return CBDoubleLowConfig(
        n_entry=int(s.get("n_entry", 20)),
        n_hold_buffer=float(s.get("n_hold_buffer", 1.5)),
        exit_dual_low_threshold=float(s.get("exit_dual_low_threshold", 180.0)),
        stop_loss_close=float(s.get("stop_loss_close", 85.0)),
        weight_scheme=s.get("weight_scheme", "equal"),
        filter_config=filt,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="CB 双低 daily — advisory only")
    parser.add_argument("--config", default=str(_DEFAULT_CONFIG))
    parser.add_argument("--no-write", action="store_true",
                        help="不写 report/data/quant_cb.json")
    parser.add_argument("--top", type=int, default=None,
                        help="覆盖 yaml daily.output_top_n")
    parser.add_argument("--lookback-days", type=int, default=14,
                        help="panel 回溯天数找最新 asof")
    args = parser.parse_args()

    cfg_yaml = _load_yaml(Path(args.config))
    daily = cfg_yaml.get("daily", {})
    if not daily.get("enabled", True):
        print("[cb] daily.enabled=false → noop. 修改 config/cb_double_low.yaml 开启.")
        return 0

    cfg = _build_config(cfg_yaml)
    top_n = args.top or int(daily.get("output_top_n", 20))
    target_pct = float(cfg_yaml.get("portfolio", {}).get("target_pct", 0.05))
    source = cfg_yaml.get("portfolio", {}).get("source", "A_mom")

    cache_dir = Path(cfg_yaml.get("data", {}).get("cache_dir",
                                                  "./data/cache/cb_double_low"))
    if not cache_dir.is_absolute():
        cache_dir = _REPO_ROOT / cache_dir
    loader = CBDataLoader(cache_dir=cache_dir)

    today = date.today()
    print(f"\n{'='*70}")
    print(f"  CB 双低 daily — {today} (advisory only)")
    print(f"  config: {args.config}")
    print(f"  v7 配比: CB {target_pct*100:.0f}% (从 {source} 抽)")
    print(f"{'='*70}")

    # 1. universe
    print(f"\n[1/4] universe (asof={today})...")
    universe = loader.load_universe(asof=today)
    active = universe[universe["exit_status"] == "active"].copy()
    print(f"  total={len(universe)} active={len(active)}")

    # 2. panel: 拉最近 N 天找最新可用 asof
    start = today - timedelta(days=args.lookback_days)
    codes = active["bond_code"].tolist()
    print(f"\n[2/4] panel [{start} → {today}] cold {len(codes)} 只...")
    panel = loader.load_panel(start=start, end=today, codes=codes)
    if len(panel) == 0:
        print("⚠️  panel 全空, 退出 (cache 可能未 backfill).")
        loader.close()
        return 2

    panel_max_date = panel["date"].max().date()
    panel_today = panel[panel["date"] == panel["date"].max()].copy()
    print(f"  asof (panel 最新日): {panel_max_date}, 覆盖 {len(panel_today)}/{len(codes)}")

    # 3. redemption
    redemption = loader.load_redemption_events(asof=panel_max_date)

    # 4. compute target portfolio (空仓 advisory — PR8+ 接 journal 后填 current_holdings)
    print(f"\n[3/4] compute_target_portfolio (cold start)...")
    out = compute_target_portfolio(
        universe=active,
        panel_today=panel_today,
        redemption=redemption,
        current_holdings=[],
        asof=panel_max_date,
        config=cfg,
    )

    # ranked 详情: 复用 filter_universe (与 compute_target_portfolio 同 filter 链),
    # 避免直接 active.merge(panel) 绕过 filter 导致退市债/低 close/负溢价漏入 top.
    filtered_df, _ = filter_universe(
        active, panel_today, redemption, panel_max_date, cfg.filter_config,
    )
    filtered_df["dual_low_score"] = (
        filtered_df["close"] + filtered_df["conversion_premium_rate"]
    )
    # 加 bond_name (filter_universe 默认不带 name)
    name_map = dict(zip(active["bond_code"], active["bond_name"]))
    filtered_df["bond_name"] = filtered_df["bond_code"].map(name_map).fillna("")
    ranked = (
        filtered_df.dropna(subset=["dual_low_score"])
        .nsmallest(top_n, "dual_low_score")
        .reset_index(drop=True)
    )

    # 5. force exit candidates (advisory ⚠)
    redeem_active = set(
        redemption[
            (redemption["last_trading_date"].notna())
            & (redemption["last_trading_date"] <= pd.Timestamp(panel_max_date) + pd.Timedelta(days=30))
            & (redemption["last_trading_date"] >= pd.Timestamp(panel_max_date))
        ]["bond_code"].astype(str)
    )

    print(f"\n[4/4] 今日双低 top {top_n}:")
    print(f"  {'rank':<5} {'code':<8} {'name':<14} {'close':>8} {'prem%':>8} {'score':>8}")
    advisory_entries: list[dict] = []
    for i, row in ranked.iterrows():
        code = row["bond_code"]
        is_warn = code in redeem_active
        flag = " ⚠强赎临近" if is_warn else ""
        print(
            f"  {i+1:<5} {code:<8} {str(row['bond_name'])[:14]:<14} "
            f"{row['close']:>8.2f} {row['conversion_premium_rate']:>+8.2f} "
            f"{row['dual_low_score']:>8.2f}{flag}"
        )
        advisory_entries.append({
            "rank": int(i + 1),
            "bond_code": code,
            "bond_name": row["bond_name"],
            "close": float(row["close"]),
            "conversion_premium_rate": float(row["conversion_premium_rate"]),
            "dual_low_score": float(row["dual_low_score"]),
            "warn_redeem_near": bool(is_warn),
        })

    # 6. 配比建议
    weight_per = 1.0 / cfg.n_entry if cfg.n_entry > 0 else 0.0
    print(f"\n配比建议 (v7 组合内 CB sleeve {target_pct*100:.0f}%, 等权 1/{cfg.n_entry}):")
    print(f"  CB sleeve 内每只: {weight_per*100:.2f}% (= 总资产 {weight_per*target_pct*100:.3f}%)")
    print(f"  示例 100w 总资产: CB sleeve = {100*target_pct:.1f}w, 每只 ≈ {100*target_pct*weight_per*1000:.0f} 元")

    # 7. 写 report/data/quant_cb.json (前端 + 双写 placeholder)
    if not args.no_write:
        _REPORT_DATA.mkdir(parents=True, exist_ok=True)
        payload = {
            "date": str(today),
            "asof_panel": str(panel_max_date),
            "strategy": "cb_double_low",
            "market": "a_share",
            "advisory_only": bool(daily.get("advisory_only", True)),
            "config": {
                "n_entry": cfg.n_entry,
                "exit_dual_low_threshold": cfg.exit_dual_low_threshold,
                "stop_loss_close": cfg.stop_loss_close,
                "min_conversion_premium": cfg.filter_config.min_conversion_premium,
                "target_pct": target_pct,
                "source": source,
            },
            "universe": {
                "total": int(len(universe)),
                "active": int(len(active)),
                "panel_coverage": int(len(panel_today)),
                "panel_coverage_pct": (
                    float(len(panel_today) / len(codes)) if codes else 0.0
                ),
            },
            "filter_stats": dict(out["filter_stats"]),
            "entries_top": advisory_entries,
            "warn_redeem_near": sorted(redeem_active),
        }
        json_path = _REPORT_DATA / "quant_cb.json"
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\n[report] quant_cb.json → {json_path.relative_to(_REPO_ROOT)}")
    else:
        print("\n[--no-write] 跳过 report/data 写入")

    loader.close()
    print(f"\n{'='*70}\n  CB daily 完成 (advisory only — PM 人工参考是否月初 rebalance)\n{'='*70}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
