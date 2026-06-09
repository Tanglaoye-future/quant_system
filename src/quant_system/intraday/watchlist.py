"""daily persistent state — daily_equity/zhuang 写, intraday 读.

文件:
  data/intraday/equity_watchlist.json     (PR2 breakout alert)
  data/intraday/pending_entries_equity.json  (T+1 open entry)
  data/intraday/pending_entries_zhuang.json  (T+1 open entry, zhuang)

schema: docs/specs/pr2_intraday_watchlist_breakout.md + feat/t1-open-entry.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional


@dataclass
class WatchlistCandidate:
    """daily 一个候选股的快照 (T 日 EOD 写入, T+1 盘中消费)."""
    symbol: str
    name: str
    reference_high: float           # T 日 high → T+1 突破基线
    reference_close: float          # T 日 close (展示用)
    entry_price_suggested: float    # daily 给的入场参考
    stop_loss_suggested: Optional[float] = None
    take_profit_suggested: Optional[float] = None
    factor_score: float = 0.0
    reasons: list[str] = field(default_factory=list)


@dataclass
class Watchlist:
    asof_date: str          # YYYY-MM-DD, daily 跑的那天 (T)
    strategy: str           # "equity_factor" / "zhuang"
    market: str             # "a_share" / ...
    candidates: list[WatchlistCandidate] = field(default_factory=list)


def dump_watchlist(wl: Watchlist, path: Path) -> None:
    """覆盖式写; 自动建父目录."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "asof_date": wl.asof_date,
        "strategy": wl.strategy,
        "market": wl.market,
        "candidates": [asdict(c) for c in wl.candidates],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_watchlist(path: Path) -> Optional[Watchlist]:
    """读取 watchlist; 文件不存在 / 解析失败 → None."""
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        cands = [
            WatchlistCandidate(**c) for c in (raw.get("candidates") or [])
        ]
        return Watchlist(
            asof_date=str(raw.get("asof_date", "")),
            strategy=str(raw.get("strategy", "")),
            market=str(raw.get("market", "")),
            candidates=cands,
        )
    except Exception:
        return None


def is_watchlist_stale(wl: Watchlist, today: date, max_age_days: int = 5) -> bool:
    """asof_date 超过 max_age_days 自然日 → stale, intraday 应跳过."""
    try:
        wl_date = datetime.strptime(wl.asof_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return True
    return (today - wl_date) > timedelta(days=max_age_days)


# ── T+1 开盘入场 (feat/t1-open-entry) ───────────────────────────────────

@dataclass
class PendingEntry:
    """D 日检测到入场信号 → 不立即 open_trade, 写到 pending file;
    D+1 日 EOD 执行 Step 0: 读 pending file → fetch open → open_trade(open 价).

    TradeOpen 字段子集 — 够重建 open_trade 调用.
    """
    symbol: str
    name: str
    market: str
    strategy: str
    entry_price_signal: float          # D 日 close (信号参考价)
    stop_loss: float
    take_profit: float
    factor_score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    entry_features: Optional[dict] = None
    entry_bar_date: str = ""           # 实际 K 线日 (entry_date_actual)

    # zhuang 专属 (nullable — equity 路径不填)
    accumulation_score: Optional[float] = None
    phase: Optional[str] = None
    atr_at_entry: Optional[float] = None


@dataclass
class PendingEntryManifest:
    asof_date: str
    market: str
    strategy: str
    entries: list[PendingEntry] = field(default_factory=list)


def dump_pending_entries(m: PendingEntryManifest, path: Path) -> None:
    """覆盖式写; 自动建父目录."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "asof_date": m.asof_date,
        "market": m.market,
        "strategy": m.strategy,
        "entries": [asdict(e) for e in m.entries],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_pending_entries(path: Path) -> Optional[PendingEntryManifest]:
    """读取 pending entries; 文件不存在 / 解析失败 → None."""
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = [
            PendingEntry(**e) for e in (raw.get("entries") or [])
        ]
        return PendingEntryManifest(
            asof_date=str(raw.get("asof_date", "")),
            market=str(raw.get("market", "")),
            strategy=str(raw.get("strategy", "")),
            entries=entries,
        )
    except Exception:
        return None
