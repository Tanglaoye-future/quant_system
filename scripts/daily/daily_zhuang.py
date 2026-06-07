#!/usr/bin/env python3
"""
庄股策略 daily 建仓闭环（生产用）.

流程（与回测引擎 ZhuangBacktester 同口径）:
  Step 1 风控  : 对 ledger 里 open 仓位跑 check_exit_signal → 写盯市快照 + 输出 EXIT/HOLD 建议
  Step 2 扫描  : 全 universe 算吃货期评分 → 候选清单（报表用）
  Step 3 建仓  : check_entry_signal Phase-A + 市场趋势门 + tiered sizing → 自动写 ledger

出场为 advisory（与 equity daily 一致，不自动平仓）；建仓为 auto-record（按信号日收盘价记账，
次日开盘≈成交）。zhuang 持仓存独立 ledger（zhuang_trades），与 equity 完全隔离。

用法:
  python scripts/daily/daily_zhuang.py --capital 400000
  python scripts/daily/daily_zhuang.py --dry-run          # 只看信号不建仓
  python scripts/daily/daily_zhuang.py --top 20 --min-score 55
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from quant_system.strategies.zhuang.data.loader import ZhuangDataLoader
from quant_system.strategies.zhuang.journal.journal import TradeOpen, ZhuangJournal
from quant_system.strategies.zhuang.signals.accumulation import accumulation_score_detail
from quant_system.strategies.zhuang.signals.entry import check_entry_signal
from quant_system.strategies.zhuang.signals.exit import check_exit_signal

_REPORT_DATA = Path(__file__).resolve().parents[2] / "report" / "data"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def parse_args():
    p = argparse.ArgumentParser(description="庄股策略 daily 建仓闭环")
    p.add_argument("--config", default="config/zhuang.yaml")
    p.add_argument("--market", default=None,
                   help="Phase 1-C: 指定 market (a_share / hk_small); 缺省读 config.default_market 或 a_share")
    p.add_argument("--date", default=date.today().strftime("%Y-%m-%d"), help="扫描日期")
    p.add_argument("--top", type=int, default=15, help="候选清单显示 TOP N")
    p.add_argument("--min-score", type=float, default=50.0, help="候选清单最低评分（仅报表，与入场阈值无关）")
    p.add_argument("--refresh-days", type=int, default=1)
    p.add_argument("--capital", type=float, default=1_000_000,
                   help="本策略可用资金（部署计划里 zhuang≈40%%，示例 --capital 400000）")
    p.add_argument("--dry-run", action="store_true", help="只显示信号，不实际建仓")
    p.add_argument("--no-write", action="store_true", help="不写盯市快照 / 不建仓（纯干跑）")
    return p.parse_args()


def _compute_position_pct(strat: dict, score: float) -> float:
    """与 ZhuangBacktester._compute_position_pct 同逻辑：按 score + 模式决定单票占比。"""
    mode = str(strat.get("position_size_mode", "fixed"))
    single_max = float(strat.get("single_position_pct_max", 0.05))
    if mode == "tiered":
        t = list(strat.get("tiered_score_thresholds", [75.0, 80.0]))
        p = list(strat.get("tiered_position_pcts", [0.04, 0.05, 0.06]))
        if len(t) >= 2 and len(p) >= 3:
            if score < t[0]:
                return float(p[0])
            if score < t[1]:
                return float(p[1])
            return float(p[2])
        return single_max
    if mode == "linear":
        lo = float(strat.get("linear_score_min", 70.0))
        hi = float(strat.get("linear_score_max", 85.0))
        pmin = float(strat.get("linear_position_min", 0.04))
        pmax = float(strat.get("linear_position_max", 0.06))
        if hi <= lo:
            return single_max
        ratio = max(0.0, min(1.0, (float(score) - lo) / (hi - lo)))
        return pmin + ratio * (pmax - pmin)
    return single_max


def _market_trend_ok(loader: ZhuangDataLoader, strat: dict, asof: str):
    """中证500（或配置基准）close>MA60 且 MA20>MA60 才允许建仓。

    返回 True/False；数据缺失时返回 None（不阻断，仅告警）—— 与回测同判别口径。
    """
    if not bool(strat.get("market_trend_filter", False)):
        return None
    benchmark = loader.market_cfg.get("benchmark") or strat.get("market_trend_index", "sh.000905")
    idx_code = str(benchmark).split(".")[-1]
    ma_n = int(strat.get("market_trend_ma", 60))
    start = (pd.Timestamp(asof) - pd.Timedelta(days=420)).strftime("%Y-%m-%d")
    try:
        idx = loader.get_daily(idx_code, start, asof)
    except Exception as e:
        print(f"[warn] 基准 {benchmark} 拉取失败({e})，跳过市场趋势门", flush=True)
        return None
    if idx is None or idx.empty or len(idx) < ma_n + 1:
        print(f"[warn] 基准 {benchmark} 数据不足({0 if idx is None else len(idx)} 行)，跳过市场趋势门", flush=True)
        return None
    idx = idx.sort_values("date").reset_index(drop=True)
    close = float(idx["close"].iloc[-1])
    ma60 = float(idx["close"].rolling(ma_n).mean().iloc[-1])
    ma20 = float(idx["close"].rolling(20).mean().iloc[-1])
    ok = close > ma60 and ma20 > ma60
    print(f"  市场趋势门: {benchmark} close={close:.2f} MA{ma_n}={ma60:.2f} MA20={ma20:.2f} → {'OK' if ok else 'X 熊市停手'}",
          flush=True)
    return ok


def main():
    args = parse_args()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = Path(__file__).resolve().parents[2] / args.config
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    market = args.market or config.get("default_market", "a_share")
    loader = ZhuangDataLoader(config, refresh_days=args.refresh_days, market=market)
    strat = config.get("strategy", {}) or {}
    acc_w = config.get("accumulation_weights", {}) or None

    journal = ZhuangJournal()
    journal.init_schema()

    print()
    print("=" * 78)
    print(f"  庄股 daily   asof = {args.date}   market = {market}")
    print("=" * 78)

    # ── Step 1: 风控（open 持仓出场评估 + 盯市快照，advisory 不自动平）─────────
    # safety margin 阈值：距离 < 1% 算"贴线"，与 equity_factor 同款
    CRITICAL_MARGIN = 0.01
    atr_mult_cfg = float(strat.get("stop_loss_atr_mult", 1.5))
    max_stop_cfg = float(strat.get("max_stop_loss_pct", 0.06))
    tp_pct_cfg = float(strat.get("take_profit_pct", 0.10))

    open_trades = journal.list_open()
    open_codes = {t["code"] for t in open_trades}
    exits, holds = [], []
    for tr in open_trades:
        code = tr["code"]
        df_since = loader.get_daily(code, tr["entry_date"], args.date)
        if df_since is None or df_since.empty:
            holds.append({"code": code, "pnl_pct": None, "hold_days": None,
                          "action": "持有", "reason": "无行情(停牌?)",
                          "entry_price": tr["entry_price"], "entry_size": tr.get("entry_size"),
                          "current_price": None, "stop_loss": tr.get("stop_loss_price"),
                          "take_profit": tr.get("take_profit_price"),
                          "dist_to_stop_pct": None, "dist_to_target_pct": None})
            continue
        atr_entry = tr.get("atr_at_entry") or (tr["entry_price"] * 0.03)
        sig = check_exit_signal(
            code=code,
            df_since_entry=df_since,
            entry_price=tr["entry_price"],
            entry_date=tr["entry_date"],
            atr_at_entry=atr_entry,
            stop_loss_atr_mult=atr_mult_cfg,
            max_stop_loss_pct=max_stop_cfg,
            momentum_stop_pct=float(strat.get("momentum_stop_pct", 0.03)),
            take_profit_pct=tp_pct_cfg,
            max_hold_days=int(strat.get("max_hold_days", 10)),
            extend_hold_days=int(strat.get("extend_hold_days", 25)),
            extend_profit_pct=float(strat.get("extend_profit_pct", 0.05)),
            distribution_turnover_thresh=float(strat.get("distribution_turnover_thresh", 6.0)),
        )
        today_close = float(df_since["close"].iloc[-1])
        pnl_pct = today_close / tr["entry_price"] - 1.0
        hold_days = len(df_since) - 1
        is_exit = sig.action == "EXIT"

        # safety margin：止损 = ATR 止损 vs 固定比例止损取较高者（与 check_exit_signal 同公式），
        # 与 ledger 里 stop_loss_price 一致；止盈 = entry × (1 + tp_pct)。
        # zhuang 止损当前不 trail（静态），所以 ledger.stop_loss_price 即为今日有效止损价。
        stop_px = tr.get("stop_loss_price")
        if stop_px is None or stop_px <= 0:
            stop_px = max(tr["entry_price"] - atr_mult_cfg * atr_entry,
                          tr["entry_price"] * (1.0 - max_stop_cfg))
        tp_px = tr.get("take_profit_price") or tr["entry_price"] * (1.0 + tp_pct_cfg)
        dist_to_stop = (today_close - stop_px) / today_close if today_close > 0 and stop_px > 0 else None
        dist_to_target = (tp_px - today_close) / today_close if today_close > 0 and tp_px > 0 else None

        if not args.no_write:
            journal.add_snapshot(tr["id"], args.date, today_close,
                                 risk_flag="exit" if is_exit else "normal",
                                 note=sig.reason)
        rec = {
            "code": code, "pnl_pct": pnl_pct, "hold_days": hold_days,
            "action": "卖出" if is_exit else "持有", "reason": sig.reason,
            "entry_price": tr["entry_price"], "entry_size": tr.get("entry_size"),
            "current_price": today_close,
            "stop_loss": float(stop_px), "take_profit": float(tp_px),
            "dist_to_stop_pct": dist_to_stop, "dist_to_target_pct": dist_to_target,
        }
        (exits if is_exit else holds).append(rec)

    print()
    print(f"【今日卖出建议】 ({len(exits)} 笔，advisory — 不自动平仓)")
    if not exits:
        print("  无")
    for r in exits:
        print(f"  {r['code']}  浮盈 {r['pnl_pct']*100:+.2f}%  持有 {r['hold_days']} 天  >> {r['reason']}")
    print()
    print(f"【持有维持】 ({len(holds)} 笔)")
    if not holds:
        print("  无")
    n_critical = 0
    for r in holds:
        pp = f"{r['pnl_pct']*100:+.2f}%" if r["pnl_pct"] is not None else "—"
        hd = r["hold_days"] if r["hold_days"] is not None else "—"
        # safety margin 段：与 equity_factor 同款，止损贴线 ⚠，止盈中性
        stop_seg = (
            f"距 {r['dist_to_stop_pct']*100:+.2f}%"
            if r.get("dist_to_stop_pct") is not None else "距 —"
        )
        tp_seg = (
            f"止盈 {r['take_profit']:.2f} (距 {r['dist_to_target_pct']*100:+.2f}%)"
            if r.get("take_profit") is not None and r.get("dist_to_target_pct") is not None
            else "止盈 —"
        )
        is_critical = (
            r.get("dist_to_stop_pct") is not None and r["dist_to_stop_pct"] < CRITICAL_MARGIN
        )
        warn = " ⚠ 临界" if is_critical else ""
        if is_critical:
            n_critical += 1
        stop_str = f"止损 {r['stop_loss']:.2f}" if r.get("stop_loss") is not None else "止损 —"
        print(f"  {r['code']}  浮盈 {pp}  {stop_str} ({stop_seg})  {tp_seg}  持有 {hd} 天{warn}")
    if n_critical > 0 and holds:
        print(f"  ⚠ {n_critical}/{len(holds)} 只贴近止损 (margin < {CRITICAL_MARGIN*100:.0f}%)，"
              "组合层均值可能掩盖单只风险")

    # 加载 universe code → 名称 映射 (持仓 + 候选填中文名, dashboard 操盘人友好)
    name_map = loader.get_name_map(args.date)

    # ── Step 2: 全 universe 扫候选（报表用，沿用旧逻辑）─────────────────────────
    universe = loader.get_universe(args.date)
    print()
    print(f"[scan] universe={len(universe)} codes, date={args.date}")
    report_min = float(args.min_score)
    px_by_code: dict[str, pd.DataFrame] = {}
    results = []
    for i, code in enumerate(universe, 1):
        if i % 200 == 0:
            print(f"  [{i}/{len(universe)}]", flush=True)
        df = loader.get_daily(code, "2020-01-01", args.date)
        if df is None or len(df) < 40:
            continue
        px_by_code[code] = df
        detail = accumulation_score_detail(df, weights=acc_w)
        if detail["total"] >= report_min:
            results.append({"code": code, **detail})

    df_out = pd.DataFrame(results).sort_values("total", ascending=False) if results else pd.DataFrame()
    print()
    print(f"【吃货期候选】 (score >= {report_min}，共 {len(df_out)} 只)")
    if not df_out.empty:
        print(df_out.head(args.top).to_string(index=False))
        out_path = Path("data") / f"scan_{args.date}.csv"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df_out.to_csv(out_path, index=False)
        print(f"  已保存 → {out_path}")

    # ── Step 3: 自动建仓（check_entry_signal Phase-A + 市场趋势门 + tiered sizing）─
    market_trend = _market_trend_ok(loader, strat, args.date)
    pos_max = int(strat.get("position_max_count", 6))
    available_slots = pos_max - len(open_trades)
    acc_score_entry = float(strat.get("accumulation_score_entry", 70.0))
    price_pos_min = float(strat.get("entry_price_position_min", 0.4))
    vol_spike = float(strat.get("volume_spike_ratio_min", 2.0))

    new_trades = []
    print()
    if args.dry_run or args.no_write:
        print("【自动建仓】 (干跑模式，不实际建仓)")
    elif available_slots <= 0:
        print(f"【自动建仓】 仓位已满 ({len(open_trades)}/{pos_max})，跳过")
    elif market_trend is False:
        print("【自动建仓】 市场趋势门 X（熊市），今日不建新仓")
    else:
        entry_hits = []
        for code, df in px_by_code.items():
            if code in open_codes:
                continue
            sig = check_entry_signal(
                code=code, df=df, asof_date=args.date,
                score_threshold=acc_score_entry, volume_spike_ratio=vol_spike,
                phase="A", acc_weights=acc_w, price_position_min=price_pos_min,
            )
            if sig is not None:
                entry_hits.append(sig)
        entry_hits.sort(key=lambda s: -s.accumulation_score)

        atr_mult = float(strat.get("stop_loss_atr_mult", 1.5))
        max_stop = float(strat.get("max_stop_loss_pct", 0.06))
        tp_pct = float(strat.get("take_profit_pct", 0.10))
        for sig in entry_hits:
            if len(new_trades) >= available_slots:
                break
            code = sig.code
            entry_px = float(sig.price)   # 信号日收盘价（记账参考价）
            pos_pct = _compute_position_pct(strat, sig.accumulation_score)
            size = int(args.capital * pos_pct / entry_px / 100) * 100
            if size < 100:
                continue
            df = px_by_code[code]
            atr_series = loader.compute_atr(df)
            atr_val = float(atr_series.iloc[-1]) if not atr_series.empty else entry_px * 0.03
            if np.isnan(atr_val):
                atr_val = entry_px * 0.03
            # 有效止损 = ATR止损 与 固定比例止损 取较高者（与 check_exit_signal 一致）
            stop_px = max(entry_px - atr_mult * atr_val, entry_px * (1.0 - max_stop))
            tp_px = entry_px * (1.0 + tp_pct)
            tid = journal.open_trade(TradeOpen(
                code=code, market=market, entry_date=args.date,
                entry_price=entry_px, entry_size=size,
                accumulation_score=sig.accumulation_score, phase=sig.phase,
                atr_at_entry=atr_val, entry_reason=sig.reason,
                stop_loss_price=stop_px, take_profit_price=tp_px,
            ))
            new_trades.append({"id": tid, "code": code, "size": size, "entry_px": entry_px,
                               "score": sig.accumulation_score, "pos_pct": pos_pct,
                               "stop": stop_px, "tp": tp_px})
            open_codes.add(code)

        if new_trades:
            print(f"【自动建仓】 ({len(new_trades)} 笔)")
            for t in new_trades:
                cost = t["size"] * t["entry_px"]
                print(f"  #{t['id']} {t['code']}  score {t['score']:.1f}  仓位{t['pos_pct']*100:.0f}%  "
                      f"{t['size']}股 @ {t['entry_px']:.2f}  成本 {cost:,.0f}  "
                      f"止损 {t['stop']:.2f}  止盈 {t['tp']:.2f}")
        else:
            print(f"【自动建仓】 无符合 Phase-A 入场条件的新仓 (可用槽位 {available_slots})")

    # ── 组合摘要 + portfolio_alerts（与 equity_factor 06-04 同款 3 阈值，仅告警）──
    # 复用已持仓的 size + current_price 算市值；新建仓按 entry_px × size 入账。
    cost_basis = 0.0
    market_value = 0.0
    weights: list[tuple[str, float]] = []
    worst_pnl: float | None = None
    for r in exits + holds:
        sz = r.get("entry_size") or 0
        ep = r.get("entry_price") or 0.0
        cp = r.get("current_price") if r.get("current_price") is not None else ep
        if sz and ep:
            cost_basis += sz * ep
            mv = sz * cp
            market_value += mv
            weights.append((r["code"], mv))
        if r.get("pnl_pct") is not None:
            worst_pnl = r["pnl_pct"] if worst_pnl is None else min(worst_pnl, r["pnl_pct"])
    for t in new_trades:
        sz = t["size"]
        ep = t["entry_px"]
        cost_basis += sz * ep
        mv = sz * ep
        market_value += mv
        weights.append((t["code"], mv))
    unrealized_pnl = market_value - cost_basis
    unrealized_pnl_pct = (unrealized_pnl / cost_basis) if cost_basis > 0 else 0.0
    max_single_weight = (max(w for _, w in weights) / market_value) if (weights and market_value > 0) else 0.0
    n_at_risk = len(exits)
    n_positions_total = len(exits) + len(holds) + len(new_trades)

    portfolio_alerts: list[str] = []
    pr_node = config.get("portfolio_risk") or {}
    if bool(pr_node.get("enabled", False)) and n_positions_total > 0:
        max_w_thr = pr_node.get("max_single_weight_pct")
        pnl_floor_thr = pr_node.get("unrealized_pnl_floor_pct")
        exit_ratio_thr = pr_node.get("exit_signal_ratio_max")
        if max_w_thr is not None and max_single_weight > float(max_w_thr):
            portfolio_alerts.append(
                f"单只权重 {max_single_weight*100:.1f}% > 阈值 {float(max_w_thr)*100:.0f}%（集中度）"
            )
        if pnl_floor_thr is not None and unrealized_pnl_pct < float(pnl_floor_thr):
            portfolio_alerts.append(
                f"组合浮盈 {unrealized_pnl_pct*100:+.2f}% < 阈值 {float(pnl_floor_thr)*100:+.0f}%（账户层 stop alarm）"
            )
        if exit_ratio_thr is not None and n_positions_total > 0:
            ratio = n_at_risk / n_positions_total
            if ratio > float(exit_ratio_thr):
                portfolio_alerts.append(
                    f"EXIT 信号占比 {ratio*100:.0f}% > 阈值 {float(exit_ratio_thr)*100:.0f}%（panic 信号）"
                )

    total_open = len(open_trades) + len(new_trades)
    print()
    print("【组合摘要】")
    if n_positions_total == 0:
        print(f"  持仓 {total_open}/{pos_max} 只  当前空仓")
    else:
        print(f"  持仓 {total_open}/{pos_max} 只  (原有 {len(open_trades)} + 新建 {len(new_trades)})  "
              f"卖出建议 {len(exits)} 笔")
        if cost_basis > 0:
            print(f"  总成本 {cost_basis:.0f} / 总市值 {market_value:.0f} / "
                  f"浮盈 {unrealized_pnl_pct*100:+.2f}%  单只最大占比 {max_single_weight*100:.1f}%  "
                  f"最差单只浮亏 {(worst_pnl or 0)*100:+.2f}%")
    for alert in portfolio_alerts:
        print(f"  ⚠ 组合层告警: {alert}")
    print()

    # ── 报表 JSON（候选 + 持仓 + safety margin 字段）───────────────────────────
    def _round_or_none(v, n=4):
        return round(float(v), n) if v is not None else None

    report_positions = []
    for r in exits + holds:
        report_positions.append({
            "code": r["code"], "name": name_map.get(r["code"], ""),
            "entry_date": next((t["entry_date"] for t in open_trades if t["code"] == r["code"]), ""),
            "hold_days": r["hold_days"],
            "pnl_pct": _round_or_none(r["pnl_pct"], 4),
            "action": r["action"],
            # safety margin 字段（与 equity_factor 同结构）
            "entry_price": _round_or_none(r.get("entry_price"), 2),
            "current_price": _round_or_none(r.get("current_price"), 2),
            "stop_loss": _round_or_none(r.get("stop_loss"), 2),
            "take_profit": _round_or_none(r.get("take_profit"), 2),
            "dist_to_stop_pct": _round_or_none(r.get("dist_to_stop_pct"), 4),
            "dist_to_target_pct": _round_or_none(r.get("dist_to_target_pct"), 4),
        })
    for t in new_trades:
        report_positions.append({
            "code": t["code"], "name": name_map.get(t["code"], ""), "entry_date": args.date,
            "hold_days": 0, "pnl_pct": 0.0, "action": "建仓",
            "entry_price": _round_or_none(t["entry_px"], 2),
            "current_price": _round_or_none(t["entry_px"], 2),
            "stop_loss": _round_or_none(t["stop"], 2),
            "take_profit": _round_or_none(t["tp"], 2),
            "dist_to_stop_pct": _round_or_none((t["entry_px"] - t["stop"]) / t["entry_px"], 4),
            "dist_to_target_pct": _round_or_none((t["tp"] - t["entry_px"]) / t["entry_px"], 4),
        })

    top15 = df_out.head(15).to_dict(orient="records") if not df_out.empty else []
    top15_with_name = []
    for row in top15:
        item = {k: (float(v) if hasattr(v, "item") else v) for k, v in row.items()}
        item["name"] = name_map.get(item.get("code", ""), "")
        top15_with_name.append(item)
    report_payload = {
        "date": args.date,
        "market": market,
        "universe_size": len(universe),
        "candidates_count": len(df_out),
        "market_trend": market_trend,
        "top_candidates": top15_with_name,
        "positions": report_positions,
        # 组合层风控 alerts（默认 enabled: false → 永远 []，零回归）
        "portfolio_alerts": portfolio_alerts,
    }
    _REPORT_DATA.mkdir(parents=True, exist_ok=True)
    (_REPORT_DATA / "zhuang.json").write_text(
        json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[report] zhuang.json → {_REPORT_DATA / 'zhuang.json'}")

    # 双写 Postgres（失败不影响 JSON 跑批）
    from quant_system.db.ingest import maybe_ingest_zhuang, maybe_upsert_portfolio_history
    maybe_ingest_zhuang(report_payload)

    # PR1：portfolio_history 收尾 UPSERT —— PR2 在此基础上算 peak DD
    from datetime import date as _date
    maybe_upsert_portfolio_history(
        asof=_date.fromisoformat(str(args.date)[:10]),
        strategy_name="zhuang",
        market=market,
        n_positions=n_positions_total,
        cost_basis=float(cost_basis),
        market_value=float(market_value),
        unrealized_pnl=float(unrealized_pnl),
        unrealized_pnl_pct=float(unrealized_pnl_pct),
    )

    # 自动重建 HTML 报告
    from quant_system.report.builder import rebuild_html_report
    rebuild_html_report(args.date, open_browser=False)

    loader._logout()


if __name__ == "__main__":
    main()
