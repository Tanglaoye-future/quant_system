"""
端到端验证 timing/signals.py:
  1. 扫几只股票的历史, 列出过去 1 年内所有入场触发日
  2. 对当前持仓的中联重科 (000157), 评估今天是否要卖 + 当前 trailing stop
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_system.config import load_config
from quant_system.data.loader import DataLoader
from quant_system.journal.journal import Journal
from quant_system.timing.signals import (
    TimingConfig, entry_signal, exit_signal, scan_entries, trailing_stop,
)


def main() -> None:
    cfg = load_config()
    hsi = cfg.get("data", "hang_seng_indexes", default=None) or {}
    loader = DataLoader(
        cfg.cache_dir,
        refresh_days=cfg.get("data", "refresh_days", default=1),
        price_adjust=cfg.get("data", "price_adjust", default="qfq"),
        hang_seng_indexes=hsi,
    )
    tcfg = TimingConfig()

    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")  # 多拉一段, 让 MA60 / RSI 有热身期

    # ============ Part 1: 历史入场信号扫描 ============
    print("=" * 70)
    print("Part 1: 过去 ~1 年内的入场信号触发日")
    print("=" * 70)

    test_codes = [
        ("000001", "平安银行"),
        ("000157", "中联重科"),
        ("000100", "TCL科技"),
        ("000063", "中兴通讯"),
    ]

    for code, name in test_codes:
        print(f"\n[{code}] {name}")
        try:
            px = loader.get_daily("a_share", code, start, today)
        except Exception as e:
            print(f"  数据加载失败: {e}")
            continue

        if len(px) < tcfg.ma_long + 5:
            print(f"  数据不足: 仅 {len(px)} 条")
            continue

        hits = scan_entries(px, tcfg)
        if hits.empty:
            print(f"  本期内无入场信号 (共 {len(px)} 个交易日)")
        else:
            print(f"  共 {len(hits)} 次入场信号:")
            for _, h in hits.iterrows():
                print(f"    {h['date']}  close={h['close']:.2f}  "
                      f"MA20={h['ma20']:.2f}  MA60={h['ma60']:.2f}  "
                      f"RSI={h['rsi']:.1f}  量比={h['vol_mult']:.2f}  "
                      f"stop={h['stop_loss']:.2f}  target={h['take_profit']:.2f}")

    # ============ Part 2: 对当前持仓做出场评估 ============
    print()
    print("=" * 70)
    print("Part 2: 当前持仓 (来自 journal) 的出场评估")
    print("=" * 70)

    j = Journal(cfg.journal_db_path)
    for trade in j.list_open():
        code = trade["symbol"]
        entry_date = trade["entry_date"]
        entry_price = trade["entry_price"]
        prev_stop = trade["stop_loss_price"]

        print(f"\n[#{trade['id']}] {code}  入场: {entry_date} @ {entry_price}")
        try:
            px = loader.get_daily(trade["market"], code, start, today)
        except Exception as e:
            print(f"  数据加载失败: {e}")
            continue

        if len(px) < tcfg.ma_long + 5:
            print(f"  数据不足")
            continue

        new_stop = trailing_stop(px, entry_price, prev_stop, tcfg)
        ex = exit_signal(px, entry_price, entry_date, new_stop, tcfg)
        cur_close = px["close"].iloc[-1]
        cur_date = px["date"].iloc[-1]

        print(f"  最新价: {cur_close:.2f} ({cur_date})")
        print(f"  当前止损 (trailing): {prev_stop:.2f} -> {new_stop:.2f}")
        print(f"  浮动盈亏: {(cur_close/entry_price-1)*100:+.2f}%")
        print(f"  出场信号: {'EXIT' if ex['signal'] else 'HOLD'}  ({ex['reason']})")


if __name__ == "__main__":
    main()
