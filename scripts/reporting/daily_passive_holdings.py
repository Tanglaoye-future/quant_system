#!/usr/bin/env python3
"""
Daily passive holdings card — v7 配比里的被动持仓 (QQQ / GLD / BTC) spot snapshot.

driver: v7 实盘配比 (memory/cb_double_low_pr7_yaml_daily_2026-06.md):
       HK 50% / A_mom 15% / A_mr 0% / QQQ 10% / GLD 10% / BTC 10% / CB 5%
       QQQ/GLD/BTC 是被动 ETF / 资产, 不需要 daily 信号 — 只需"目标配比 + 当前价 + 今日涨跌"
       供 PM 复核仓位。

输出: report/data/passive_holdings.json
{
  "asof": "2026-06-16",
  "holdings": [
    {"symbol": "QQQ", "label": "纳指 100", "target_pct": 0.10,
     "spot": 744.0, "prev_close": 721.34, "change_pct": 0.0314, "as_of_date": "2026-06-15"},
    ...
  ]
}

用法:
  python scripts/reporting/daily_passive_holdings.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "report" / "data"

# v7 配比 — 见 memory/cb_double_low_pr7_yaml_daily_2026-06.md
HOLDINGS = [
    {"symbol": "QQQ", "label": "纳指 100", "target_pct": 0.10},
    {"symbol": "GLD", "label": "黄金", "target_pct": 0.10},
    {"symbol": "BTC-USD", "label": "比特币", "target_pct": 0.10},
]


def fetch_spot(symbol: str) -> dict | None:
    """近 7 日数据取最后 2 个非 nan 收盘, 算 1d 变动. 7d 窗口防 GLD 单日 nan."""
    try:
        hist = yf.Ticker(symbol).history(period="7d")
    except Exception as e:
        print(f"[{symbol}] fetch ERR: {type(e).__name__}: {e}", file=sys.stderr)
        return None
    hist = hist.dropna(subset=["Close"])
    if len(hist) < 2:
        print(f"[{symbol}] only {len(hist)} usable bars", file=sys.stderr)
        return None
    prev = float(hist["Close"].iloc[-2])
    cur = float(hist["Close"].iloc[-1])
    if prev <= 0:
        return None
    return {
        "spot": cur,
        "prev_close": prev,
        "change_pct": (cur - prev) / prev,
        "as_of_date": str(hist.index[-1].date()),
    }


def main():
    today = date.today().isoformat()
    out_holdings = []
    for h in HOLDINGS:
        spot = fetch_spot(h["symbol"])
        row = {**h}
        if spot is not None:
            row.update(spot)
        else:
            row.update({"spot": None, "prev_close": None, "change_pct": None, "as_of_date": None})
        out_holdings.append(row)
        if spot:
            print(f"  {h['symbol']}: {spot['spot']:.2f} ({spot['change_pct']:+.2%}) as_of={spot['as_of_date']}")
        else:
            print(f"  {h['symbol']}: FETCH FAILED")

    payload = {"asof": today, "holdings": out_holdings}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    json_path = DATA_DIR / "passive_holdings.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[report] passive_holdings.json → {json_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
