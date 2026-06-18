#!/usr/bin/env python3
"""手动平仓 CB 双低实盘持仓 (券商已成交后录入到 PG ledger).

调 PR11 close_cb_trade wrapper:
  1. journal.close_trade — 算 pnl/pnl_pct/hold_days + 写 equity-flavor exit_features
     (exit_type=OTHER for CB reasons, hold_days_bucket, max_dd, max_profit, asof)
  2. journal.update_exit_features 浅合并补 CB 特有字段:
     - cb_exit_type (CB taxonomy: SCORE_EXIT/STOP_LOSS/FORCE_REDEEM/REBALANCE/DELISTED)
     - pnl_yuan / exit_price / exit_reason_raw

使用场景:
  - 月度 rebalance (PR9 SELL 'out_of_top_band'/'dual_low_too_high'): PM 手动卖出 CB 后录入
  - 实时风控触发 (PR10 cb_break_stop_loss / cb_redeem_imminent): 紧急清仓后录入
  - 强赎执行 (强赎日到, 必须出场): exit_reason=force_redeem

用法:
  # 先查 open
  python scripts/admin/close_cb_trade.py --list-open

  # 单笔 close (dry-run 先看)
  python scripts/admin/close_cb_trade.py \\
      --trade-id 12 --exit-date 2026-08-01 --exit-price 125.0 \\
      --exit-reason score_over_180 --dry-run

  # 真写
  python scripts/admin/close_cb_trade.py --trade-id 12 \\
      --exit-date 2026-08-01 --exit-price 125.0 \\
      --exit-reason score_over_180

exit_reason 枚举 (CB taxonomy 映射, 见 cb_double_low/journal/exit_taxonomy.py):
  SCORE_EXIT:
    score_over_180         慢出场, score 越过 yaml exit_dual_low_threshold
    dual_low_too_high      同上, 同义词
  STOP_LOSS:
    stop_loss              债底击穿, close < 85
    stop_loss_close        同上, 同义词
  FORCE_REDEEM:
    redeem_announced       公司强赎公告, last_trading_date 内必须出场
    force_redeem           强赎执行
    cb_redeem_imminent     PR10 实时告警触发出场
  REBALANCE:
    out_of_top_band        月度 rank 漂移 (rank > n_entry*1.5)
    rebalance              月度换仓
  DELISTED:
    out_of_universe        被砍出 filter
    delisted               退市

注意:
  - exit_price 是券商真实净价成交 (不含应计利息)
  - CB 按张交易, pnl_yuan = (exit - entry) × entry_size 直接是元数
  - 佣金/印花税不在 ledger 算, 以券商单据为准
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from quant_system.strategies.cb_double_low.journal import (  # noqa: E402
    CB_MARKET,
    CB_STRATEGY,
    Journal,
    close_cb_trade,
)
from quant_system.strategies.cb_double_low.journal.exit_taxonomy import (  # noqa: E402
    cb_exit_layer_from_reason,
)


# exit_reason 枚举 (CLI choices 严控, 防 PM 拼错 SCORE_EXIT/STOP_LOSS 等)
VALID_EXIT_REASONS = (
    "score_over_180", "dual_low_too_high",
    "stop_loss", "stop_loss_close",
    "redeem_announced", "force_redeem", "cb_redeem_imminent",
    "out_of_top_band", "rebalance",
    "out_of_universe", "delisted",
    "manual",  # 兜底 → OTHER
)


def parse_args():
    p = argparse.ArgumentParser(
        description="手动平仓 CB 双低实盘持仓到 journal_trades",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--trade-id", type=int,
                   help="journal_trades.id (用 --list-open 查)")
    p.add_argument("--exit-date", help="平仓日 YYYY-MM-DD")
    p.add_argument("--exit-price", type=float,
                   help="券商真实净价成交 (元, 如 125.0)")
    p.add_argument("--exit-reason", choices=VALID_EXIT_REASONS,
                   help="出场原因 (CB taxonomy 自动映射 cb_exit_type)")
    p.add_argument("--list-open", action="store_true",
                   help="只列 CB sleeve open trades, 不平仓")
    p.add_argument("--dry-run", action="store_true",
                   help="仅打印 pnl 预览不写库")
    return p.parse_args()


def list_open(j: Journal) -> None:
    opens = j.list_open(market=CB_MARKET, strategy=CB_STRATEGY)
    if not opens:
        print("[cb] 无 open trades (CB sleeve) ✅")
        return
    print(f"[cb] CB sleeve open trades: {len(opens)}")
    print(f"  {'id':>4} {'code':>8} {'entry_date':>12} {'entry_净价':>10} "
          f"{'张数':>6} {'入场 score':>10} {'rank':>6} {'name'}")
    for t in opens:
        ef = t.get("entry_features") or {}
        score = ef.get("dual_low_score")
        rank = ef.get("rank_at_entry")
        score_str = f"{score:>10.2f}" if score is not None else "       —"
        rank_str = f"{rank:>6}" if rank is not None else "     —"
        print(
            f"  {t['id']:>4} {t['symbol']:>8} {str(t['entry_date']):>12} "
            f"{t['entry_price']:>10.2f} {t['entry_size']:>6} "
            f"{score_str} {rank_str}  {(t.get('notes') or '')[:14]}"
        )


def close_one(
    j: Journal, trade_id: int, exit_date: str, exit_price: float,
    exit_reason: str, dry_run: bool,
) -> int:
    opens = {t["id"]: t for t in j.list_open(market=CB_MARKET, strategy=CB_STRATEGY)}
    t = opens.get(trade_id)
    if t is None:
        # 防御性: 也许 PM 传了 equity trade id, 提示
        all_opens = {t["id"]: t for t in j.list_open()}
        if trade_id in all_opens:
            other = all_opens[trade_id]
            print(f"[cb] trade_id={trade_id} 存在但不属 CB sleeve "
                  f"(market={other['market']}, strategy={other['strategy']}) — 拒绝平仓")
            return 3
        print(f"[cb] trade_id={trade_id} 不在 CB open 列表 — 可能已 closed 或 id 错")
        return 1

    layer = cb_exit_layer_from_reason(exit_reason)
    pnl_per_zhang = exit_price - t["entry_price"]
    pnl_total = pnl_per_zhang * t["entry_size"]
    pnl_pct = exit_price / t["entry_price"] - 1.0

    print(f"\n[cb] close preview:")
    print(f"  trade_id        = {t['id']} ({t['symbol']} / {(t.get('notes') or '')[:14]})")
    print(f"  entry           = {t['entry_price']:.2f} × {t['entry_size']} 张 on {t['entry_date']}")
    print(f"  exit            = {exit_price:.2f} on {exit_date}")
    print(f"  pnl/zhang       = {pnl_per_zhang:+.2f}  ({pnl_pct*100:+.2f}%)")
    print(f"  pnl_yuan        = ¥{pnl_total:+,.2f}")
    print(f"  exit_reason     = {exit_reason}")
    print(f"  cb_exit_type    = {layer}  (PR12 retrospective 分桶用)")
    print()

    if dry_run:
        print("[dry-run] 未写库")
        return 0

    close_cb_trade(
        journal=j,
        trade_id=trade_id,
        exit_date=exit_date,
        exit_price=exit_price,
        exit_reason=exit_reason,
    )
    print(f"[cb] ✅ trade {trade_id} closed (exit_features.cb_exit_type={layer} 已写)")
    print(f"  下次跑 daily_cb (PR9) {t['symbol']} 不再在 current_holdings")
    print(f"  intraday_risk_check (PR10) 不再评估此 code")
    print(f"  learn_from_trades (PR12) cb_double_low sleeve N 增 1")
    return 0


def main() -> int:
    args = parse_args()
    j = Journal()

    if args.list_open:
        list_open(j)
        return 0

    missing = [n for n, v in [
        ("--trade-id", args.trade_id),
        ("--exit-date", args.exit_date),
        ("--exit-price", args.exit_price),
        ("--exit-reason", args.exit_reason),
    ] if v is None]
    if missing:
        print(f"缺参数: {', '.join(missing)} (或用 --list-open 看 open trades)")
        return 2

    return close_one(
        j, args.trade_id, args.exit_date, args.exit_price,
        args.exit_reason, args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
