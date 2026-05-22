#!/usr/bin/env python3
"""
每日期权信号生成脚本.

运行方式：
  python scripts/daily_signal.py
  python scripts/daily_signal.py --paper          # 使用模拟账户 (port 4002)
  python scripts/daily_signal.py --no-ibkr        # 仅计算 IV + 动量，不连接 IBKR

流程：
  1. 计算 VXN → IVR（IV 环境）
  2. 检查 QQQ 动量信号
  3. 若信号 + IV 条件通过 → 连接 IBKR → 选取最优价差 → 打印信号卡
  4. 检查现有持仓 → 输出出场提醒
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path


import yaml

from quant_system.strategies.options.iv.engine import IVMode, compute_ivr
from quant_system.strategies.options.signals.momentum import check_momentum
from quant_system.strategies.options.utils.display import print_monitor_alerts, print_no_signal, print_signal_card

_REPORT_DATA = Path(__file__).resolve().parents[2] / "report" / "data"


def _write_report_json(iv, momentum, signal_detail: dict | None, reason: str) -> None:
    """将期权系统今日结果写入 quant_system/report/data/options.json."""
    payload = {
        "date": date.today().strftime("%Y-%m-%d"),
        "ivr": round(float(iv.ivr), 2),
        "iv_mode": iv.mode.value,
        "signal_grade": iv.signal_grade,
        "qqq_price": round(float(momentum.price), 2),
        "qqq_ma200": round(float(momentum.ma200), 2),
        "qqq_rsi": round(float(momentum.rsi), 1),
        "qqq_bullish": bool(momentum.bullish),
        "signal": signal_detail,
        "reason": reason,
    }
    _REPORT_DATA.mkdir(parents=True, exist_ok=True)
    (_REPORT_DATA / "options.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[report] options.json → {_REPORT_DATA / 'options.json'}")


def parse_args():
    p = argparse.ArgumentParser(description="QQQ 期权每日信号")
    p.add_argument("--config", default="config/options.yaml")
    p.add_argument("--paper", action="store_true", help="使用模拟账户 (port 4002)")
    p.add_argument("--no-ibkr", action="store_true", help="跳过 IBKR 连接，仅输出 IV/动量")
    p.add_argument("--monitor-only", action="store_true", help="仅检查持仓，不生成新信号")
    return p.parse_args()


def load_config(path: str) -> dict:
    cfg_path = Path(path)
    if not cfg_path.is_absolute():
        cfg_path = Path(__file__).resolve().parents[2] / path
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    args = parse_args()
    cfg = load_config(args.config)

    strat = cfg["strategy"]
    iv_cfg = strat["iv_engine"]
    entry_cfg = strat["entry"]
    exit_cfg = strat["exit"]
    mom_cfg = strat["momentum"]
    acct_cfg = cfg["account"]
    broker_cfg = cfg["broker"]

    cache_dir = Path(__file__).resolve().parents[2] / "data" / "cache"

    # ── Step 1: IV 环境 ───────────────────────────────────────────────────────
    print("[1/4] 计算 IV Rank...", flush=True)
    iv = compute_ivr(
        vxn_ticker=iv_cfg["vxn_ticker"],
        lookback_days=iv_cfg["ivr_lookback_days"],
        cache_dir=cache_dir,
        refresh_hours=4.0,
    )
    print(f"      VXN={iv.vxn_current:.2f}  IVR={iv.ivr:.1f}  模式={iv.mode.value}  评级={iv.signal_grade}")

    # ── Step 2: 动量信号 ──────────────────────────────────────────────────────
    print("[2/4] 检查 QQQ 动量...", flush=True)
    momentum = check_momentum(
        ticker=strat["underlying"],
        ma_period=mom_cfg["ma_period"],
        rsi_period=mom_cfg["rsi_period"],
        rsi_low=mom_cfg["rsi_entry_low"],
        rsi_high=mom_cfg["rsi_entry_high"],
        lookback_days=mom_cfg["lookback_days"],
    )
    print(f"      QQQ=${momentum.price:.2f}  MA200=${momentum.ma200:.2f}  RSI={momentum.rsi:.1f}  "
          f"{'✅ 看涨' if momentum.bullish else '❌ 信号不足'}")

    # ── 信号评估 ──────────────────────────────────────────────────────────────
    entry_blocked = (
        iv.signal_grade == "D" or           # IV 过高
        not momentum.bullish                 # 动量不足
    )

    if args.monitor_only:
        entry_blocked = True

    # 决定不操作的原因文本
    no_signal_reason = ""
    if iv.signal_grade == "D":
        no_signal_reason = f"IV过高(grade={iv.signal_grade}, IVR={iv.ivr:.1f})"
    elif not momentum.bullish:
        no_signal_reason = f"QQQ动量不足(RSI={momentum.rsi:.1f}, MA200=${momentum.ma200:.2f})"

    if entry_blocked and not args.monitor_only:
        print_no_signal(iv, momentum)
        _write_report_json(iv, momentum, None, no_signal_reason)
        # 仍然检查持仓
    elif not entry_blocked:
        if args.no_ibkr:
            print("\n[--no-ibkr] 跳过 IBKR 连接，仅输出分析结果")
            print_no_signal(iv, momentum)
            _write_report_json(iv, momentum, None, "--no-ibkr 模式，跳过 IBKR 连接")
            return

        # ── Step 3: 连接 IBKR 获取期权链 ─────────────────────────────────────
        print("[3/4] 连接 IBKR Gateway...", flush=True)
        port = broker_cfg["paper_port"] if args.paper else broker_cfg["port"]

        from quant_system.strategies.options.broker.ibkr import IBKRClient
        from quant_system.strategies.options.signals.selector import find_best_spread, size_position

        try:
            with IBKRClient(
                host=broker_cfg["host"],
                port=port,
                client_id=broker_cfg["client_id"],
                timeout=broker_cfg["timeout_sec"],
            ) as client:

                # 账户信息
                account = client.get_account_info()
                print(f"      账户净值: ${account.net_liquidation:,.0f}  现金: ${account.cash_balance:,.0f}")

                # 期权链
                print("[3/4] 获取 QQQ 期权链...", flush=True)
                chain = client.get_option_chain(
                    symbol=strat["underlying"],
                    dte_min=entry_cfg["dte_min"],
                    dte_max=entry_cfg["dte_max"],
                )
                print(f"      找到 {len(chain)} 个到期日")

                if not chain:
                    print("❌ 未找到符合 DTE 条件的期权，退出。")
                    return

                # 选取最优价差
                print("[4/4] 搜索最优 Bull Call Spread...", flush=True)
                spread = find_best_spread(
                    client=client,
                    symbol=strat["underlying"],
                    chain=chain,
                    current_price=momentum.price,
                    long_delta_target=entry_cfg["long_leg_delta"],
                    short_delta_target=entry_cfg["short_leg_delta"],
                    min_spread_width_pct=entry_cfg["min_spread_width_pct"],
                    max_bid_ask_pct=entry_cfg["max_bid_ask_pct"],
                )

                if spread is None:
                    print("❌ 未找到满足条件的价差结构，可能是流动性不足。")
                    return

                # 仓位计算
                sizing = size_position(
                    net_debit_per_contract=spread.net_debit,
                    account_net_liq=account.net_liquidation,
                    risk_pct=acct_cfg["risk_per_trade_pct"],
                    max_contracts=acct_cfg["max_concurrent_positions"],
                )

                # 打印信号卡
                print_signal_card(iv, momentum, spread, sizing, account.net_liquidation)

                # 写报告 JSON
                signal_detail = {
                    "type": "Bull Call Spread",
                    "structure": f"{strat['underlying']} 牛市看涨价差",
                    "buy_leg": f"买 Call K={spread.long_strike} DTE={spread.dte}",
                    "sell_leg": f"卖 Call K={spread.short_strike} DTE={spread.dte}",
                    "max_profit": f"${(spread.short_strike - spread.long_strike - spread.net_debit) * 100 * sizing.contracts:.0f}",
                    "max_loss": f"-${spread.net_debit * 100 * sizing.contracts:.0f}",
                    "contracts": sizing.contracts,
                    "net_debit": round(float(spread.net_debit), 2),
                }
                _write_report_json(iv, momentum, signal_detail, "有效信号，已连接 IBKR")

                # ── Step 4: 持仓监控 ─────────────────────────────────────────
                from quant_system.strategies.options.engine.monitor import check_positions
                print("[监控] 检查现有期权持仓...", flush=True)
                alerts = check_positions(
                    client=client,
                    symbol=strat["underlying"],
                    profit_target_mult=exit_cfg["profit_target_mult"],
                    stop_loss_mult=exit_cfg["stop_loss_mult"],
                    dte_warning=exit_cfg["dte_warning"],
                )
                print_monitor_alerts(alerts)

        except Exception as e:
            print(f"\n❌ IBKR 连接失败: {e}")
            print("   请确认 IBKR Gateway 已运行，API 连接已在 Gateway 设置中启用。")
            print("   Gateway → Configuration → API → Settings → Enable ActiveX and Socket Clients")
            _write_report_json(iv, momentum, None, f"IBKR连接失败: {e}")
            sys.exit(1)
    else:
        # monitor-only 模式
        print("[monitor-only] 仅检查持仓...", flush=True)
        port = broker_cfg["paper_port"] if args.paper else broker_cfg["port"]
        from quant_system.strategies.options.broker.ibkr import IBKRClient
        from quant_system.strategies.options.engine.monitor import check_positions
        try:
            with IBKRClient(
                host=broker_cfg["host"], port=port,
                client_id=broker_cfg["client_id"], timeout=broker_cfg["timeout_sec"],
            ) as client:
                alerts = check_positions(
                    client=client, symbol=strat["underlying"],
                    profit_target_mult=exit_cfg["profit_target_mult"],
                    stop_loss_mult=exit_cfg["stop_loss_mult"],
                    dte_warning=exit_cfg["dte_warning"],
                )
                print_monitor_alerts(alerts)
        except Exception as e:
            print(f"❌ IBKR 连接失败: {e}")
            sys.exit(1)

    # 自动重建 HTML 报告
    from quant_system.report.builder import rebuild_html_report
    rebuild_html_report(report_date=None, open_browser=False)


if __name__ == "__main__":
    main()
