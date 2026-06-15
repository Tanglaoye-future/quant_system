#!/usr/bin/env python3
"""手动平仓 zhuang 实盘持仓（券商已成交后录入到 PG ledger）。

使用场景：zhuang 子策略 2026-06-14 弃用（见 memory/zhuang_deprecated_2026-06.md），
用户在券商人工卖出 open zhuang 持仓后，把实际成交价回写到 ledger，把 trade 标 closed
+ 算 pnl + 触发 L4 exit_features 自动采集 (close_trade 内部已实现)。

与 scripts/admin/record_zhuang_trade.py 对称：那个负责开仓回填，本脚本负责平仓回填。

用法：
  # 单笔（建议）
  venv/bin/python scripts/admin/close_zhuang_manual.py \\
      --trade-id 4 --exit-date 2026-06-15 --exit-price 68.50 \\
      --exit-reason manual_dispose_zhuang_deprecated

  # 批量（一次性平 3 笔 — 弃用清仓场景）
  venv/bin/python scripts/admin/close_zhuang_manual.py --list-open
  # → 给你 trade-id + code 列表，确认后逐笔跑上面

  # 干跑（默认 --dry-run 关，加 --dry-run 仅打印）
  venv/bin/python scripts/admin/close_zhuang_manual.py --trade-id 4 \\
      --exit-date 2026-06-15 --exit-price 68.50 --dry-run

注意：
  - exit-price 是券商真实成交价（不是收盘价/参考价），佣金/印花税不在 ledger 算（M终
    层面 P&L 估算用，与券商对账请以券商单据为准）
  - exit-reason 建议用统一标签便于 L5 retrospective 筛选：
    * manual_dispose_zhuang_deprecated  (本次弃用清仓专用)
    * stop_loss / take_profit / time_stop (按真实出场原因)
"""
from __future__ import annotations

import argparse
import sys

from quant_system.strategies.zhuang.journal.journal import ZhuangJournal


def parse_args():
    p = argparse.ArgumentParser(description="手动平仓 zhuang 实盘持仓到 PG ledger")
    p.add_argument("--trade-id", type=int, help="zhuang_trades.id (用 --list-open 查)")
    p.add_argument("--exit-date", help="平仓日 YYYY-MM-DD")
    p.add_argument("--exit-price", type=float, help="券商真实成交价 (元/股)")
    p.add_argument("--exit-reason", default="manual_dispose_zhuang_deprecated",
                   help="出场原因标签 (默认: manual_dispose_zhuang_deprecated)")
    p.add_argument("--list-open", action="store_true", help="只列 open trades 不做平仓")
    p.add_argument("--dry-run", action="store_true", help="仅打印不写库")
    return p.parse_args()


def list_open(j: ZhuangJournal) -> None:
    opens = j.list_open()
    if not opens:
        print("[zhuang] 无 open trades — 已全部清仓 ✅")
        return
    print(f"[zhuang] open trades: {len(opens)}")
    print(f"{'id':>4} {'code':>8} {'entry_date':>12} {'entry_price':>12} {'size':>8} {'stop':>10} {'tp':>10} {'notes'}")
    for t in opens:
        print(
            f"{t['id']:>4} {t['code']:>8} {t['entry_date']:>12} "
            f"{t['entry_price']:>12.3f} {t['entry_size']:>8} "
            f"{(t['stop_loss_price'] or 0):>10.3f} {(t['take_profit_price'] or 0):>10.3f} "
            f"{t.get('notes') or ''}"
        )


def close_one(j: ZhuangJournal, trade_id: int, exit_date: str, exit_price: float,
              exit_reason: str, dry_run: bool) -> None:
    opens = {t["id"]: t for t in j.list_open()}
    t = opens.get(trade_id)
    if t is None:
        print(f"[zhuang] trade_id={trade_id} 不在 open 列表 — 可能已 closed 或不存在")
        sys.exit(1)

    pnl_per_share = exit_price - t["entry_price"]
    pnl_total = pnl_per_share * t["entry_size"]
    pnl_pct = exit_price / t["entry_price"] - 1.0
    print(f"[zhuang] close preview:")
    print(f"  trade_id    = {t['id']} ({t['code']})")
    print(f"  entry       = {t['entry_price']:.3f} × {t['entry_size']} on {t['entry_date']}")
    print(f"  exit        = {exit_price:.3f} on {exit_date}")
    print(f"  pnl/share   = {pnl_per_share:+.3f} ({pnl_pct*100:+.2f}%)")
    print(f"  pnl total   = ¥{pnl_total:+,.2f}")
    print(f"  exit_reason = {exit_reason}")

    if dry_run:
        print("[dry-run] 未写库")
        return

    j.close_trade(
        trade_id=trade_id,
        exit_date=exit_date,
        exit_price=exit_price,
        exit_reason=exit_reason,
    )
    print(f"[zhuang] ✅ trade {trade_id} closed in PG (exit_features 已 L4 内部采集)")


def main() -> None:
    args = parse_args()
    j = ZhuangJournal()

    if args.list_open:
        list_open(j)
        return

    missing = [n for n, v in [
        ("--trade-id", args.trade_id),
        ("--exit-date", args.exit_date),
        ("--exit-price", args.exit_price),
    ] if v is None]
    if missing:
        print(f"缺参数: {', '.join(missing)}（或用 --list-open）")
        sys.exit(2)

    close_one(j, args.trade_id, args.exit_date, args.exit_price,
              args.exit_reason, args.dry_run)


if __name__ == "__main__":
    main()
