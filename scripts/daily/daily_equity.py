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
from typing import Optional

import numpy as np
import pandas as pd

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
from quant_system.strategies.equity_factor.timing.signals import enrich, scan_today_entries, timing_config_from_yaml_node
from quant_system.intraday.watchlist import (
    Watchlist,
    WatchlistCandidate,
    dump_watchlist,
)


def _safe_float(value) -> Optional[float]:
    """NaN / None / Inf → None (JSONB 友好); 数值 → float."""
    try:
        f = float(value)
        if not np.isfinite(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _build_entry_features_for_code(
    loader, market: str, code: str, asof: str, strategy: str,
    tcfg, entry_score: Optional[float], history_start: str = "2024-01-01",
) -> Optional[dict]:
    """L2 of self_learning_pipeline — 重 enrich + snapshot today numeric features.

    Backstop #5 严守：零新计算，全部从 timing.enrich 已计算的列 + 20d high/low
    band 抽出（band 是 pandas .iloc 操作，不是新指标）。
    任何失败返回 None（fail-soft，不阻断 open_trade）。
    """
    try:
        px = loader.get_daily(market, code, history_start, asof)
        if px is None or len(px) < (tcfg.ma_long + 5):
            return None
        e = enrich(px, tcfg)
        today = e.iloc[-1]
        close = _safe_float(today.get("close"))
        vol_ma = _safe_float(today.get("vol_ma"))
        volume = _safe_float(today.get("volume"))
        ma_short = _safe_float(today.get("ma_short"))
        ma_long = _safe_float(today.get("ma_long"))
        vol_ratio = (volume / vol_ma) if (vol_ma and vol_ma > 0 and volume is not None) else None
        # 20d 区间位置 — 与 signals.py breakout 模式一致, 用前 20 日 close max
        # (不含今天) 算 dist; 价格位置用前 20 日 high/low band (不含今天).
        lb = 20
        dist_to_20d_high_pct = None
        price_position_20d = None
        if len(e) >= lb + 1:
            prev = e.iloc[-(lb + 1):-1]  # 前 20 日, 不含今天
            prev_close_high = _safe_float(pd.to_numeric(prev["close"], errors="coerce").max())
            prev_high_20 = _safe_float(pd.to_numeric(prev["high"], errors="coerce").max())
            prev_low_20 = _safe_float(pd.to_numeric(prev["low"], errors="coerce").min())
            if close is not None and prev_close_high and prev_close_high > 0:
                dist_to_20d_high_pct = (close - prev_close_high) / prev_close_high
            if close is not None and prev_high_20 is not None and prev_low_20 is not None and prev_high_20 > prev_low_20:
                price_position_20d = (close - prev_low_20) / (prev_high_20 - prev_low_20)
        return {
            "rsi": _safe_float(today.get("rsi")),
            "vol_ratio": _safe_float(vol_ratio),
            "ma_short": ma_short,
            "ma_long": ma_long,
            "ma_short_above_long": (ma_short is not None and ma_long is not None and ma_short > ma_long),
            "atr": _safe_float(today.get("atr")),
            "close": close,
            "dist_to_20d_high_pct": dist_to_20d_high_pct,
            "price_position_20d": price_position_20d,
            "strategy": strategy,
            "market": market,
            "asof": asof,
            "sector_sw1": None,  # L2 暂留 None；申万行业数据需 akshare 接入，留未来 PR
            "zscore_within_universe": _safe_float(entry_score),
        }
    except Exception:
        # fail-soft: 采集失败不阻断 open_trade (Backstop #5)
        return None


def _write_equity_watchlist(
    loader,
    market: str,
    strategy: str,
    asof: str,
    hits: list[dict],
    name_map: dict,
    top: int,
    repo_root: Path,
) -> Optional[Path]:
    """PR2: daily 跑完 (a_share + equity_factor) 后写 equity_watchlist.json,
    供 intraday breakout 告警 (pr2_intraday_watchlist_breakout.md).

    每只 candidate 拉 T 日 daily 末根 K 取 high; loader 失败 → 该只 reference_high=close.
    """
    if not hits:
        return None
    candidates: list[WatchlistCandidate] = []
    for c in hits[:top]:
        code = c["code"]
        ref_high = float(c.get("entry_price", 0.0))
        ref_close = float(c.get("entry_price", 0.0))
        try:
            px = loader.get_daily(market, code, "2026-01-01", asof)
            if px is not None and len(px) > 0:
                last = px.iloc[-1]
                ref_close = float(last["close"])
                ref_high = float(last["high"]) if "high" in px.columns else ref_close
        except Exception:
            pass
        candidates.append(WatchlistCandidate(
            symbol=code,
            name=name_map.get(code, ""),
            reference_high=ref_high,
            reference_close=ref_close,
            entry_price_suggested=float(c.get("entry_price", ref_close)),
            stop_loss_suggested=float(c["stop_loss"]) if c.get("stop_loss") else None,
            take_profit_suggested=float(c["take_profit"]) if c.get("take_profit") else None,
            factor_score=float(c.get("score", 0.0)),
            reasons=list(c.get("reasons", [])),
        ))
    wl = Watchlist(
        asof_date=asof,
        strategy=strategy,
        market=market,
        candidates=candidates,
    )
    path = repo_root / "data" / "intraday" / "equity_watchlist.json"
    dump_watchlist(wl, path)
    return path


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
    # 有效策略标识：mean_reversion 等 kind 式调用 strategy_name 为 None，回退到 args.strategy，
    # 否则风控的 strategy 过滤失效 → 又会评估到 momentum 的仓位（串台）。
    eff_strategy = args.strategy_name or args.strategy
    # 组合层风控（仅 alert，不自动平仓）；yaml `portfolio_risk:` 缺失或 enabled=false 时整段 noop
    from quant_system.strategies.equity_factor.risk.monitor import PortfolioRiskConfig
    pr_node = cfg.get("portfolio_risk") or {}
    portfolio_risk_cfg = PortfolioRiskConfig(
        enabled=bool(pr_node.get("enabled", False)),
        max_single_weight_pct=pr_node.get("max_single_weight_pct"),
        unrealized_pnl_floor_pct=pr_node.get("unrealized_pnl_floor_pct"),
        exit_signal_ratio_max=pr_node.get("exit_signal_ratio_max"),
    )
    monitor = RiskMonitor(loader=loader, journal=j, timing_cfg=tcfg,
                          market=args.market, strategy=eff_strategy,
                          portfolio_risk_cfg=portfolio_risk_cfg)
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
    # safety margin 阈值：距离 < 1% 算"贴线"，提示操盘人
    CRITICAL_MARGIN = 0.01
    n_critical = 0
    for p in holds:
        prev = f"{p.prev_stop:.2f}" if p.prev_stop is not None else "(无)"
        delta = " ↑" if (p.prev_stop is not None and p.new_stop > p.prev_stop) else ""
        cat = catalyst.summarize(p.symbol, asof=args.asof)
        # safety margin 段：把距离止损 / 距离 MA60 暴露给操盘人，避免组合层 +0.30% 假象掩盖单只贴线
        stop_seg = (
            f"距 {p.dist_to_stop_pct*100:+.2f}%"
            if p.dist_to_stop_pct is not None else "距 —"
        )
        ma_seg = (
            f"MA60 距 {p.dist_to_ma_long_pct*100:+.2f}%"
            if p.dist_to_ma_long_pct is not None else "MA60 距 —"
        )
        is_critical = (
            (p.dist_to_stop_pct is not None and p.dist_to_stop_pct < CRITICAL_MARGIN)
            or (p.dist_to_ma_long_pct is not None and p.dist_to_ma_long_pct < CRITICAL_MARGIN)
        )
        warn = " ⚠ 临界" if is_critical else ""
        if is_critical:
            n_critical += 1
        # 止盈视图：止盈价 + 距离百分比；不参与临界判定（接近止盈不是风险）
        tp_seg = (
            f"止盈 {p.take_profit:.2f} (距 {p.dist_to_target_pct*100:+.2f}%)"
            if (p.take_profit is not None and p.dist_to_target_pct is not None) else "止盈 —"
        )
        print(f"  #{p.trade_id} {p.symbol}  浮盈 {p.pnl_pct*100:+.2f}%  "
              f"止损 {prev}→{p.new_stop:.2f}{delta} ({stop_seg})  "
              f"{ma_seg}  {tp_seg}  持有 {p.hold_days} 天{warn}")
        if cat.to_label() != "-":
            flag = "⚠ 利空" if cat.is_negative() else ("✓ 利好" if cat.is_positive() else "")
            print(f"      催化剂: {cat.to_label()}  {flag}")
    if n_critical > 0 and holds:
        print(f"  ⚠ {n_critical}/{len(holds)} 只贴近触发线 (margin < {CRITICAL_MARGIN*100:.0f}%)，"
              "组合层均值可能掩盖单只风险")

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

    # ---------------- PR2: 写 intraday breakout watchlist ----------------
    # 仅 A 股 + 非 mean_reversion (mr 是 bottom-fish, 跟 breakout 反向);
    # dry-run 不写副作用文件; hits 已按 score 排序.
    if (
        not args.dry_run
        and not args.no_write
        and args.market == "a_share"
        and args.kind != "mean_reversion"
        and hits
    ):
        try:
            wl_path = _write_equity_watchlist(
                loader=loader,
                market=args.market,
                strategy=eff_strategy or args.strategy,
                asof=args.asof,
                hits=hits,
                name_map=name_map,
                top=args.top,
                repo_root=Path(__file__).resolve().parents[2],
            )
            if wl_path:
                print(f"  写 intraday watchlist: {wl_path.relative_to(Path.cwd()) if wl_path.is_relative_to(Path.cwd()) else wl_path}")
        except Exception as exc:
            print(f"  (写 watchlist 失败: {exc})")

    # ---------------- Step 3: 自动开仓 ----------------
    # sleeve 内隔离: A_mom / A_mr / HK_mom 各自独立 slot 池, 不互挤
    # 详 docs/specs/a_mr_auto_entry.md "list_open 隔离决策"
    open_codes_set = {
        t["symbol"]
        for t in j.list_open(market=args.market, strategy=eff_strategy)
    }
    max_positions = int(cfg.get("strategy", "position_max_count", default=6))
    max_single_pct = float(cfg.get("strategy", "single_position_pct_max", default=0.20))
    available_slots = max_positions - len(open_codes_set)

    new_trades = []
    if args.dry_run:
        print()
        print(f"【自动开仓】 (干跑模式，不实际录入)")
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
            # L2 of self_learning_pipeline: 采集结构化 entry features (fail-soft)
            entry_feats = _build_entry_features_for_code(
                loader, args.market, code, args.asof,
                eff_strategy or args.strategy, tcfg, c.get("score", 0.0),
            )
            # M3 of fix_hold_days_entry_bar_date: entry_date 用实际 K 线日 (周一跑
            # daily 时 baostock 当日 K 线未入库, args.asof 是未来日 → hold_days 负数 +
            # α benchmark 错位). 兜底回 args.asof.
            entry_date_actual = c.get("entry_bar_date") or args.asof
            t = TradeOpen(
                symbol=code,
                market=args.market,
                strategy=eff_strategy,
                entry_date=entry_date_actual,
                entry_price=c["entry_price"],
                entry_size=entry_size,
                entry_score=c.get("score", 0.0),
                reason_timing=reasons_str,
                stop_loss_price=c["stop_loss"],
                take_profit_price=c["take_profit"],
                entry_features=entry_feats,
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
    # 组合层 alerts —— 仅显示警告，决策仍走个股层
    for alert in port.alerts:
        print(f"  ⚠ 组合层告警: {alert}")
    print()

    # ---------------- 输出报告 JSON ----------------
    gate_ok = None
    gate_msg_str = ""
    if args.kind != "mean_reversion" and tcfg.m2_regime_enabled:
        # Phase 2b: 与 L183 elif 条件对齐，去掉冗余 market 硬比
        gate_ok = ok  # noqa: F821  (defined in the branch above)
        gate_msg_str = msg  # noqa: F821

    # 基准指数 close + MA（前端市况卡/矩阵展示用）。与择时门同窗口（m2_regime_ma_days）。
    bench_close_val: float | str = "—"
    bench_ma_val: float | str = "—"
    try:
        import pandas as _pd
        _ma_days = int(tcfg.m2_regime_ma_days or 60)
        _idx = loader.get_index_daily(str(bench))
        _idx = _idx[_idx["date"].astype(str).str[:10] <= args.asof]
        _c = _pd.to_numeric(_idx["close"], errors="coerce").dropna()
        if len(_c) >= _ma_days:
            bench_close_val = round(float(_c.iloc[-1]), 2)
            bench_ma_val = round(float(_c.rolling(_ma_days).mean().iloc[-1]), 2)
    except Exception:
        pass

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
            # safety margin 字段（前端 dashboard 列：距止损 / 距 MA60 / 距止盈）
            "current_price": round(float(p.current_price), 2) if getattr(p, "current_price", None) is not None else None,
            "stop_loss": round(float(p.new_stop), 2) if getattr(p, "new_stop", None) is not None else None,
            "ma_long": round(float(p.ma_long), 2) if getattr(p, "ma_long", None) is not None else None,
            "dist_to_stop_pct": round(float(p.dist_to_stop_pct), 4) if getattr(p, "dist_to_stop_pct", None) is not None else None,
            "dist_to_ma_long_pct": round(float(p.dist_to_ma_long_pct), 4) if getattr(p, "dist_to_ma_long_pct", None) is not None else None,
            "take_profit": round(float(p.take_profit), 2) if getattr(p, "take_profit", None) is not None else None,
            "dist_to_target_pct": round(float(p.dist_to_target_pct), 4) if getattr(p, "dist_to_target_pct", None) is not None else None,
        })

    # PR2: 组合层汇总 nested object（含 PR2 新增 peak_market_value / drawdown_from_peak_pct）
    portfolio_summary = {
        "n_positions": port.n_positions,
        "cost_basis": round(float(port.cost_basis), 2),
        "market_value": round(float(port.market_value), 2),
        "unrealized_pnl": round(float(port.unrealized_pnl), 2),
        "unrealized_pnl_pct": round(float(port.unrealized_pnl_pct), 4),
        "max_single_weight": round(float(port.max_single_weight), 4),
        "n_at_risk": port.n_at_risk,
        "worst_drawdown_pct": round(float(port.worst_drawdown_pct), 4),
        "peak_market_value": (
            round(float(port.peak_market_value), 2)
            if port.peak_market_value is not None else None
        ),
        "drawdown_from_peak_pct": (
            round(float(port.drawdown_from_peak_pct), 4)
            if port.drawdown_from_peak_pct is not None else None
        ),
    }

    report_payload = {
        "date": args.asof,
        "market": args.market,
        "strategy": args.strategy,
        "strategy_kind": args.kind,
        "strategy_name": args.strategy_name,
        "market_gate": gate_ok,
        "market_gate_msg": gate_msg_str,
        "benchmark_close": bench_close_val,
        "benchmark_ma60": bench_ma_val,
        "signals": report_signals,
        "positions": report_positions,
        # 组合层风控 alerts —— 前端 banner 红字显示；空 list = 无告警
        "portfolio_alerts": list(port.alerts),
        # PR2: 组合层汇总 + peak DD（包含 peak_market_value / drawdown_from_peak_pct）
        "portfolio_summary": portfolio_summary,
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
    from quant_system.db.ingest import maybe_ingest_quant, maybe_upsert_portfolio_history
    maybe_ingest_quant(report_payload)

    # PR1：portfolio_history 收尾 UPSERT —— PR2 在此基础上算 peak DD
    from datetime import date as _date
    _ph_strategy_name = args.strategy_name or args.strategy or args.kind
    maybe_upsert_portfolio_history(
        asof=_date.fromisoformat(str(args.asof)[:10]),
        strategy_name=_ph_strategy_name,
        market=args.market,
        n_positions=port.n_positions,
        cost_basis=float(port.cost_basis),
        market_value=float(port.market_value),
        unrealized_pnl=float(port.unrealized_pnl),
        unrealized_pnl_pct=float(port.unrealized_pnl_pct),
    )

    # 自动重建 HTML 报告
    from quant_system.report.builder import rebuild_html_report
    rebuild_html_report(args.asof, open_browser=False)


if __name__ == "__main__":
    main()
