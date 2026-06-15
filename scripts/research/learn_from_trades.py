#!/usr/bin/env python3
"""L5 of docs/specs/self_learning_pipeline.md — retrospective 报表脚手架.

读 PG 的 closed trades (journal_trades + zhuang_trades) 含 L2-L4 采集的
entry_features / exit_features, 输出 winner-vs-loser 分布差 + 18 条证伪
cross-check + 严格小样本警告.

设计原则 (5 条 Backstop 全适用):
1. 18 条证伪 + 四层 efficient set 硬墙 — candidate 撞墙强 SOFT-FALSIFY
2. 双窗口 4y+8y Sharpe 同向才落 yaml — 报表 footer 强制写
3. N < min_sample 强 warn + 拒输出分布差结论
4. PM 决策权 — 程序产出报告, 不自动改 alpha
5. 采集与 alpha 决策完全分离 — 报表零写 yaml / 零触发 daily / 零新依赖 (无 scipy)

入口:
    venv/bin/python scripts/research/learn_from_trades.py \\
        [--since 2026-05-22] [--min-sample 10] \\
        [--output md|json|both] [--out-dir logs]

详 docs/specs/learn_l5_retrospective_report.md.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ── 18 条证伪 manifest (L5 stub — match 逻辑骨架, L5.1 完整 implement) ─────────

FALSIFIED_PATTERNS: list[dict[str, Any]] = [
    # 数据源死亡 (不投 backtest)
    {
        "name": "northbound_overlay",
        "keywords": ["northbound", "北向", "hsgt_north"],
        "doc_ref": "a1_northbound_dead_southbound_alive_2026-06",
        "severity": "DEAD",
        "note": "akshare 2024-08 起永久 NaN; 无替代数据源",
    },
    {
        "name": "southbound_gate_threshold",
        "keywords": ["southbound", "南向", "南向 gate"],
        "doc_ref": "a1prime_southbound_gate_falsified_2026-06",
        "severity": "DEAD",
        "note": "widen + gate 互斥; 4y backtest -0.058 Sharpe; base rate spurious",
    },
    # HS300 因子层 (L8D2 已是 efficient set)
    {
        "name": "hs300_roic",
        "keywords": ["roic"],
        "doc_ref": "equity_factor_l9b_falsified_2026-05",
        "severity": "DEAD",
        "note": "Spearman(ROIC, ROE) ∈ [0.92, 0.95]; 与 ROE 完全重复",
    },
    {
        "name": "hs300_ar_yoy",
        "keywords": ["ar_yoy", "应收账款", "应收增长"],
        "doc_ref": "equity_factor_l9b_falsified_2026-05",
        "severity": "DEAD",
        "note": "AR YoY 横截面 median ≈ -0.78 一致负; 中国累计申报季节性 artifact",
    },
    {
        "name": "hs300_fcf_yield",
        "keywords": ["fcf_yield", "fcf"],
        "doc_ref": "equity_factor_l8_2026-05",
        "severity": "DEAD",
        "note": "L8 双窗口同时负贡献; L8D2 (fcf=0) 已落 yaml",
    },
    # zhuang sleeve (L1-E sweet spot)
    {
        "name": "zhuang_position_max_count_8_10",
        "keywords": ["position_max_count"],
        "doc_ref": "zhuang_l7a_falsified_2026-05",
        "severity": "DEAD",
        "note": "6/8/10 三 case 同分 Sharpe 1.505; cap 不 binding",
    },
    {
        "name": "zhuang_score_threshold_loosen",
        "keywords": ["accumulation_score_entry", "score_threshold"],
        "doc_ref": "zhuang_l7b_falsified_2026-05",
        "severity": "DEAD",
        "note": "70→67→65 单调下 (1.505→0.925→0.843); 放宽损质量",
    },
    {
        "name": "zhuang_fundamentals_gate",
        "keywords": ["zhuang_roe", "zhuang_fundamentals", "zhuang_revenue"],
        "doc_ref": "zhuang_l8_fundamentals_falsified_2026-05",
        "severity": "DEAD",
        "note": "winner/loser ROE>0 占比 73% vs 79% 反向; 误杀 47% ≈ 随机",
    },
    {
        "name": "zhuang_accumulation_weights_strong",
        "keywords": ["accumulation_weights_strong", "strong-volume", "strong-conso"],
        "doc_ref": "zhuang_l6a_weights_2026-05",
        "severity": "DEAD",
        "note": "L6-A: equal weights (0.20×5) 双窗口同向赢 baseline; strong 变体过拟合",
    },
    # 组合层 (v5 是 efficient frontier)
    {
        "name": "ibit_overlay",
        "keywords": ["ibit", "btc", "bitcoin"],
        "doc_ref": "v5_efficient_frontier_2026-05",
        "severity": "DEAD",
        "note": "5/10% 配比 Sharpe -0.10 / -0.87; 高 vol 拖累 frontier",
    },
    {
        "name": "tlt_overlay",
        "keywords": ["tlt", "long_bond"],
        "doc_ref": "v5_efficient_frontier_2026-05",
        "severity": "DEAD",
        "note": "5/10% 配比 Sharpe -0.13 / -0.37; 8y -0.08 单资产",
    },
    {
        "name": "csi1000_overlay",
        "keywords": ["csi1000_overlay"],
        "doc_ref": "v5_efficient_frontier_2026-05",
        "severity": "DEAD",
        "note": "5/10% 配比 Sharpe -0.10 / -0.34",
    },
    # A_mr 4 路径
    {
        "name": "a_mr_v1_swing_reversion",
        "keywords": ["mean_reversion_v1", "swing_reversion"],
        "doc_ref": "a_mr_rebuild_v6_grid_2026-05",
        "severity": "DEAD",
        "note": "4y Sharpe -0.27; A_mr 是 hedge 价值非 solo alpha",
    },
    {
        "name": "a_mr_v2_buffer_slope",
        "keywords": ["a_mr_v2", "ma200_buffer"],
        "doc_ref": "a_mr_v2_falsified_2026-05",
        "severity": "DEAD",
        "note": "sweep 5 case plateau -0.27~-0.34",
    },
    # 组合层 regime overlay
    {
        "name": "v6_regime_overlay",
        "keywords": ["regime_overlay", "v6_regime"],
        "doc_ref": "v6_regime_overlay_2026-05",
        "severity": "DEAD",
        "note": "双 MA200 动态权重全窗口 2.142 < v5 静态 2.231",
    },
    # 反向情绪 / capitulation
    {
        "name": "capitulation_execution_alpha",
        "keywords": ["capitulation", "panic_buy", "rebound"],
        "doc_ref": "capitulation_strategy_falsified_2026-06",
        "severity": "DEAD",
        "note": "execution-vs-strategy 错配; akshare 跌停撬开 30 日窗口; LHB T+1 滞后",
    },
    # C ensemble (双窗口反向)
    {
        "name": "mom3m_mom6m_ensemble",
        "keywords": ["mom6m", "mom_6m", "momentum_6m"],
        "doc_ref": "equity_factor_c_ensemble_falsified_2026-06",
        "severity": "DEAD",
        "note": "4y +0.082 / 8y -0.052; AMBIGUOUS verdict ≡ SOFT-FALSIFY",
    },
    # TP runner / ATR trail sweep (HK, windowed paradox 第 7 类)
    {
        "name": "tp_runner_atr_sweep_hk",
        "keywords": ["atr_target_mult", "atr_stop_mult", "tp_runner", "trail_widen"],
        "doc_ref": "tp_runner_sweep_falsified_2026-06",
        "severity": "SOFT-FALSIFY",
        "note": "HK 12 变体双窗口 0 PASS; 4y stop=3.0 +0.095 Sharpe / DD -7pp 但 8y -0.131 异号; time_stop 留 alpha 假设反证",
    },
]


# ── Mann-Whitney U (normal approximation, 不带 scipy) ──────────────────────────

def _norm_cdf(x: float) -> float:
    """Φ(x) = 0.5 * (1 + erf(x / √2))."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _ranks_with_ties(values: list[float]) -> list[float]:
    """Average-rank with ties (秩相同时取平均秩)."""
    n = len(values)
    indexed = sorted(enumerate(values), key=lambda t: t[1])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # ranks 1-based
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def mann_whitney_u_p(a: list[float], b: list[float]) -> Optional[float]:
    """Two-sided Mann-Whitney U p-value, normal approximation (无 scipy 依赖).

    Returns None if either group empty / n < 2.
    Note: n < 20 时 approximation 偏差大; 调用方应配合 min_sample warn.
    """
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return None
    combined = a + b
    ranks = _ranks_with_ties(combined)
    rank_sum_a = sum(ranks[:na])
    u_a = rank_sum_a - na * (na + 1) / 2.0
    mean_u = na * nb / 2.0
    # tie correction omitted (小样本下 corrective term 影响有限, L5 阶段够用)
    std_u = math.sqrt(na * nb * (na + nb + 1) / 12.0)
    if std_u == 0:
        return None
    z = (u_a - mean_u) / std_u
    p = 2.0 * (1.0 - _norm_cdf(abs(z)))
    return max(0.0, min(1.0, p))


# ── Falsified manifest cross-check ────────────────────────────────────────────

def cross_check_falsified(candidate_name: str) -> Optional[dict[str, Any]]:
    """candidate feature name 撞 18 条证伪墙 → 返 manifest entry; 否则 None.

    L5 当前仅 keyword substring match (lowercase). L5.1 升级为 regex + 阈值。
    """
    cand_lower = candidate_name.lower()
    for pattern in FALSIFIED_PATTERNS:
        for kw in pattern["keywords"]:
            if kw.lower() in cand_lower:
                return pattern
    return None


# ── benchmark α 计算 (M2 of L5.0.1) ──────────────────────────────────────────

# sleeve → baostock index code (None 表示 L5.0.1 未接入)
SLEEVE_BENCHMARK: dict[str, Optional[tuple[str, str]]] = {
    "A_mom": ("sh.000300", "HS300"),
    "HK_mom": None,         # HSCHK100 / HSI 选哪个留 L5.0.2 决策
    "zhuang": ("sh.000905", "CSI500"),
    "mean_reversion": ("sh.000300", "HS300"),  # M1 启用后归在 A_mom 桶里, 这里留备用
}


def _fetch_benchmark_close(code: str, start: str, end: str) -> Optional[dict[str, float]]:
    """拉 baostock index 日线, 返 {date_str: close}; fail-soft None.

    单次脚本里多次调用同 (code, start, end) 是 inefficient — 调用方在 build_report
    最外层 cache 一次即可 (per sleeve 一次 query).
    """
    try:
        import baostock as bs  # type: ignore
    except ImportError:
        return None
    try:
        bs.login()
        try:
            rs = bs.query_history_k_data_plus(
                code, "date,close",
                start_date=start, end_date=end,
                frequency="d", adjustflag="3",
            )
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            if not rows:
                return None
            return {r[0]: float(r[1]) for r in rows}
        finally:
            bs.logout()
    except Exception:
        return None


def _alpha_for_trade(trade: dict, bench_close: Optional[dict[str, float]]) -> tuple[Optional[float], Optional[float]]:
    """返 (benchmark_pnl_pct, alpha_pct); 任一缺失返 (None, None)."""
    if bench_close is None or not bench_close:
        return None, None
    pnl = trade.get("pnl_pct")
    if pnl is None:
        return None, None
    entry_d = trade.get("entry_date")
    exit_d = trade.get("exit_date")
    if not entry_d or not exit_d:
        return None, None
    # 用 entry_date / exit_date 的 close (若当天非交易日, 取最近一个早于该日的 close)
    bench_entry = bench_close.get(entry_d)
    bench_exit = bench_close.get(exit_d)
    if bench_entry is None or bench_exit is None:
        # 找最近 close 前一日
        dates_sorted = sorted(bench_close.keys())
        if bench_entry is None:
            cands = [d for d in dates_sorted if d <= entry_d]
            bench_entry = bench_close[cands[-1]] if cands else None
        if bench_exit is None:
            cands = [d for d in dates_sorted if d <= exit_d]
            bench_exit = bench_close[cands[-1]] if cands else None
    if bench_entry is None or bench_exit is None or bench_entry <= 0:
        return None, None
    bench_pnl = bench_exit / bench_entry - 1.0
    alpha = pnl - bench_pnl
    return bench_pnl, alpha


# ── 数据拉取 ──────────────────────────────────────────────────────────────────

def fetch_closed_trades(since: date) -> dict[str, list[dict]]:
    """返 {sleeve: [trade_row, ...]} for sleeves: A_mom / HK_mom / zhuang.

    A_mom = journal_trades.strategy='equity_momentum' & market='a_share'
    HK_mom = journal_trades.strategy='equity_hk_momentum' & market='hk_share'
    zhuang = zhuang_trades (无 strategy 字段, 全归 zhuang)
    """
    from sqlalchemy import select
    from quant_system.db import JournalTrade
    from quant_system.db.models import ZhuangTrade
    from quant_system.db.session import get_sessionmaker

    out: dict[str, list[dict]] = {"A_mom": [], "HK_mom": [], "zhuang": []}
    Sm = get_sessionmaker()
    with Sm() as s:
        rows = s.scalars(
            select(JournalTrade).where(
                JournalTrade.exit_date.isnot(None),
                JournalTrade.exit_date >= since,
            )
        ).all()
        for t in rows:
            d = {
                "symbol": t.symbol, "market": t.market, "strategy": t.strategy,
                "entry_date": str(t.entry_date), "exit_date": str(t.exit_date),
                "entry_price": t.entry_price, "exit_price": t.exit_price,
                "pnl_pct": t.pnl_pct, "hold_days": t.hold_days,
                "exit_reason": t.exit_reason,
                "entry_features": t.entry_features,
                "exit_features": t.exit_features,
            }
            if t.market == "hk_share":
                out["HK_mom"].append(d)
            else:
                out["A_mom"].append(d)
        zhuang_rows = s.scalars(
            select(ZhuangTrade).where(
                ZhuangTrade.exit_date.isnot(None),
                ZhuangTrade.exit_date >= since,
            )
        ).all()
        for t in zhuang_rows:
            out["zhuang"].append({
                "symbol": t.code, "market": t.market, "strategy": "zhuang",
                "entry_date": str(t.entry_date), "exit_date": str(t.exit_date),
                "entry_price": t.entry_price, "exit_price": t.exit_price,
                "pnl_pct": t.pnl_pct, "hold_days": t.hold_days,
                "exit_reason": t.exit_reason,
                "entry_features": t.entry_features,
                "exit_features": t.exit_features,
            })
    return out


# ── 报表组装 ──────────────────────────────────────────────────────────────────

def _numeric_keys(trades: list[dict]) -> list[str]:
    """提取 entry_features 里所有 numeric key (非 None 且非 bool/str)."""
    keys: set[str] = set()
    for t in trades:
        feats = t.get("entry_features") or {}
        for k, v in feats.items():
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                keys.add(k)
    return sorted(keys)


def _split_winner_loser(trades: list[dict]) -> tuple[list[dict], list[dict]]:
    winners = [t for t in trades if (t.get("pnl_pct") or 0) > 0]
    losers = [t for t in trades if (t.get("pnl_pct") or 0) <= 0]
    return winners, losers


def build_report(
    closed_by_sleeve: dict[str, list[dict]],
    min_sample: int,
    benchmark_fetcher=None,
) -> dict:
    """主报表数据结构 (md 渲染 + json 输出共用).

    benchmark_fetcher: 可注入 (test 用 mock 不走网络). 默认走 _fetch_benchmark_close.
    签名: (code, start, end) -> Optional[dict[str_date, close]]
    """
    if benchmark_fetcher is None:
        benchmark_fetcher = _fetch_benchmark_close

    report = {
        "asof": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "min_sample": min_sample,
        "sleeves": {},
        "global_warnings": [],
        "footer": (
            "本报表仅为 PM 决策辅助。任何 yaml 调参须先通过双窗口 4y+8y backtest "
            "同向 PASS (Backstop #2)。命中 SOFT-FALSIFY 标记的方向不应再尝试 "
            "(Backstop #1)。"
        ),
    }

    for sleeve, trades in closed_by_sleeve.items():
        n = len(trades)
        sleeve_data: dict[str, Any] = {
            "n_closed": n,
            "sample_sufficient": n >= min_sample,
        }
        if n == 0:
            sleeve_data["pnl_summary"] = None
            sleeve_data["alpha_summary"] = None
            report["sleeves"][sleeve] = sleeve_data
            continue

        # §2 PnL summary
        pnls = [t["pnl_pct"] for t in trades if t.get("pnl_pct") is not None]
        win_rate = sum(1 for p in pnls if p > 0) / len(pnls) if pnls else None
        sleeve_data["pnl_summary"] = {
            "win_rate": win_rate,
            "avg_pnl_pct": (sum(pnls) / len(pnls)) if pnls else None,
            "avg_win_pct": (sum(p for p in pnls if p > 0) / max(1, sum(1 for p in pnls if p > 0))) if pnls else None,
            "avg_loss_pct": (sum(p for p in pnls if p <= 0) / max(1, sum(1 for p in pnls if p <= 0))) if pnls else None,
        }

        # §2.5 benchmark-relative α (M2 of L5.0.1)
        bench_meta = SLEEVE_BENCHMARK.get(sleeve)
        if bench_meta is None:
            sleeve_data["alpha_summary"] = {
                "benchmark_code": None,
                "benchmark_name": None,
                "reason": "未接入 (L5.0.2 决策)",
            }
        else:
            bench_code, bench_name = bench_meta
            entry_dates = [t["entry_date"] for t in trades if t.get("entry_date")]
            exit_dates = [t["exit_date"] for t in trades if t.get("exit_date")]
            if not entry_dates or not exit_dates:
                sleeve_data["alpha_summary"] = {
                    "benchmark_code": bench_code, "benchmark_name": bench_name,
                    "reason": "无 entry/exit 日期",
                }
            else:
                start = min(entry_dates)
                end = max(exit_dates)
                bench_close = benchmark_fetcher(bench_code, start, end)
                if bench_close is None:
                    sleeve_data["alpha_summary"] = {
                        "benchmark_code": bench_code, "benchmark_name": bench_name,
                        "reason": "benchmark 拉取失败 (网络/baostock 不可用)",
                    }
                else:
                    bench_pnls: list[float] = []
                    alphas: list[float] = []
                    for t in trades:
                        bp, a = _alpha_for_trade(t, bench_close)
                        t["benchmark_pnl_pct"] = bp
                        t["alpha_pct"] = a
                        if bp is not None: bench_pnls.append(bp)
                        if a is not None: alphas.append(a)
                    sleeve_data["alpha_summary"] = {
                        "benchmark_code": bench_code,
                        "benchmark_name": bench_name,
                        "avg_benchmark_pnl_pct": (sum(bench_pnls) / len(bench_pnls)) if bench_pnls else None,
                        "avg_alpha_pct": (sum(alphas) / len(alphas)) if alphas else None,
                        "n_alpha_positive": sum(1 for a in alphas if a > 0),
                        "n_with_alpha": len(alphas),
                    }

        # §3 winner-vs-loser numeric (仅 N >= min_sample)
        if n < min_sample:
            sleeve_data["winner_vs_loser_numeric"] = None
            sleeve_data["winner_vs_loser_categorical"] = None
            sleeve_data["warnings"] = [
                f"N={n} < min_sample={min_sample}: 任何 winner-vs-loser 结论无统计学意义 (Backstop #3)"
            ]
            report["sleeves"][sleeve] = sleeve_data
            continue

        winners, losers = _split_winner_loser(trades)
        numeric_rows = []
        for key in _numeric_keys(trades):
            w_vals = [
                t["entry_features"][key]
                for t in winners
                if t.get("entry_features") and isinstance(t["entry_features"].get(key), (int, float))
                and not isinstance(t["entry_features"].get(key), bool)
            ]
            l_vals = [
                t["entry_features"][key]
                for t in losers
                if t.get("entry_features") and isinstance(t["entry_features"].get(key), (int, float))
                and not isinstance(t["entry_features"].get(key), bool)
            ]
            if not w_vals or not l_vals:
                continue
            row = {
                "feature": key,
                "winner_n": len(w_vals),
                "loser_n": len(l_vals),
                "winner_mean": sum(w_vals) / len(w_vals),
                "loser_mean": sum(l_vals) / len(l_vals),
                "delta": sum(w_vals) / len(w_vals) - sum(l_vals) / len(l_vals),
                "mwu_p_value": mann_whitney_u_p(w_vals, l_vals),
            }
            # §6 falsified cross-check
            hit = cross_check_falsified(key)
            row["falsified_hit"] = hit
            numeric_rows.append(row)
        sleeve_data["winner_vs_loser_numeric"] = numeric_rows

        # §4 categorical (descriptive only, p-value 留 L5.1)
        cat_keys = ["sector_sw1", "phase", "market_trend_on", "market", "ma_short_above_long"]
        cat_data = {}
        for key in cat_keys:
            w_counts = Counter(
                t["entry_features"][key] for t in winners
                if t.get("entry_features") and key in t["entry_features"]
            )
            l_counts = Counter(
                t["entry_features"][key] for t in losers
                if t.get("entry_features") and key in t["entry_features"]
            )
            if not w_counts and not l_counts:
                continue
            cat_data[key] = {"winners": dict(w_counts), "losers": dict(l_counts)}
        sleeve_data["winner_vs_loser_categorical"] = cat_data

        # §5 exit_features 分布
        exit_types_w = Counter(
            t.get("exit_features", {}).get("exit_type") for t in winners
            if t.get("exit_features")
        )
        exit_types_l = Counter(
            t.get("exit_features", {}).get("exit_type") for t in losers
            if t.get("exit_features")
        )
        sleeve_data["exit_summary"] = {
            "exit_type_winners": dict(exit_types_w),
            "exit_type_losers": dict(exit_types_l),
        }
        sleeve_data["warnings"] = []
        report["sleeves"][sleeve] = sleeve_data

    return report


def render_markdown(report: dict) -> str:
    lines: list[str] = []
    lines.append(f"# 实盘 Retrospective 报表 ({report['asof']})")
    lines.append("")
    lines.append(f"min_sample = {report['min_sample']}")
    lines.append("")

    has_data = any(s.get("n_closed", 0) > 0 for s in report["sleeves"].values())
    if not has_data:
        lines.append("⚠ **无 closed trade** — 实盘启动以来无任何 exit 落地, 无数据可供分析.")
        lines.append("")
    for sleeve, data in report["sleeves"].items():
        lines.append(f"## {sleeve}")
        lines.append(f"- n_closed = **{data['n_closed']}**")
        if data["n_closed"] == 0:
            lines.append("")
            continue

        # §2.5 alpha_summary 不被 sample_sufficient gating — N=1 也算
        # (单笔 α = pnl - benchmark, descriptive, 不出统计学结论)
        alpha = data.get("alpha_summary")
        if alpha and alpha.get("benchmark_name"):
            if alpha.get("avg_alpha_pct") is not None:
                lines.append(
                    f"- **α (vs {alpha['benchmark_name']})**: "
                    f"avg pnl - avg benchmark = "
                    f"{alpha['avg_alpha_pct']*100:+.2f}%  "
                    f"(benchmark avg {alpha.get('avg_benchmark_pnl_pct', 0)*100:+.2f}%, "
                    f"α>0 笔数 {alpha['n_alpha_positive']}/{alpha['n_with_alpha']})"
                )
            else:
                lines.append(f"- α: {alpha.get('reason', '不可用')} (benchmark={alpha['benchmark_name']})")

        if not data["sample_sufficient"]:
            lines.append(f"- ⚠ **样本量不足** (N < {report['min_sample']}); 跳过分布差段")
            for w in data.get("warnings", []):
                lines.append(f"- {w}")
            lines.append("")
            continue

        # §2 pnl
        s = data["pnl_summary"]
        lines.append(f"- win_rate = {s['win_rate']:.2%}" if s["win_rate"] is not None else "- win_rate = n/a")
        if s["avg_win_pct"] is not None:
            lines.append(f"- avg_win_pct = {s['avg_win_pct']:+.2%}")
        if s["avg_loss_pct"] is not None:
            lines.append(f"- avg_loss_pct = {s['avg_loss_pct']:+.2%}")
        lines.append("")

        # §3 numeric
        nrows = data.get("winner_vs_loser_numeric") or []
        if nrows:
            lines.append("### §3 Winner vs Loser — numeric entry_features")
            lines.append("")
            lines.append("| feature | win_n | los_n | win_mean | los_mean | delta | MWU p | ⚠ |")
            lines.append("|---|---|---|---|---|---|---|---|")
            for r in nrows:
                p = r["mwu_p_value"]
                p_str = f"{p:.3f}" if p is not None else "n/a"
                sig = "⚠ p<0.05" if (p is not None and p < 0.05) else ""
                falsified = ""
                if r.get("falsified_hit"):
                    falsified = f"⚠ SOFT-FALSIFY [{r['falsified_hit']['doc_ref']}]"
                tag = (sig + " " + falsified).strip() or ""
                lines.append(
                    f"| `{r['feature']}` | {r['winner_n']} | {r['loser_n']} | "
                    f"{r['winner_mean']:.4f} | {r['loser_mean']:.4f} | "
                    f"{r['delta']:+.4f} | {p_str} | {tag} |"
                )
            lines.append("")

        # §4 categorical
        cat = data.get("winner_vs_loser_categorical") or {}
        if cat:
            lines.append("### §4 Winner vs Loser — categorical (descriptive, p-value 留 L5.1)")
            lines.append("")
            for key, d in cat.items():
                lines.append(f"**{key}**: winners={d['winners']} / losers={d['losers']}")
            lines.append("")

        # §5 exit
        ex = data.get("exit_summary") or {}
        if ex:
            lines.append("### §5 exit_features 分布")
            lines.append(f"- winners: {ex.get('exit_type_winners')}")
            lines.append(f"- losers : {ex.get('exit_type_losers')}")
            lines.append("")

    # §6 footer
    lines.append("---")
    lines.append(f"_{report['footer']}_")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="实盘 retrospective 报表 (L5 of self_learning_pipeline)")
    p.add_argument("--since", default="2026-05-22", help="closed trade 起始日 (default 实盘启动)")
    p.add_argument("--min-sample", type=int, default=10, help="< N 时 warn 不出分布差 (Backstop #3)")
    p.add_argument("--output", choices=["md", "json", "both"], default="both")
    p.add_argument("--out-dir", default="logs")
    args = p.parse_args(argv)

    since_dt = date.fromisoformat(args.since)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    asof_str = datetime.now().strftime("%Y-%m-%d")

    closed = fetch_closed_trades(since_dt)
    report = build_report(closed, min_sample=args.min_sample)

    if args.output in ("md", "both"):
        md = render_markdown(report)
        md_path = out_dir / f"learn_{asof_str}.md"
        md_path.write_text(md, encoding="utf-8")
        print(f"[learn] markdown → {md_path}")
    if args.output in ("json", "both"):
        json_path = out_dir / f"learn_{asof_str}.json"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[learn] json     → {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
