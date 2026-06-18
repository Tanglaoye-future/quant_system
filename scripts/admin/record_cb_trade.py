#!/usr/bin/env python3
"""手动录入 CB 双低实盘持仓到 journal_trades (PR8 共享表 + PR11 entry_features).

使用场景: PM 月初/中途按 daily_cb advisory 在券商下单 CB, 需要把成交 trade
注册到 ledger, 后续:
  - daily_cb (PR9) Journal.list_open() 反查得到 current_holdings 算 BUY/SELL/HOLD diff
  - intraday_risk_check (PR10) 实时评估 close<85 + 强赎临近
  - learn_from_trades (PR12) 9 月 retrospective 拿 cb_double_low sleeve 真数据

字段映射:
  - market='cb_a' / strategy='cb_double_low' (PR8 命名空间)
  - entry_price = CB 净价 (券商成交价 without 应计利息)
  - entry_size  = 张数 (1 张 = 100 元面值; 10 张 = 1000 元仓位)
  - entry_features JSONB (PR11 build_cb_entry_features 全字段)
  - stop_loss_price 从 config/cb_double_low.yaml strategy.stop_loss_close (单源)
  - take_profit_price = None (CB 出场是 score/强赎, 不是固定 TP)

用法:
  # 单笔 (dry-run 先看效果)
  python scripts/admin/record_cb_trade.py \\
      --code 113008 --bond-name 电气转债 \\
      --entry-date 2026-07-02 --entry-price 108.50 --entry-size 10 \\
      --dual-low-score 128.42 --conversion-premium 19.92 --rank 3 \\
      --dry-run

  # 真写 (去 --dry-run)
  python scripts/admin/record_cb_trade.py --code 113008 ... (略)

  # 月初批量录 20 笔, 用 shell 循环或写 wrapper script:
  while read code name price size score prem rank; do
    python scripts/admin/record_cb_trade.py \\
        --code "$code" --bond-name "$name" --entry-date 2026-07-02 \\
        --entry-price "$price" --entry-size "$size" \\
        --dual-low-score "$score" --conversion-premium "$prem" --rank "$rank"
  done < 7_1_rebalance_list.txt

可选 entry_features 字段 (CB 立项时全部, retrospective 用):
  --scale-remain-yi 4.5   剩余规模 (亿)
  --rating AA              信用评级 (AAA/AA+/AA/AA-/A+)
  --years-to-maturity 3.2  剩余年限
  --pure-bond-premium 12.5 纯债溢价率 (%)
  --last-trading-date 2027-08-15  强赎最后交易日 (有公告时填)
  --notes "..."
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from quant_system.strategies.cb_double_low.journal import (  # noqa: E402
    CB_MARKET,
    CB_STRATEGY,
    Journal,
    build_cb_trade_open,
    list_open_cb_holdings,
)


_CB_CONFIG = Path(__file__).resolve().parents[2] / "config" / "cb_double_low.yaml"


def parse_args():
    p = argparse.ArgumentParser(
        description="手动录入 CB 双低实盘持仓到 journal_trades (PR8 共享表)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # 必填 (券商成交回单 + daily_cb advisory 直接抄)
    p.add_argument("--code", required=True, help="bond_code 6 位 (如 113008)")
    p.add_argument("--bond-name", default="", help="债券名 (如 电气转债)")
    p.add_argument("--entry-date", required=True, help="入场日 YYYY-MM-DD")
    p.add_argument("--entry-price", required=True, type=float,
                   help="入场净价 (元, 如 108.50)")
    p.add_argument("--entry-size", required=True, type=int,
                   help="张数 (10 张=1000元面值)")
    p.add_argument("--dual-low-score", required=True, type=float,
                   help="入场时 dual_low_score (close + 转股溢价率)")
    p.add_argument("--conversion-premium", required=True, type=float,
                   help="入场时转股溢价率 百分数 (如 19.92)")
    p.add_argument("--rank", required=True, type=int,
                   help="入场时 daily_cb ranked 排名 (从 1 起)")
    # 可选 entry_features (PR12 retrospective 分桶用)
    p.add_argument("--scale-remain-yi", type=float, default=None,
                   help="剩余规模 (亿)")
    p.add_argument("--rating", default=None,
                   help="信用评级 (AAA/AA+/AA/AA-/A+)")
    p.add_argument("--years-to-maturity", type=float, default=None,
                   help="剩余年限")
    p.add_argument("--pure-bond-premium", type=float, default=None,
                   help="纯债溢价率 百分数")
    p.add_argument("--last-trading-date", default=None,
                   help="强赎最后交易日 YYYY-MM-DD (有公告时填)")
    p.add_argument("--notes", default=None, help="备注")
    p.add_argument("--config", default=str(_CB_CONFIG),
                   help="CB yaml 路径 (读 stop_loss_close)")
    p.add_argument("--dry-run", action="store_true",
                   help="只打印不写 PG (推荐先 dry-run 确认)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    # stop_loss_close 单源 — config/cb_double_low.yaml (与 PR10 intraday 同源)
    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = Path(__file__).resolve().parents[2] / args.config
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    stop_loss_close = float(
        (cfg.get("strategy") or {}).get("stop_loss_close", 85.0)
    )

    bond_name = args.bond_name or args.notes or ""

    # build TradeOpen (复用 PR8 facade — 所有 CB 字段 → entry_features JSONB)
    trade_open = build_cb_trade_open(
        bond_code=args.code,
        bond_name=bond_name,
        entry_date=args.entry_date,
        entry_price=args.entry_price,
        entry_size=args.entry_size,
        dual_low_score=args.dual_low_score,
        rank=args.rank,
        conversion_premium_rate=args.conversion_premium,
        stop_loss_close=stop_loss_close,
        scale_remain_yi=args.scale_remain_yi,
        rating=args.rating,
        years_to_maturity=args.years_to_maturity,
        pure_bond_premium_rate=args.pure_bond_premium,
        last_trading_date=args.last_trading_date,
        notes=args.notes,
    )

    face_value = args.entry_size * 100.0   # CB 面值固定 100 元/张
    cost = args.entry_size * args.entry_price
    print()
    print("=" * 70)
    print(f"  手动录入 CB 持仓   asof = {args.entry_date}")
    print("=" * 70)
    print(f"  bond_code    : {args.code} ({bond_name or '—'})")
    print(f"  market       : {CB_MARKET} / strategy : {CB_STRATEGY}")
    print(f"  入场净价     : {args.entry_price:.2f}")
    print(f"  张数         : {args.entry_size}  (面值 {face_value:,.0f} 元 / 实付 {cost:,.2f} 元)")
    print(f"  dual_low_score: {args.dual_low_score:.2f}  rank={args.rank}")
    print(f"  转股溢价率   : {args.conversion_premium:+.2f}%")
    print(f"  止损线 (yaml): {stop_loss_close:.2f}  (close 击穿触发 cb_break_stop_loss)")
    if args.scale_remain_yi is not None:
        print(f"  剩余规模     : {args.scale_remain_yi:.2f} 亿")
    if args.rating is not None:
        print(f"  信用评级     : {args.rating}")
    if args.years_to_maturity is not None:
        print(f"  剩余年限     : {args.years_to_maturity:.2f}")
    if args.last_trading_date is not None:
        print(f"  ⚠ 强赎日期   : {args.last_trading_date}")
    if args.notes:
        print(f"  备注         : {args.notes}")
    print()
    print(f"  entry_features (JSONB):")
    for k, v in (trade_open.entry_features or {}).items():
        print(f"    {k:<28} = {v}")
    print()

    journal = Journal()

    # 重复防御 — 同 code 已 open
    existing = list_open_cb_holdings(journal)
    if args.code in existing:
        print(f"[error] {args.code} 已 open (CB sleeve). 先 close_cb_trade 再 record 新 entry.")
        return 2

    if args.dry_run:
        print("[dry-run] 不写 PG; 去掉 --dry-run 才真插入")
        return 0

    tid = journal.open_trade(trade_open)
    print(f"[ok] 已写入 journal_trades id={tid}")
    print(f"  下次跑 daily_cb (PR9) 反查 current_holdings 会看到 {args.code}")
    print(f"  intraday_risk_check (PR10) 每 15 min 评估 close<{stop_loss_close} + 强赎临近")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
