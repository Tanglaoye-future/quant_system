#!/usr/bin/env python3
"""
今日吃货期扫描（生产用）.

扫描全 universe，输出当日吃货期评分 TOP N 候选股票.

用法:
  python scripts/scan_today.py
  python scripts/scan_today.py --top 20 --min-score 55
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path


import yaml
import pandas as pd

from quant_system.strategies.zhuang.data.loader import ZhuangDataLoader
from quant_system.strategies.zhuang.signals.accumulation import accumulation_score_detail
from quant_system.strategies.zhuang.signals.entry import check_entry_signal

_REPORT_DATA = Path(__file__).resolve().parents[2] / "report" / "data"


def parse_args():
    p = argparse.ArgumentParser(description="今日吃货期候选扫描")
    p.add_argument("--config", default="config/zhuang.yaml")
    p.add_argument("--date", default=date.today().strftime("%Y-%m-%d"), help="扫描日期")
    p.add_argument("--top", type=int, default=15, help="显示 TOP N")
    p.add_argument("--min-score", type=float, default=50.0, help="最低评分")
    p.add_argument("--refresh-days", type=int, default=1)
    return p.parse_args()


def main():
    args = parse_args()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = Path(__file__).resolve().parents[2] / args.config
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    loader = ZhuangDataLoader(config, refresh_days=args.refresh_days)
    universe = loader.get_universe(args.date)
    print(f"[scan] universe={len(universe)} codes, date={args.date}")

    acc_w = config.get("accumulation_weights", {}) or None
    threshold = float(config.get("strategy", {}).get("accumulation_score_entry", 55.0))

    results = []
    for i, code in enumerate(universe, 1):
        if i % 200 == 0:
            print(f"  [{i}/{len(universe)}]", flush=True)
        df = loader.get_daily(code, "2020-01-01", args.date)
        if len(df) < 40:
            continue
        detail = accumulation_score_detail(df, weights=acc_w)
        if detail["total"] >= args.min_score:
            results.append({"code": code, **detail})

    if not results:
        print(f"\n吃货期候选：0 只（universe 为空或无股票达到评分门槛）")
        return
    df_out = pd.DataFrame(results).sort_values("total", ascending=False)
    print(f"\n吃货期候选（score >= {args.min_score}，共 {len(df_out)} 只）")
    print(df_out.head(args.top).to_string(index=False))

    out_path = Path("data") / f"scan_{args.date}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(out_path, index=False)
    print(f"\n已保存 → {out_path}")

    # ── 输出报告 JSON ────────────────────────────────────────────────────────
    top15 = df_out.head(15).to_dict(orient="records")
    # 检查市场趋势（从 config 读取，实际判断在 backtest 引擎；这里输出静态布尔）
    market_trend_ok = None  # scan_today 不运行 backtest engine，设为 None 表示未知
    report_payload = {
        "date": args.date,
        "universe_size": len(universe),
        "candidates_count": len(df_out),
        "market_trend": market_trend_ok,
        "top_candidates": [
            {k: (float(v) if hasattr(v, "item") else v) for k, v in row.items()}
            for row in top15
        ],
    }
    _REPORT_DATA.mkdir(parents=True, exist_ok=True)
    (_REPORT_DATA / "zhuang.json").write_text(
        json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[report] zhuang.json → {_REPORT_DATA / 'zhuang.json'}")

    # 自动重建 HTML 报告
    from quant_system.report.builder import rebuild_html_report
    rebuild_html_report(args.date, open_browser=False)

    loader._logout()


if __name__ == "__main__":
    main()
