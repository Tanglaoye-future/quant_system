"""Serving 侧 DAO 层 — 唯一从 backend 读 DB 的地方（三层解耦 Phase 1）。

把 strategy_runs / signals / positions 还原成前端既有的 quant/options/zhuang
JSON 形状，让 API 路由对"数据来自 DB 还是 JSON 文件"无感知。

无相关行时返回 None，由路由回退到 report/data/*.json（过渡安全网，见 routes._db_or_json）。

—— 行 ↔ JSON 字段映射约定（写侧 Phase 2 也遵循同一约定）——
- Signal:   归一列 code/name/score/reason/action；策略特有字段(entry_price/
            stop_loss/take_profit/suggested_action ...) 进 payload。
            读出 = {code, name, score, reason, (action 若有), **payload}
- Position: 归一列 code/name/action/entry_date/hold_days/pnl_pct；其余进 payload。
- options:  全部标量在 strategy_runs.metrics；读出 = {date, market, **metrics}
- zhuang:   候选落 signals(因子分项进 payload, total=score)；
            汇总(universe_size/candidates_count/market_trend) 在 metrics。
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_system.db import Position, Signal, StrategyRun

# (market, strategy_kind, 展示标签) —— 与 routes._merge_quant 的 JSON 源顺序/标签一致
_QUANT_SOURCES: list[tuple[str, str, str]] = [
    ("hk_share", "bottomup_timing", "HK 港股 · momentum"),
    ("a_share", "bottomup_timing", "A 股 · momentum"),
    ("a_share", "mean_reversion", "A 股 · mean-reversion"),
]


def _latest_run(
    session: Session, strategy_kind: str, market: Optional[str] = None
) -> Optional[StrategyRun]:
    """同一 (kind[, market]) 取 run_date 最新的一次跑批。"""
    stmt = select(StrategyRun).where(StrategyRun.strategy_kind == strategy_kind)
    if market is not None:
        stmt = stmt.where(StrategyRun.market == market)
    stmt = stmt.order_by(StrategyRun.run_date.desc(), StrategyRun.id.desc()).limit(1)
    return session.scalars(stmt).first()


def _signal_to_dict(sig: Signal) -> dict[str, Any]:
    out: dict[str, Any] = {"code": sig.code, "name": sig.name or ""}
    if sig.score is not None:
        out["score"] = sig.score
    if sig.reason is not None:
        out["reason"] = sig.reason
    if sig.action is not None:
        out["action"] = sig.action
    out.update(sig.payload or {})
    return out


def _position_to_dict(pos: Position) -> dict[str, Any]:
    out: dict[str, Any] = {
        "code": pos.code,
        "name": pos.name or "",
        "entry_date": str(pos.entry_date) if pos.entry_date is not None else "",
        "hold_days": pos.hold_days,
        "pnl_pct": pos.pnl_pct,
        "action": pos.action,
    }
    out.update(pos.payload or {})
    return out


def run_to_payload(run: StrategyRun) -> dict[str, Any]:
    """单个 run → 它对应的 daily JSON 文件形状（按 strategy_kind 分派）。

    供双写一致性校验逐 run 比对（与合并的 quant_payload 不同，这是单文件粒度）。
    """
    if run.strategy_kind == "bull_call_spread":
        return {"date": str(run.run_date), "market": run.market, **(run.metrics or {})}

    if run.strategy_kind == "zhuang":
        metrics = run.metrics or {}
        candidates = []
        for sig in run.signals:
            item: dict[str, Any] = {"code": sig.code}
            item.update(sig.payload or {})
            if sig.score is not None:
                item["total"] = sig.score
            candidates.append(item)
        return {
            "date": str(run.run_date),
            "market": run.market,
            "universe_size": metrics.get("universe_size"),
            "candidates_count": metrics.get("candidates_count"),
            "market_trend": metrics.get("market_trend"),
            "top_candidates": candidates,
            "positions": [_position_to_dict(p) for p in run.positions],
        }

    # equity_factor (bottomup_timing / mean_reversion)
    out: dict[str, Any] = {
        "date": str(run.run_date),
        "market": run.market,
        "strategy_kind": run.strategy_kind,
        "strategy_name": run.strategy_name,
        "market_gate": run.market_gate,
        "market_gate_msg": run.market_gate_msg,
    }
    out.update(run.metrics or {})  # strategy / benchmark_close / benchmark_ma60
    out["signals"] = [_signal_to_dict(s) for s in run.signals]
    out["positions"] = [_position_to_dict(p) for p in run.positions]
    return out


def quant_payload(session: Session) -> Optional[dict[str, Any]]:
    """合并 HK/A momentum + A mean-reversion 最新跑批 → /api/report/quant 形状。"""
    runs: list[tuple[StrategyRun, str]] = []
    for market, kind, label in _QUANT_SOURCES:
        run = _latest_run(session, kind, market)
        if run is not None:
            runs.append((run, label))
    if not runs:
        return None

    merged_date = ""
    merged_market = ""
    merged_gate: Optional[bool] = None
    merged_gate_msg = ""
    signals: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []

    for run, label in runs:
        merged_date = str(run.run_date)
        merged_market = merged_market or run.market
        if run.market_gate is not None:
            merged_gate = run.market_gate
            merged_gate_msg = run.market_gate_msg or ""
        for sig in run.signals:
            d = _signal_to_dict(sig)
            d["_source"] = label
            signals.append(d)
        for pos in run.positions:
            d = _position_to_dict(pos)
            d["_source"] = label
            positions.append(d)

    return {
        "date": merged_date,
        "market": merged_market,
        "market_gate": merged_gate,
        "market_gate_msg": merged_gate_msg,
        "benchmark_close": "—",
        "benchmark_ma60": "—",
        "signals": signals,
        "positions": positions,
    }


def options_payload(session: Session) -> Optional[dict[str, Any]]:
    """最新 bull_call_spread 跑批 → /api/report/options 形状。"""
    run = _latest_run(session, "bull_call_spread")
    if run is None:
        return None
    return {"date": str(run.run_date), "market": run.market, **(run.metrics or {})}


def zhuang_payload(session: Session) -> Optional[dict[str, Any]]:
    """最新 zhuang 跑批 → /api/report/zhuang 形状（候选来自 signals）。"""
    run = _latest_run(session, "zhuang")
    if run is None:
        return None
    metrics = run.metrics or {}
    candidates = []
    for sig in run.signals:
        item: dict[str, Any] = {"code": sig.code}
        item.update(sig.payload or {})
        if sig.score is not None:
            item["total"] = sig.score
        candidates.append(item)
    return {
        "date": str(run.run_date),
        "market": run.market,
        "universe_size": metrics.get("universe_size"),
        "candidates_count": metrics.get("candidates_count", len(candidates)),
        "market_trend": metrics.get("market_trend"),
        "top_candidates": candidates,
        "positions": [_position_to_dict(p) for p in run.positions],
    }
