"""统一数据层. 当前提供 DuckDB 价格存储."""
from quant_system.data.duckdb_store import DuckDBStore, get_default_store

__all__ = ["DuckDBStore", "get_default_store"]
