"""
量化日报: 主流水线.
每日盘后跑一次, 输出操作清单 (卖出 / 买入 / 持有).

流程:
  1. 风控: 对所有未平仓 trade 评估, 给出 EXIT/HOLD 建议
  2. 选股: 在 universe 内做因子打分, 取 top N
  3. 择时: 对 top N 跑 entry_signal, 找出今日触发的
  4. 输出操作清单

用法:
  python scripts/daily_run.py                       # 默认 HS300 全跑, 因子前 30 找入场
  python scripts/daily_run.py --top 20 --limit 50   # 只看 universe 前 50 (调试)
  python scripts/daily_run.py --no-write            # 干跑, 不写 DB
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_REPORT_DATA = Path(__file__).resolve().parents[2] / "report" / "data"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from quant_system.strategies.equity_factor.bottomup.factors import FactorWeights, score_universe
from quant_system.strategies.equity_factor.bottomup.portfolio import m4_config_from_yaml
from quant_system.strategies.equity_factor.catalyst.monitor import CatalystMonitor
from quant_system.config import load_config, resolve_strategy, resolve_strategy_params
from quant_system.market import load_market_context
from quant_system.strategies.equity_factor.data.loader import DataLoader
from quant_system.strategies.equity_factor.journal.journal import Journal
from quant_system.strategies.equity_factor.risk.monitor import RiskMonitor
from quant_system.strategies.equity_factor.timing.regime import MarketRegimeGate, build_timing_regime_context
from quant_system.strategies.equity_factor.timing.signals import scan_today_entries, timing_config_from_yaml_node


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "量化日报 (Phase 1b CLI 主索引翻转后).\n"
            "  新用法: --strategy equity_momentum   # 自动从 deployments 推导 market\n"
            "  旧用法: --strategy bottomup_timing --market a_share  # 仍兼容"
        ),
    )
    parser.add_argument("--strategy", default="equity_momentum",
                        help="策略名 (equity_momentum / equity_hk_momentum) 或工厂 kind (bottomup_timing / mean_reversion)")
    parser.add_argument("--market", default=None, choices=["a_share", "hk_share"],
                        help="可选；策略只部署到单一市场时自动推导")
    parser.add_argument("--top", type=int, default=30,
                        help="从因子打分前 N 名里挑择时信号")
    parser.add_argument("--limit", type=int, default=0,
                        help="只扫 universe 前 N 只 (0=全部, 调试用)")
    parser.add_argument("--asof", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--no-write", action="store_true",
                        help="不写 snapshot / stop_loss 到 DB (干跑模式)")
    parser.add_argument("--all-stocks", action="store_true",
                        help="扫所有股票 (默认 True 只扫已缓存的, 加此参数会触发未缓存股票的在线 fetch)")
    parser.add_argument("--capital", type=float, default=1_000_000,
                        help="总资金 (用于计算仓位大小), 默认 100 万")
    parser.add_argument("--dry-run", action="store_true",
                        help="干跑模式: 不实际录入开仓, 仅显示信号")
    args = parser.parse_args()

    cfg = load_config()

    # Phase 1b: --strategy 主索引解析
    resolved_market, kind, strategy_name = resolve_strategy(cfg, args.strategy, args.market)
    args.market = resolved_market
    args.kind = kind
    args.strategy_name = strategy_name

    # Phase 1-B: 优先按 (strategy_name, market) 精确 lookup，回退到 markets[market]
    _deps = cfg.get("deployments") or {}
    market_cfg = ((_deps.get(args.strategy_name) or {}).get(args.market)
                  if args.strategy_name else None) or cfg.get("markets", args.market)
    if not market_cfg or not market_cfg.get("enabled"):
        print(f"strategy {args.strategy_name} @ market {args.market} 在 config 里未启用")
        return

    hsi = cfg.get("data", "hang_seng_indexes", default=None) or {}
    us_mkt = cfg.get("data", "us_market", default=None) or {}
    loader = DataLoader(
        cfg.cache_dir,
        refresh_days=cfg.get("data", "refresh_days", default=1),
        price_adjust=cfg.get("data", "price_adjust", default="qfq"),
        hang_seng_indexes=hsi,
        us_market=us_mkt,
        us_universe=market_cfg.get("universe"),   # 影响 us_share 多 universe 路径
    )
    j = Journal(cfg.journal_db_path)
    j.init_schema()
    # Phase 1b: 与 backtest.py 共用 resolve_strategy_params, 修复 daily_equity 漏 merge markets.<m>.timing 的回归
    # Phase 1-B: 传 strategy_name 支持一市多策略
    _params = resolve_strategy_params(cfg, args.market, strategy_name=args.strategy_name)
    tcfg = timing_config_from_yaml_node(_params["timing"])
    bt_cfg = cfg.get("backtest") or {}
    bench = _params["benchmark"]

    print()
    print("=" * 78)
    print(f"  量化日报   asof = {args.asof}   market = {args.market}")
    print("=" * 78)

    # ---------------- Step 1: 风控 ----------------
    monitor = RiskMonitor(loader=loader, journal=j, timing_cfg=tcfg)
    positions, port = monitor.daily_check(asof=args.asof, write_snapshots=not args.no_write)

    catalyst = CatalystMonitor(cache_dir=cfg.cache_dir,
                               refresh_days=cfg.get("data", "refresh_days", default=1))

    exits = [p for p in positions if p.action == "EXIT"]
    holds = [p for p in positions if p.action == "HOLD"]

    print()
    print(f"【今日卖出建议】 ({len(exits)} 笔)")
    if not exits:
        print("  无")
    for p in exits:
        cat = catalyst.summarize(p.symbol, asof=args.asof)
        layer = f" [{p.exit_layer}]" if getattr(p, "exit_layer", "") else ""
        print(f"  #{p.trade_id} {p.symbol}  浮盈 {p.pnl_pct*100:+.2f}%  "
              f"持有 {p.hold_days} 天  >> {p.reason}{layer}")
        if cat.to_label() != "-":
            print(f"      催化剂: {cat.to_label()}")

    print()
    print(f"【持有维持】 ({len(holds)} 笔)")
    if not holds:
        print("  无")
    for p in holds:
        prev = f"{p.prev_stop:.2f}" if p.prev_stop is not None else "(无)"
        delta = " ↑" if (p.prev_stop is not None and p.new_stop > p.prev_stop) else ""
        cat = catalyst.summarize(p.symbol, asof=args.asof)
        print(f"  #{p.trade_id} {p.symbol}  浮盈 {p.pnl_pct*100:+.2f}%  "
              f"止损 {prev}→{p.new_stop:.2f}{delta}  持有 {p.hold_days} 天")
        if cat.to_label() != "-":
            flag = "⚠ 利空" if cat.is_negative() else ("✓ 利好" if cat.is_positive() else "")
            print(f"      催化剂: {cat.to_label()}  {flag}")

    # ---------------- Step 2: 全市场扫 entry signal ----------------
    print()
    print(f"【今日买入候选】 (全市场扫 entry signal -> 因子排序)")

    universe = loader.get_universe(args.market, market_cfg["universe"])
    if args.limit > 0:
        universe = universe.head(args.limit)
    print(f"  universe = {market_cfg['universe']}, 扫 {len(universe)} 只 entry signal ...", flush=True)

    open_codes = {t["symbol"] for t in j.list_open()}
    name_map = dict(zip(universe["code"], universe["name"]))

    regime_ctx = None
    # Phase 2b: 由 tcfg 字段驱动（hk_share 策略默认未开这两个字段，不会进；
    # 真要在 hk 上启用，是配置层的事，scripts 不该硬限市场）
    if tcfg.m3_regime_rsi_band or tcfg.m3_reg_vol_tighten_hi:
        regime_ctx = build_timing_regime_context(
            loader,
            str(bench),
            args.asof,
            tcfg.m2_regime_ma_days,
            atr_period=tcfg.atr_period,
            atr_pct_median_window=tcfg.m3_reg_index_atr_pct_median_window,
        )

    if args.kind == "mean_reversion":
        # mean_reversion 子策略：直接调用 Strategy 类的 screen()，输出转 dict 格式
        from quant_system.strategies.equity_factor.engine.strategy import MeanReversionStrategy, MeanReversionConfig
        mr_node = (market_cfg.get("mean_reversion") or {}) if isinstance(market_cfg, dict) else {}
        mr_strat = MeanReversionStrategy(
            loader=loader, market=args.market,
            universe_codes=universe["code"].tolist(),
            cfg=MeanReversionConfig(**mr_node),
            market_ctx=load_market_context(cfg, args.market),
        )
        from datetime import date as _date
        asof_dt = datetime.strptime(args.asof, "%Y-%m-%d").date()
        signals = mr_strat.screen(asof_dt)
        hits = [{
            "code": s.symbol,
            "entry_price": s.entry_price,
            "stop_loss": s.stop_loss,
            "take_profit": s.take_profit if s.take_profit else s.entry_price * 1.10,
            "reasons": list(s.reasons.values()),
            "score": s.score,
        } for s in signals]
    elif tcfg.m2_regime_enabled:
        # Phase 2b: 由 tcfg.m2_regime_enabled 驱动；hk_share 策略也开了 m2_regime_enabled,
        # 现在终于会用上 M2 门保护（之前被 args.market == "a_share" 硬限误屏蔽）
        gate = MarketRegimeGate(loader, str(bench), tcfg.m2_regime_ma_days)
        ok, msg = gate.allows_long_entries(args.asof)
        print(f"  M2市况门: {msg}", flush=True)
        if not ok:
            hits = []
        else:
            hits = scan_today_entries(
                loader, args.market, universe["code"].tolist(), args.asof, tcfg,
                only_cached=not args.all_stocks,
                regime_ctx=regime_ctx,
            )
    else:
        hits = scan_today_entries(
            loader, args.market, universe["code"].tolist(), args.asof, tcfg,
            only_cached=not args.all_stocks,
            regime_ctx=regime_ctx,
        )
    # 排除已持仓
    hits = [h for h in hits if h["code"] not in open_codes]
    print(f"  共 {len(hits)} 只触发 (排除已持仓)", flush=True)

    # ---------------- Step 3: 对触发集合算因子, 按分排序 ----------------
    if hits:
        # Phase 1b: 用合并后的 weights, 同步修复漏 merge markets.<m>.factors.weights 的回归
        weights = FactorWeights(**_params["weights"])
        m4_cfg = m4_config_from_yaml(_params["m4"])
        m4_for_score = (
            m4_cfg if float(m4_cfg.m4_factor_dispersion_lambda) > 0 else None
        )
        hit_codes = [h["code"] for h in hits]
        try:
            ranked = score_universe(
                loader, args.market, hit_codes, args.asof, weights,
                verbose=False, m4_cfg=m4_for_score,
            )
            for h in hits:
                h["score"] = float(ranked.loc[h["code"], "score"]) if h["code"] in ranked.index else 0.0
                row = ranked.loc[h["code"]] if h["code"] in ranked.index else None
                h["pe_inv"] = float(row["pe_inverse"]) if row is not None else float("nan")
                h["roe"] = float(row["roe"]) if row is not None else float("nan")
                h["rev_g"] = float(row["revenue_growth"]) if row is not None else float("nan")
        except Exception as e:
            print(f"  (因子打分失败, 仅按 timing 输出: {e})")
            for h in hits:
                h["score"] = 0.0
                h["pe_inv"] = h["roe"] = h["rev_g"] = float("nan")
        hits.sort(key=lambda h: -h["score"])

    if not hits:
        print(f"  无")
    else:
        for c in hits[: args.top]:
            cat = catalyst.summarize(c["code"], asof=args.asof)
            name = name_map.get(c["code"], "?")
            risk_pct = (c["entry_price"] - c["stop_loss"]) / c["entry_price"] * 100
            rr = (c["take_profit"] - c["entry_price"]) / (c["entry_price"] - c["stop_loss"])
            print()
            print(f"    {c['code']} {name}  因子分 {c['score']:+.3f}  "
                  f"(PE^-1={c['pe_inv']:.3f}, ROE={c['roe']:.2f}, 营收{c['rev_g']:+.1f}%)")
            print(f"      入场 {c['entry_price']:.2f}  止损 {c['stop_loss']:.2f}  "
                  f"止盈 {c['take_profit']:.2f}  风险 {risk_pct:.1f}%  盈亏比 1:{rr:.1f}")
            for r in c["reasons"]:
                print(f"      · {r}")
            if cat.to_label() != "-":
                flag = "⚠利空" if cat.is_negative() else ("✓利好" if cat.is_positive() else "")
                print(f"      催化剂: {cat.to_label()}  {flag}")

    # ---------------- Step 3: 自动开仓 ----------------
    open_codes_set = {t["symbol"] for t in j.list_open()}
    max_positions = int(cfg.get("strategy", "position_max_count", default=6))
    max_single_pct = float(cfg.get("strategy", "single_position_pct_max", default=0.20))
    available_slots = max_positions - len(open_codes_set)

    new_trades = []
    if args.dry_run:
        print()
        print(f"【自动开仓】 (干跑模式，不实际录入)")
    elif args.kind == "mean_reversion":
        print()
        print(f"【自动开仓】 mean_reversion 策略暂不支持自动开仓，请手动处理")
    elif available_slots <= 0:
        print()
        print(f"【自动开仓】 仓位已满 ({len(open_codes_set)}/{max_positions})，跳过")
    elif not hits:
        pass  # 无信号，静默跳过
    else:
        from quant_system.strategies.equity_factor.journal.journal import TradeOpen
        for c in hits[:args.top]:
            if len(new_trades) >= available_slots:
                break
            code = c["code"]
            if code in open_codes_set:
                continue
            entry_size_lots = int(args.capital * max_single_pct / c["entry_price"] / 100)
            if entry_size_lots < 1:
                continue
            entry_size = entry_size_lots * 100
            reasons_str = " · ".join(c.get("reasons", []))
            t = TradeOpen(
                symbol=code,
                market=args.market,
                entry_date=args.asof,
                entry_price=c["entry_price"],
                entry_size=entry_size,
                entry_score=c.get("score", 0.0),
                reason_timing=reasons_str,
                stop_loss_price=c["stop_loss"],
                take_profit_price=c["take_profit"],
            )
            trade_id = j.open_trade(t)
            new_trades.append((code, trade_id, entry_size, c["entry_price"]))
            open_codes_set.add(code)

        if new_trades:
            print()
            print(f"【自动开仓】 ({len(new_trades)} 笔)")
            for code, tid, sz, ep in new_trades:
                name = name_map.get(code, "?")
                cost = sz * ep
                print(f"  #{tid} {code} {name}  {sz}股 @ {ep:.2f}  成本 {cost:,.0f}")
        else:
            print()
            print(f"【自动开仓】 无符合条件的新仓 (可用槽位 {available_slots})")

    # ---------------- 组合摘要 ----------------
    print()
    print("【组合摘要】")
    if port.n_positions == 0:
        print("  当前空仓")
    else:
        print(f"  持仓 {port.n_positions} 只 / 总成本 {port.cost_basis:.0f} / "
              f"总市值 {port.market_value:.0f} / 浮盈 {port.unrealized_pnl_pct*100:+.2f}%")
        print(f"  单只最大占比 {port.max_single_weight*100:.1f}%  "
              f"最差单只浮亏 {port.worst_drawdown_pct*100:+.2f}%  "
              f"EXIT 信号 {port.n_at_risk}/{port.n_positions}")
    print()

    # ---------------- 输出报告 JSON ----------------
    gate_ok = None
    gate_msg_str = ""
    if args.kind != "mean_reversion" and tcfg.m2_regime_enabled:
        # Phase 2b: 与 L183 elif 条件对齐，去掉冗余 market 硬比
        gate_ok = ok  # noqa: F821  (defined in the branch above)
        gate_msg_str = msg  # noqa: F821

    report_signals = []
    for c in hits[: args.top]:
        reasons_str = " · ".join(c.get("reasons", []))
        report_signals.append({
            "code": c["code"],
            "name": name_map.get(c["code"], ""),
            "score": round(float(c.get("score", 0)), 3),
            "entry_price": round(float(c.get("entry_price", 0)), 2),
            "stop_loss": round(float(c.get("stop_loss", 0)), 2),
            "take_profit": round(float(c.get("take_profit", 0)), 2),
            "reason": reasons_str,
            "suggested_action": "买入",
        })

    report_positions = []
    for p in positions:
        report_positions.append({
            "code": p.symbol,
            "name": name_map.get(p.symbol, ""),
            "entry_date": str(getattr(p, "entry_date", "")),
            "hold_days": getattr(p, "hold_days", 0),
            "pnl_pct": round(float(p.pnl_pct), 4) if hasattr(p, "pnl_pct") else None,
            "action": p.action,
        })

    report_payload = {
        "date": args.asof,
        "market": args.market,
        "strategy": args.strategy,
        "strategy_kind": args.kind,
        "strategy_name": args.strategy_name,
        "market_gate": gate_ok,
        "market_gate_msg": gate_msg_str,
        "benchmark_close": "—",
        "benchmark_ma60": "—",
        "signals": report_signals,
        "positions": report_positions,
    }
    _REPORT_DATA.mkdir(parents=True, exist_ok=True)
    # 按 market + kind 命名 JSON 文件，与 report builder / API 的硬编码引用兼容
    # （strategy_name 信息通过 payload 字段传递；后续如要把文件名改成 strategy_name 需同步更新 builder/routes）
    json_filename = f"quant_{args.market}_{args.kind}.json"
    (_REPORT_DATA / json_filename).write_text(
        json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[report] {json_filename} → {_REPORT_DATA / json_filename}")

    # 双写 Postgres（Phase 2，env QUANT_PG_DUALWRITE 控制，失败不影响 JSON 跑批）
    from quant_system.db.ingest import maybe_ingest_quant
    maybe_ingest_quant(report_payload)

    # 自动重建 HTML 报告
    from quant_system.report.builder import rebuild_html_report
    rebuild_html_report(args.asof, open_browser=False)


if __name__ == "__main__":
    main()
