"""Strategy-market 矩阵领域模型.

Frozen dataclasses — 不可变, 纯数据, 无副作用。供 resolver / API / 前端消费。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CellStatus(str, Enum):
    ACTIVE = "active"           # daily cron 运行, 数据存在且新鲜
    AVAILABLE = "available"     # 架构支持, CLI 可跑 (不在 daily)
    BLOCKED = "blocked"         # 架构就绪, 外部阻断 (数据 / broker 权限等)
    DEPRECATED = "deprecated"   # 曾运行, 已退役 (e.g. equity_us)
    UNSUPPORTED = "unsupported" # 根本性架构不兼容


@dataclass(frozen=True)
class StrategyCell:
    strategy_name: str          # "equity_momentum"
    strategy_label: str         # "中线 momentum"
    strategy_kind: str          # "bottomup_timing" / "bull_call_spread" / "zhuang"
    market_name: str            # "a_share"
    market_label: str           # "A 股"
    status: CellStatus
    config_enabled: bool = False
    has_data: bool = False
    data_file: str = ""         # report/data/<name>.json (如存在)
    data_date: str = ""         # JSON 内 date 字段
    blocker_reason: str = ""    # status=blocked/unsupported 时的原因
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketGroup:
    market_name: str
    market_label: str
    display_order: int
    index_info: dict[str, Any]  # 基准指数快照 (close, ma, regime)
    cells: list[StrategyCell]
