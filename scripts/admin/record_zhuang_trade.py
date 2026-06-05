#!/usr/bin/env python3
"""手动录入 zhuang 实盘持仓到 PG ledger（zhuang_trades）.

使用场景: zhuang 自动建仓被 market_trend_filter 拦截但用户人工买入了候选股,
需要把这些 trade 注册到 ledger, 后续 daily_zhuang Step 1 才能 enrich 出
safety margin (距止损/距止盈) + 组合层 alerts, dashboard 才会显示.

止损/止盈 公式与 daily_zhuang 自动建仓同口径:
  stop  = max(entry - atr_mult × ATR, entry × (1 - max_stop_pct))
  tp    = entry × (1 + take_profit_pct)
ATR 优先从 loader.compute_atr 实算; 缺数据用 entry × 3% 兜底.

用法:
  python scripts/admin/record_zhuang_trade.py \\
      --code 600584 --entry-date 2026-06-03 \\
      --entry-price 38.50 --entry-size 1000

  # 多笔 --dry-run 先验证再去 --no-dry-run:
  python scripts/admin/record_zhuang_trade.py --code 600584 --entry-date 2026-06-03 --entry-price 38.5 --entry-size 1000 --dry-run

可选:
  --atr 0.85          手动指定 ATR (跳过实算; 用券商确认的价格波动)
  --score 72.5        accumulation_score (留空填 None; 不影响出场)
  --notes "..."       备注
  --config            非默认 config 路径
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import yaml

from quant_system.strategies.zhuang.data.loader import ZhuangDataLoader
from quant_system.strategies.zhuang.journal.journal import TradeOpen, ZhuangJournal


def parse_args():
    p = argparse.ArgumentParser(description="手动录入 zhuang 实盘持仓到 ledger")
    p.add_argument("--code", required=True, help="股票代码 (6 位, 如 600584)")
    p.add_argument("--entry-date", required=True, help="入场日 YYYY-MM-DD")
    p.add_argument("--entry-price", required=True, type=float, help="入场价 (元)")
    p.add_argument("--entry-size", required=True, type=int, help="股数 (手数 ×100)")
    p.add_argument("--market", default="a_share", choices=["a_share", "hk_small"])
    p.add_argument("--atr", type=float, default=None,
                   help="手动 ATR (元); 缺省则从 daily 实算")
    p.add_argument("--score", type=float, default=None, help="accumulation_score (报表用)")
    p.add_argument("--phase", default="A")
    p.add_argument("--notes", default=None)
    p.add_argument("--config", default="config/zhuang.yaml")
    p.add_argument("--dry-run", action="store_true",
                   help="只算 stop/tp 不写 PG")
    return p.parse_args()


def main():
    args = parse_args()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = Path(__file__).resolve().parents[2] / args.config
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    strat = config.get("strategy", {}) or {}

    atr_mult = float(strat.get("stop_loss_atr_mult", 1.5))
    max_stop = float(strat.get("max_stop_loss_pct", 0.06))
    tp_pct = float(strat.get("take_profit_pct", 0.10))

    # ── ATR: 用户给了直接用; 否则从 loader 实算入场日前最近一段
    atr_val = args.atr
    if atr_val is None:
        loader = ZhuangDataLoader(config, refresh_days=1, market=args.market)
        start = (
            __import__("pandas").Timestamp(args.entry_date)
            - __import__("pandas").Timedelta(days=120)
        ).strftime("%Y-%m-%d")
        df = loader.get_daily(args.code, start, args.entry_date)
        if df is None or df.empty:
            print(f"[warn] {args.code} 拉不到 {start}..{args.entry_date} 行情, ATR 用 entry × 3% 兜底")
            atr_val = args.entry_price * 0.03
        else:
            atr_series = loader.compute_atr(df)
            atr_val = float(atr_series.iloc[-1]) if not atr_series.empty else args.entry_price * 0.03
            if np.isnan(atr_val):
                atr_val = args.entry_price * 0.03
        loader._logout()

    # ── stop / tp 公式与 daily_zhuang 自动建仓一致
    stop_px = max(args.entry_price - atr_mult * atr_val,
                  args.entry_price * (1.0 - max_stop))
    tp_px = args.entry_price * (1.0 + tp_pct)

    print()
    print("=" * 70)
    print(f"  手动录入 zhuang 持仓   asof = {args.entry_date}")
    print("=" * 70)
    print(f"  代码         : {args.code} ({args.market})")
    print(f"  入场日       : {args.entry_date}")
    print(f"  入场价       : {args.entry_price:.2f}")
    print(f"  股数         : {args.entry_size}")
    print(f"  成本         : {args.entry_size * args.entry_price:,.0f}")
    print(f"  ATR (入场)   : {atr_val:.4f}  (用户传入 {args.atr is not None})")
    print(f"  止损         : {stop_px:.2f}  (距入场 {(stop_px/args.entry_price-1)*100:+.2f}%)")
    print(f"  止盈         : {tp_px:.2f}  (距入场 {(tp_px/args.entry_price-1)*100:+.2f}%)")
    print(f"  score        : {args.score if args.score is not None else '—'}")
    if args.notes:
        print(f"  备注         : {args.notes}")
    print()

    if args.dry_run:
        print("[dry-run] 不写 PG; 去掉 --dry-run 才真插入")
        return

    journal = ZhuangJournal()
    journal.init_schema()
    # 检查重复 (同 code + 同 entry_date 已 open)
    for tr in journal.list_open():
        if tr["code"] == args.code and str(tr["entry_date"]) == args.entry_date:
            print(f"[error] {args.code} @ {args.entry_date} 已存在 open trade id={tr['id']}, 跳过")
            sys.exit(2)

    tid = journal.open_trade(TradeOpen(
        code=args.code, market=args.market,
        entry_date=args.entry_date,
        entry_price=args.entry_price, entry_size=args.entry_size,
        accumulation_score=args.score, phase=args.phase,
        atr_at_entry=atr_val,
        entry_reason="manual_entry",
        stop_loss_price=stop_px, take_profit_price=tp_px,
        notes=args.notes,
    ))
    print(f"[ok] 已写入 zhuang_trades id={tid}")
    print("  下次跑 daily_zhuang Step 1 会自动 enrich, dashboard 庄股卡显示距止损/止盈")


if __name__ == "__main__":
    main()
