"""策略-市场矩阵解析器.

resolve_matrix() 是唯一公开入口。流程:
  1. _discover_from_config()   — config 层已知的 (strategy, market) deployment
  2. _discover_from_filesystem() — report/data/*.json 存在的数据文件
  3. _merge_status()           — 合并 status 判定
  4. _load_declarations()      — cells.yaml 补充 UNSUPPORTED/BLOCKED 声明
  5. _group_and_sort()         — 分组 + 排序 → list[MarketGroup]
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from quant_system.config import PROJECT_ROOT, load_config
from quant_system.report.registry.domain import CellStatus, MarketGroup, StrategyCell

REPORT_DATA = PROJECT_ROOT / "report" / "data"
CELLS_DECL = PROJECT_ROOT / "config" / "cells.yaml"

# ── 显示名称映射 ────────────────────────────────────────────────────────

_MARKET_LABELS: dict[str, str] = {
    "a_share": "A 股", "hk_share": "港股", "us_share": "美股",
    "us_qqq": "美股", "hk_small": "港股", "hk_hsi": "港股",
}
_MARKET_ORDER: dict[str, int] = {"a_share": 0, "hk_share": 1, "hk_small": 1, "hk_hsi": 1, "us_share": 2, "us_qqq": 2}

_STRATEGY_LABELS: dict[str, str] = {
    "equity_momentum": "中线 momentum", "equity_hk_momentum": "中线 momentum (HK)",
    "equity_us_momentum": "中线 momentum (US)", "equity_mean_reversion": "中线 mean-reversion",
    "options_bull_call_spread": "期权 Bull Call Spread", "zhuang": "庄股跟庄",
}
_STRATEGY_KIND: dict[str, str] = {
    "equity_momentum": "bottomup_timing", "equity_hk_momentum": "bottomup_timing",
    "equity_us_momentum": "bottomup_timing", "equity_mean_reversion": "mean_reversion",
    "options_bull_call_spread": "bull_call_spread", "zhuang": "zhuang",
}


def _label_market(name: str) -> str:
    return _MARKET_LABELS.get(name, name)


def _normalize_market(name: str) -> str:
    """将子市场归一化到三大市场: hk_small→hk_share, us_qqq→us_share."""
    m = {
        "hk_small": "hk_share", "hk_hsi": "hk_share",
        "us_qqq": "us_share",
    }
    return m.get(name, name)


def _normalize_strategy(name: str) -> str:
    """归一化策略名。mean_reversion → equity_mean_reversion."""
    if name == "mean_reversion":
        return "equity_mean_reversion"
    return name


def _label_strategy(name: str) -> str:
    return _STRATEGY_LABELS.get(name, name)


def _kind_of(name: str) -> str:
    return _STRATEGY_KIND.get(name, "unknown")


# ── config 扫描 ─────────────────────────────────────────────────────────

def _discover_from_config() -> dict[tuple[str, str], dict[str, Any]]:
    """从 config 文件发现所有 (strategy_name, market_name) deployment.

    覆盖:
      - equity_factor.yaml + options.yaml (split config → _assemble_split → deployments[][])
      - zhuang.yaml (inline markets: dict, 不走 split config)
    """
    cells: dict[tuple[str, str], dict[str, Any]] = {}

    # equity_factor split config
    try:
        eq_cfg = load_config(PROJECT_ROOT / "config" / "equity_factor.yaml")
        deps = eq_cfg.get("deployments") or {}
        for sname, markets in deps.items():
            for mname, entry in markets.items():
                if not isinstance(entry, dict):
                    continue
                cells[(sname, mname)] = {
                    "enabled": bool(entry.get("enabled")),
                    "kind": entry.get("strategy_kind") or _kind_of(sname),
                }
    except Exception:
        pass

    # options split config
    try:
        opt_cfg = load_config(PROJECT_ROOT / "config" / "options.yaml")
        deps = opt_cfg.get("deployments") or {}
        for sname, markets in deps.items():
            for mname, entry in markets.items():
                if not isinstance(entry, dict):
                    continue
                cells[(sname, mname)] = {
                    "enabled": bool(entry.get("enabled")),
                    "kind": entry.get("strategy_kind") or _kind_of(sname),
                }
    except Exception:
        pass

    # zhuang inline config
    try:
        with open(PROJECT_ROOT / "config" / "zhuang.yaml", encoding="utf-8") as f:
            zhuang_cfg = yaml.safe_load(f) or {}
        for mname, mcfg in (zhuang_cfg.get("markets") or {}).items():
            if not isinstance(mcfg, dict):
                continue
            cells[("zhuang", mname)] = {
                "enabled": bool(mcfg.get("enabled")),
                "kind": "zhuang",
            }
    except Exception:
        pass

    # equity_mean_reversion — 无独立 strategy yaml; 从 daily_equity kind 推断.
    # A_MR_RETIRED 2026-06-16: v7 配比 A_mr 0% (不投), daily 跳过, 前端隐藏.
    # 代码保留, 重启时 enabled 改 True + 取消 run_daily.sh 里 A_mean_reversion 行的注释.
    if ("equity_momentum", "a_share") in cells:
        cells[("equity_mean_reversion", "a_share")] = {
            "enabled": False, "kind": "mean_reversion",
        }

    return cells


# ── 文件系统扫描 ────────────────────────────────────────────────────────

def _discover_from_filesystem() -> dict[tuple[str, str], dict[str, Any]]:
    """扫描 report/data/*.json, 按内部字段归因到 (strategy_name, market)."""
    cells: dict[tuple[str, str], dict[str, Any]] = {}
    if not REPORT_DATA.exists():
        return cells

    for f in sorted(REPORT_DATA.glob("*.json")):
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue

        sname = payload.get("strategy_name") or payload.get("strategy")
        market = payload.get("market") or ""

        # 从文件名推断 (options)
        if not sname and f.stem.startswith("options"):
            sname = "options_bull_call_spread"
            # options.json → us_qqq; options_{m}.json → {m}
            if f.stem == "options":
                market = market or "us_qqq"

        # zhuang
        if f.stem == "zhuang":
            sname = sname or "zhuang"
            market = "a_share"

        # quant_{market}_{kind}.json → 通过 kind 反查 strategy_name
        if not sname and f.stem.startswith("quant_"):
            # quant_a_share_bottomup_timing → kind=bottomup_timing
            parts = f.stem.split("_")
            # ['quant', market_part..., kind_part...]
            if len(parts) >= 3:
                market = market or "_".join(parts[1:-1])  # a_share or hk_share
                kind = parts[-1]  # bottomup_timing or mean_reversion

        if not sname:
            # 最后手段: 从 quant_{market}_{kind} 反推
            parts = f.stem.split("_")
            if len(parts) >= 3 and parts[0] == "quant":
                m = "_".join(parts[1:-1])
                k = parts[-1]
                if k == "mean_reversion":
                    sname, market = "equity_mean_reversion", m
                elif k == "bottomup_timing":
                    if m == "hk_share":
                        sname = "equity_hk_momentum"
                    elif m == "us_share":
                        sname = "equity_us_momentum"
                    else:
                        sname = "equity_momentum"
                    market = m

        if not sname:
            continue
        market = market or "a_share"

        cells[(sname, market)] = {
            "file": f.name,
            "date": payload.get("date", ""),
            "signals_count": len(payload.get("signals") or []),
            "positions_count": len(payload.get("positions") or []),
            "candidates_count": payload.get("candidates_count", 0),
            "market_gate": payload.get("market_gate"),
            "ivr": payload.get("ivr"),
            "iv_mode": payload.get("iv_mode", ""),
            "signal_grade": payload.get("signal_grade", ""),
            "qqq_price": payload.get("qqq_price"),
            "qqq_rsi": payload.get("qqq_rsi"),
            "qqq_bullish": payload.get("qqq_bullish"),
            "reason": payload.get("reason", ""),
        }

    return cells


# ── DB 扫描（三层解耦 Phase 3：matrix/markets/health 改读 Postgres）────────

def _sname_from_db_run(strategy_kind: str, strategy_name: str | None) -> str:
    """DB run → registry strategy_name（与 _discover_from_filesystem 归因一致）。"""
    if strategy_kind == "bull_call_spread":
        return "options_bull_call_spread"  # fs 从文件名 options 推得，DB 按 kind
    if strategy_kind == "zhuang":
        return "zhuang"
    return strategy_name or "equity_momentum"


def _runs_to_cells(runs) -> dict[tuple[str, str], dict[str, Any]]:
    """StrategyRun 列表 → 与 _discover_from_filesystem 同款 cells 字典（取每 (market,kind) 最新）。"""
    latest: dict[tuple[str, str], Any] = {}
    for run in runs:  # 调用方按 run_date,id 升序传入 → 后者最新
        latest[(run.market, run.strategy_kind)] = run

    cells: dict[tuple[str, str], dict[str, Any]] = {}
    for (market, kind), run in latest.items():
        sname = _sname_from_db_run(kind, run.strategy_name)
        # zhuang 候选/options signal 不是买入信号；与 JSON 文件无 signals/positions 数组对齐 → 0
        if kind in ("bottomup_timing", "mean_reversion"):
            sig_c, pos_c = len(run.signals), len(run.positions)
        else:
            sig_c, pos_c = 0, 0
        m = run.metrics or {}
        cells[(sname, market)] = {
            "date": str(run.run_date),
            "signals_count": sig_c,
            "positions_count": pos_c,
            "candidates_count": m.get("candidates_count", 0),
            "market_gate": run.market_gate,
            "market_gate_msg": run.market_gate_msg or "",
            "benchmark_close": m.get("benchmark_close", "—"),
            "benchmark_ma60": m.get("benchmark_ma60", "—"),
            "market_trend": m.get("market_trend"),
            "ivr": m.get("ivr"),
            "iv_mode": m.get("iv_mode", ""),
            "signal_grade": m.get("signal_grade", ""),
            "qqq_price": m.get("qqq_price"),
            "qqq_rsi": m.get("qqq_rsi"),
            "qqq_bullish": m.get("qqq_bullish"),
            "reason": m.get("reason", ""),
        }
    return cells


def _discover_from_db() -> dict[tuple[str, str], dict[str, Any]] | None:
    """DB-first 数据发现。DB 不可达返回 None（caller 回退文件系统冷备）。"""
    try:
        from sqlalchemy import select

        from quant_system.db import StrategyRun
        from quant_system.db.session import session_scope

        with session_scope() as session:
            runs = session.scalars(
                select(StrategyRun).order_by(StrategyRun.run_date, StrategyRun.id)
            ).all()
            return _runs_to_cells(runs)
    except Exception:
        return None


# ── cells.yaml 声明 ─────────────────────────────────────────────────────

def _load_declarations() -> list[dict[str, Any]]:
    if not CELLS_DECL.exists():
        return []
    with open(CELLS_DECL, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return raw.get("declarations") or []


# ── 状态合并 ────────────────────────────────────────────────────────────

def _merge_status(
    cfg_cells: dict[tuple[str, str], dict],
    fs_cells: dict[tuple[str, str], dict],
    decls: list[dict],
) -> list[StrategyCell]:
    """合并 config / filesystem / declarations 三重来源, 为每个 (s, m) 定 status."""
    # 先归一化 key
    def _norm_key(k: tuple[str, str]) -> tuple[str, str]:
        return (_normalize_strategy(k[0]), _normalize_market(k[1]))

    cfg_norm: dict[tuple[str, str], dict] = {}
    for k, v in cfg_cells.items():
        cfg_norm.setdefault(_norm_key(k), {}).update(v)

    fs_norm: dict[tuple[str, str], dict] = {}
    for k, v in fs_cells.items():
        fs_norm.setdefault(_norm_key(k), {}).update(v)

    decl_map: dict[tuple[str, str], dict] = {}
    for d in decls:
        key = (_normalize_strategy(d.get("strategy", "")), _normalize_market(d.get("market", "")))
        decl_map[key] = d

    result: list[StrategyCell] = []
    all_keys: set[tuple[str, str]] = set(cfg_norm.keys()) | set(fs_norm.keys()) | set(decl_map.keys())

    for (sname, mname) in sorted(all_keys):
        cfg = cfg_norm.get((sname, mname)) or {}
        fs = fs_norm.get((sname, mname)) or {}
        decl = decl_map.get((sname, mname)) or {}

        config_enabled = bool(cfg.get("enabled"))
        has_data = bool(fs)
        decl_status = decl.get("status", "")
        decl_reason = decl.get("reason", "")
        kind = cfg.get("kind") or _kind_of(sname)

        # 判定 status
        if decl_status == "unsupported":
            status = CellStatus.UNSUPPORTED
            reason = decl_reason
        elif decl_status == "blocked":
            status = CellStatus.BLOCKED
            reason = decl_reason
        elif "deprecated" in sname.lower() or not config_enabled and "us_momentum" in sname:
            status = CellStatus.DEPRECATED
            reason = "已退役 — QQQ 被动持有替代"
        elif config_enabled and has_data:
            status = CellStatus.ACTIVE
            reason = ""
        elif config_enabled and not has_data:
            status = CellStatus.AVAILABLE
            reason = "配置已启用但今日无数据"
        elif not config_enabled and has_data:
            status = CellStatus.AVAILABLE
            reason = "可 CLI 运行但不在 daily cron"
        elif not config_enabled and decl_status == "blocked":
            status = CellStatus.BLOCKED
            reason = decl_reason
        else:
            status = CellStatus.AVAILABLE
            reason = ""

        cell = StrategyCell(
            strategy_name=_normalize_strategy(sname),
            strategy_label=_label_strategy(_normalize_strategy(sname)),
            strategy_kind=kind,
            market_name=_normalize_market(mname),
            market_label=_label_market(_normalize_market(mname)),
            status=status,
            config_enabled=config_enabled,
            has_data=has_data,
            data_file=fs.get("file", ""),
            data_date=fs.get("date", ""),
            blocker_reason=reason,
            metrics={
                k: v for k, v in fs.items()
                if k not in ("file", "date")
            },
        )
        result.append(cell)

    # 去重: 归一化后同 (strategy_name, market_name) 的只保留一个,
    # 优先取有 config 的, 其次取有 data 的
    deduped: dict[tuple[str, str], StrategyCell] = {}
    for c in result:
        key = (c.strategy_name, c.market_name)
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = c
        else:
            # 合并: 取更好的状态 (ACTIVE > AVAILABLE > 其它)
            status_rank = {CellStatus.ACTIVE: 0, CellStatus.AVAILABLE: 1, CellStatus.BLOCKED: 2,
                           CellStatus.DEPRECATED: 3, CellStatus.UNSUPPORTED: 4}
            if status_rank.get(c.status, 99) < status_rank.get(existing.status, 99):
                deduped[key] = c
            elif c.has_data and not existing.has_data:
                # 同状态但新 cell 有 data
                deduped[key] = StrategyCell(
                    strategy_name=existing.strategy_name,
                    strategy_label=existing.strategy_label,
                    strategy_kind=existing.strategy_kind,
                    market_name=existing.market_name,
                    market_label=existing.market_label,
                    status=existing.status,
                    config_enabled=c.config_enabled or existing.config_enabled,
                    has_data=c.has_data or existing.has_data,
                    data_file=c.data_file or existing.data_file,
                    data_date=c.data_date or existing.data_date,
                    blocker_reason=existing.blocker_reason,
                    metrics={**existing.metrics, **c.metrics},
                )

    return list(deduped.values())


# ── 分组 + 排序 ─────────────────────────────────────────────────────────

def _group_and_sort(cells: list[StrategyCell]) -> list[MarketGroup]:
    """按 market 分组, 继承首个 ACTIVE cell 的 index 数据。"""
    by_market: dict[str, list[StrategyCell]] = {}
    for c in cells:
        by_market.setdefault(c.market_name, []).append(c)

    groups: list[MarketGroup] = []
    for mname, cell_list in sorted(by_market.items(), key=lambda kv: _MARKET_ORDER.get(kv[0], 99)):
        # index 数据来源 cell：优先选携带市况门的 momentum/options，避免落到
        # mean_reversion（无 market_gate → regime 永远 unknown，前端显示「—」）。
        _index_kind_priority = {
            "bottomup_timing": 0, "bull_call_spread": 1, "zhuang": 2, "mean_reversion": 3,
        }
        index: dict[str, Any] = {}
        index_cells = sorted(
            (c for c in cell_list if c.status == CellStatus.ACTIVE and c.has_data),
            key=lambda c: _index_kind_priority.get(c.strategy_kind, 9),
        )
        for c in index_cells:
            metrics = c.metrics
            if c.strategy_kind == "bull_call_spread":
                index = {
                    "name": "QQQ", "symbol": "QQQ",
                    "close": metrics.get("qqq_price"),
                    "ma200": metrics.get("qqq_ma200"),
                    "regime": "bullish" if metrics.get("qqq_bullish") else "bearish",
                }
            elif c.strategy_kind == "zhuang":
                _mt = metrics.get("market_trend")
                index = {
                    "name": "中证500", "symbol": "000905",
                    "close": "—", "ma": "—",
                    "regime": "ok" if _mt is True else ("closed" if _mt is False else "unknown"),
                }
            else:
                gate = metrics.get("market_gate")
                index = {
                    "name": "沪深300" if mname == "a_share" else ("恒生中国100" if "hk" in mname else "NASDAQ100"),
                    "symbol": "000300" if mname == "a_share" else ("HSCHK100" if "hk" in mname else "NDX"),
                    "close": metrics.get("benchmark_close", "—"),
                    "ma60": metrics.get("benchmark_ma60", "—"),
                    "regime": "ok" if gate is True else ("closed" if gate is False else "unknown"),
                    "regime_msg": metrics.get("market_gate_msg", ""),
                }
            break

        groups.append(MarketGroup(
            market_name=mname,
            market_label=_label_market(mname),
            display_order=_MARKET_ORDER.get(mname, 99),
            index_info=index,
            cells=sorted(cell_list, key=lambda c: (
                0 if c.status == CellStatus.ACTIVE else 1,
                c.strategy_name,
            )),
        ))

    return groups


# ── 公开入口 ────────────────────────────────────────────────────────────

def resolve_matrix() -> tuple[list[StrategyCell], list[MarketGroup]]:
    cfg_cells = _discover_from_config()
    # Phase 3：数据来源 DB-first；DB 不可达才回退扫文件（冷备）。
    data_cells = _discover_from_db()
    if data_cells is None:
        data_cells = _discover_from_filesystem()
    decls = _load_declarations()
    cells = _merge_status(cfg_cells, data_cells, decls)
    groups = _group_and_sort(cells)
    return cells, groups
