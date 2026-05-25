#!/usr/bin/env python3
"""
每日期权信号生成脚本.

运行方式：
  python scripts/daily/daily_options.py
  python scripts/daily/daily_options.py --paper          # 使用模拟账户 (port 4002)
  python scripts/daily/daily_options.py --no-ibkr        # 仅计算 IV + 动量，不连接 IBKR
  python scripts/daily/daily_options.py --market us_qqq  # 显式指定（多 market 时必需）

流程（每个 enabled market 各跑一遍）：
  1. 计算 vol_proxy → IVR（IV 环境）
  2. 检查 标的 动量信号
  3. 若信号 + IV 条件通过 → 连接 IBKR → 选取最优价差 → 打印信号卡
  4. 检查现有持仓 → 输出出场提醒
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path


from quant_system.config import load_config as load_split_config
from quant_system.strategies.options.iv.engine import IVMode, compute_ivr
from quant_system.strategies.options.signals.momentum import check_momentum
from quant_system.strategies.options.utils.display import print_monitor_alerts, print_no_signal, print_signal_card

_REPORT_DATA = Path(__file__).resolve().parents[2] / "report" / "data"


def _write_report_json(
    iv, momentum, signal_detail: dict | None, reason: str,
    market_name: str, underlying_label: str,
) -> None:
    """将期权系统今日结果写入 report/data/options[_<market>].json.

    单 market（us_qqq）保留写 options.json 维持前端报告 builder 兼容；
    多 market 时按 market 名分文件。
    """
    payload = {
        "date": date.today().strftime("%Y-%m-%d"),
        "market": market_name,
        "underlying": underlying_label,
        "ivr": round(float(iv.ivr), 2),
        "iv_mode": iv.mode.value,
        "signal_grade": iv.signal_grade,
        "qqq_price": round(float(momentum.price), 2),    # 字段名保留向下兼容
        "qqq_ma200": round(float(momentum.ma200), 2),
        "qqq_rsi": round(float(momentum.rsi), 1),
        "qqq_bullish": bool(momentum.bullish),
        "signal": signal_detail,
        "reason": reason,
    }
    _REPORT_DATA.mkdir(parents=True, exist_ok=True)
    fname = "options.json" if market_name == "us_qqq" else f"options_{market_name}.json"
    (_REPORT_DATA / fname).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[report] {fname} → {_REPORT_DATA / fname}")


def parse_args():
    p = argparse.ArgumentParser(description="期权每日信号")
    p.add_argument("--config", default="config/options.yaml")
    p.add_argument("--market", default=None,
                   help="指定要跑的 market（如 us_qqq / hk_hsi）；不指定则跑所有 enabled market")
    p.add_argument("--paper", action="store_true", help="使用模拟账户 (port 4002)")
    p.add_argument("--no-ibkr", action="store_true", help="跳过 IBKR 连接，仅输出 IV/动量")
    p.add_argument("--monitor-only", action="store_true", help="仅检查持仓，不生成新信号")
    return p.parse_args()


def load_config(path: str) -> dict:
    cfg_path = Path(path)
    if not cfg_path.is_absolute():
        cfg_path = Path(__file__).resolve().parents[2] / path
    return load_split_config(cfg_path).raw


def _select_markets(cfg: dict, market_arg: str | None) -> list[tuple[str, dict]]:
    """从装配后的 cfg.raw['markets'] 选出要跑的 (market_name, market_entry) 列表."""
    all_markets = cfg.get("markets") or {}
    if market_arg:
        if market_arg not in all_markets:
            raise SystemExit(f"未知 market: {market_arg}（可选: {list(all_markets.keys())}）")
        return [(market_arg, all_markets[market_arg])]
    enabled = [(m, e) for m, e in all_markets.items() if e.get("enabled", True)]
    if not enabled:
        raise SystemExit("没有 enabled 的 market 部署")
    return enabled


def _run_one_market(
    market_name: str,
    market_entry: dict,
    acct_cfg: dict,
    broker_cfg: dict,
    cache_dir: Path,
    args,
) -> None:
    """单个 market 一遍完整的 IV/动量/IBKR 流程."""
    underlying = market_entry["underlying"]
    vol_proxy = market_entry["vol_proxy_ticker"]
    exchange = market_entry.get("exchange", "SMART")
    currency = market_entry.get("currency", "USD")
    contract_mult = int(market_entry.get("contract_multiplier", 100))
    disp = market_entry.get("display") or {}
    underlying_label = disp.get("underlying_label", underlying)
    vol_label = disp.get("vol_label", vol_proxy.lstrip("^"))
    cs = disp.get("currency_symbol", "$")

    iv_cfg = market_entry["iv_engine"]
    entry_cfg = market_entry["entry"]
    exit_cfg = market_entry["exit"]
    mom_cfg = market_entry["momentum"]

    banner = f"[{market_name}] {underlying} ({exchange}/{currency})"
    print(f"\n{'='*60}\n  {banner}\n{'='*60}")

    # ── Step 1: IV 环境 ───────────────────────────────────────────────────────
    print(f"[1/4] 计算 IV Rank（{vol_label}）...", flush=True)
    iv = compute_ivr(
        vxn_ticker=vol_proxy,
        lookback_days=iv_cfg["ivr_lookback_days"],
        cache_dir=cache_dir,
        refresh_hours=4.0,
    )
    print(f"      {vol_label}={iv.vxn_current:.2f}  IVR={iv.ivr:.1f}  模式={iv.mode.value}  评级={iv.signal_grade}")

    # ── Step 2: 动量信号 ──────────────────────────────────────────────────────
    print(f"[2/4] 检查 {underlying_label} 动量...", flush=True)
    momentum = check_momentum(
        ticker=underlying,
        ma_period=mom_cfg["ma_period"],
        rsi_period=mom_cfg["rsi_period"],
        rsi_low=mom_cfg["rsi_entry_low"],
        rsi_high=mom_cfg["rsi_entry_high"],
        lookback_days=mom_cfg["lookback_days"],
    )
    print(f"      {underlying_label}={cs}{momentum.price:.2f}  MA200={cs}{momentum.ma200:.2f}  RSI={momentum.rsi:.1f}  "
          f"{'✅ 看涨' if momentum.bullish else '❌ 信号不足'}")

    # ── 信号评估 ──────────────────────────────────────────────────────────────
    entry_blocked = iv.signal_grade == "D" or not momentum.bullish
    if args.monitor_only:
        entry_blocked = True

    no_signal_reason = ""
    if iv.signal_grade == "D":
        no_signal_reason = f"IV过高(grade={iv.signal_grade}, IVR={iv.ivr:.1f})"
    elif not momentum.bullish:
        no_signal_reason = f"{underlying_label}动量不足(RSI={momentum.rsi:.1f}, MA200={cs}{momentum.ma200:.2f})"

    if entry_blocked and not args.monitor_only:
        print_no_signal(iv, momentum, underlying_label=underlying_label, currency_symbol=cs)
        _write_report_json(iv, momentum, None, no_signal_reason, market_name, underlying_label)
        return
    if not entry_blocked:
        if args.no_ibkr:
            print(f"\n[--no-ibkr] 跳过 IBKR 连接，仅输出分析结果")
            print_no_signal(iv, momentum, underlying_label=underlying_label, currency_symbol=cs)
            _write_report_json(iv, momentum, None, "--no-ibkr 模式，跳过 IBKR 连接",
                               market_name, underlying_label)
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
                account = client.get_account_info()
                print(f"      账户净值: {cs}{account.net_liquidation:,.0f}  现金: {cs}{account.cash_balance:,.0f}")

                print(f"[3/4] 获取 {underlying_label} 期权链...", flush=True)
                chain = client.get_option_chain(
                    symbol=underlying,
                    dte_min=entry_cfg["dte_min"],
                    dte_max=entry_cfg["dte_max"],
                    exchange=exchange,
                    currency=currency,
                )
                print(f"      找到 {len(chain)} 个到期日")

                if not chain:
                    print("❌ 未找到符合 DTE 条件的期权，退出。")
                    return

                print("[4/4] 搜索最优 Bull Call Spread...", flush=True)
                spread = find_best_spread(
                    client=client,
                    symbol=underlying,
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

                sizing = size_position(
                    net_debit_per_contract=spread.net_debit,
                    account_net_liq=account.net_liquidation,
                    risk_pct=acct_cfg["risk_per_trade_pct"],
                    max_contracts=acct_cfg["max_concurrent_positions"],
                )

                print_signal_card(
                    iv, momentum, spread, sizing, account.net_liquidation,
                    underlying_label=underlying_label,
                    vol_label=vol_label,
                    currency_symbol=cs,
                    contract_multiplier=contract_mult,
                )

                signal_detail = {
                    "type": "Bull Call Spread",
                    "structure": f"{underlying_label} 牛市看涨价差",
                    "buy_leg": f"买 Call K={spread.long_leg.strike} DTE={spread.long_leg.dte}",
                    "sell_leg": f"卖 Call K={spread.short_leg.strike} DTE={spread.short_leg.dte}",
                    "max_profit": f"{cs}{spread.max_profit * contract_mult * sizing['contracts']:.0f}",
                    "max_loss": f"-{cs}{spread.net_debit * contract_mult * sizing['contracts']:.0f}",
                    "contracts": sizing["contracts"],
                    "net_debit": round(float(spread.net_debit), 2),
                }
                _write_report_json(iv, momentum, signal_detail, "有效信号，已连接 IBKR",
                                   market_name, underlying_label)

                from quant_system.strategies.options.engine.monitor import check_positions
                print(f"[监控] 检查 {underlying_label} 期权持仓...", flush=True)
                alerts = check_positions(
                    client=client,
                    symbol=underlying,
                    profit_target_mult=exit_cfg["profit_target_mult"],
                    stop_loss_mult=exit_cfg["stop_loss_mult"],
                    dte_warning=exit_cfg["dte_warning"],
                )
                print_monitor_alerts(alerts)

        except Exception as e:
            print(f"\n❌ IBKR 连接失败: {e}")
            print("   请确认 IBKR Gateway 已运行，API 连接已在 Gateway 设置中启用。")
            print("   Gateway → Configuration → API → Settings → Enable ActiveX and Socket Clients")
            _write_report_json(iv, momentum, None, f"IBKR连接失败: {e}",
                               market_name, underlying_label)
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
                    client=client, symbol=underlying,
                    profit_target_mult=exit_cfg["profit_target_mult"],
                    stop_loss_mult=exit_cfg["stop_loss_mult"],
                    dte_warning=exit_cfg["dte_warning"],
                )
                print_monitor_alerts(alerts)
        except Exception as e:
            print(f"❌ IBKR 连接失败: {e}")
            sys.exit(1)


def main():
    args = parse_args()
    cfg = load_config(args.config)

    acct_cfg = cfg["account"]
    broker_cfg = cfg["broker"]
    cache_dir = Path(__file__).resolve().parents[2] / "data" / "cache"

    markets_to_run = _select_markets(cfg, args.market)
    for market_name, market_entry in markets_to_run:
        _run_one_market(market_name, market_entry, acct_cfg, broker_cfg, cache_dir, args)

    # 自动重建 HTML 报告（所有 market 跑完后一次）
    from quant_system.report.builder import rebuild_html_report
    rebuild_html_report(report_date=None, open_browser=False)


if __name__ == "__main__":
    main()
