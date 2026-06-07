"""quant_system 运营数据层（Postgres / OLTP）。

三层解耦的共享契约：compute 层写、backend 层读，都经由这里的 ORM 模型。
价格 K 线仍走 DuckDB（OLAP），不在此层。
"""

from quant_system.db.models import (
    Base,
    JournalSnapshot,
    JournalTrade,
    PortfolioHistory,
    Position,
    Signal,
    StrategyRun,
)
from quant_system.db.session import get_engine, get_sessionmaker, session_scope

__all__ = [
    "Base",
    "StrategyRun",
    "Signal",
    "Position",
    "JournalTrade",
    "JournalSnapshot",
    "PortfolioHistory",
    "get_engine",
    "get_sessionmaker",
    "session_scope",
]
