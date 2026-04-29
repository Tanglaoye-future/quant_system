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
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_system.bottomup.factors import FactorWeights, score_universe
from quant_system.catalyst.monitor import CatalystMonitor
from quant_system.config import load_config
from quant_system.data.loader import DataLoader
from quant_system.journal.journal import Journal
from quant_system.risk.monitor import RiskMonitor
from quant_system.timing.signals import TimingConfig, scan_today_entries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", default="a_share", choices=["a_share", "hk_share"])
    parser.add_argument("--top", type=int, default=30,
                        help="从因子打分前 N 名里挑择时信号")
    parser.add_argument("--limit", type=int, default=0,
                        help="只扫 universe 前 N 只 (0=全部, 调试用)")
    parser.add_argument("--asof", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--no-write", action="store_true",
                        help="不写 snapshot / stop_loss 到 DB (干跑模式)")
    parser.add_argument("--all-stocks", action="store_true",
                        help="扫所有股票 (默认 True 只扫已缓存的, 加此参数会触发未缓存股票的在线 fetch)")
    args = parser.parse_args()

    cfg = load_config()
    market_cfg = cfg.get("markets", args.market)
    if not market_cfg or not market_cfg.get("enabled"):
        print(f"market {args.market} 在 config 里未启用")
        return

    loader = DataLoader(cfg.cache_dir, refresh_days=cfg.get("data", "refresh_days", default=1))
    j = Journal(cfg.journal_db_path)
    j.init_schema()
    tcfg = TimingConfig()

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
        print(f"  #{p.trade_id} {p.symbol}  浮盈 {p.pnl_pct*100:+.2f}%  "
              f"持有 {p.hold_days} 天  >> {p.reason}")
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

    hits = scan_today_entries(
        loader, args.market, universe["code"].tolist(), args.asof, tcfg,
        only_cached=not args.all_stocks,
    )
    # 排除已持仓
    hits = [h for h in hits if h["code"] not in open_codes]
    print(f"  共 {len(hits)} 只触发 (排除已持仓)", flush=True)

    # ---------------- Step 3: 对触发集合算因子, 按分排序 ----------------
    if hits:
        w_cfg = cfg.get("factors", "weights", default={}) or {}
        weights = FactorWeights(**w_cfg)
        hit_codes = [h["code"] for h in hits]
        try:
            ranked = score_universe(loader, args.market, hit_codes, args.asof, weights, verbose=False)
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


if __name__ == "__main__":
    main()
