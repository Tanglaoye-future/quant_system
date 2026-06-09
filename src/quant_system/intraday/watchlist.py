"""daily watchlist 持久化 —— daily_equity 写, intraday 读.

文件:
  data/intraday/equity_watchlist.json     (PR2)
  data/intraday/zhuang_watchlist.json     (PR3, 留空白)

schema 见 docs/specs/pr2_intraday_watchlist_breakout.md '#Watchlist 文件格式'.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional


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
