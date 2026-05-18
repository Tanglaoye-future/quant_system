"""
统一日线数据存储 (DuckDB).

替代多策略子目录里独立的 CSV/parquet 缓存——所有 A 股 / HK / US 日线集中
在 ``data/quant.duckdb`` 单文件中。表设计支持快速按 (market, code, date)
范围查询与跨股票分析。

每个 loader 在 hot path 上先查 DB，未命中再 fall back 到原 CSV/parquet
（保留作灾备）。

Schema:
    daily_bars(market, code, date, open, high, low, close, volume, turnover_rate)
    PRIMARY KEY (market, code, date)
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore


DEFAULT_DB_PATH = Path("data/quant.duckdb")


class DuckDBStore:
    """轻量 DuckDB 价格存储. 线程安全 (一个 db 实例 + 锁)."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if duckdb is None:
            raise ImportError("duckdb 未安装。pip install duckdb")
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._con: duckdb.DuckDBPyConnection | None = None

    # ── 连接 ────────────────────────────────────────────────────────────

    def _connect(self) -> "duckdb.DuckDBPyConnection":
        if self._con is None:
            self._con = duckdb.connect(str(self.db_path))
            self._init_schema(self._con)
        return self._con

    def _init_schema(self, con: "duckdb.DuckDBPyConnection") -> None:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_bars (
                market  VARCHAR NOT NULL,
                code    VARCHAR NOT NULL,
                date    DATE    NOT NULL,
                open    DOUBLE,
                high    DOUBLE,
                low     DOUBLE,
                close   DOUBLE,
                volume  DOUBLE,
                turnover_rate DOUBLE,
                PRIMARY KEY (market, code, date)
            )
            """
        )

    def close(self) -> None:
        with self._lock:
            if self._con is not None:
                self._con.close()
                self._con = None

    # ── 写入 ────────────────────────────────────────────────────────────

    REQUIRED_COLS = ("date", "open", "high", "low", "close", "volume")

    def insert_daily(
        self, market: str, code: str, df: pd.DataFrame, replace: bool = True
    ) -> int:
        """
        Upsert (market, code, date) 行. 返回写入行数.

        df 列至少包含 date/open/high/low/close/volume; turnover_rate 可选.
        date 接受 string 或 datetime, 内部转 DATE.
        """
        if df is None or df.empty:
            return 0
        for col in self.REQUIRED_COLS:
            if col not in df.columns:
                raise ValueError(f"df 缺列 {col}; got {list(df.columns)}")

        d = df.copy()
        d["date"] = pd.to_datetime(d["date"]).dt.date  # → python date
        d["market"] = market
        d["code"] = str(code).zfill(6) if market == "a_share" else str(code)
        if "turnover_rate" not in d.columns:
            d["turnover_rate"] = None
        d = d[["market", "code", "date", "open", "high", "low", "close",
               "volume", "turnover_rate"]]
        # 强制数值列 dtype
        for col in ["open", "high", "low", "close", "volume", "turnover_rate"]:
            d[col] = pd.to_numeric(d[col], errors="coerce")

        with self._lock:
            con = self._connect()
            if replace:
                # DuckDB 不支持 ON CONFLICT REPLACE 在所有版本里；用 DELETE+INSERT
                con.execute(
                    "DELETE FROM daily_bars WHERE market=? AND code=? "
                    "AND date BETWEEN ? AND ?",
                    [market, d["code"].iloc[0],
                     d["date"].min(), d["date"].max()],
                )
            con.register("incoming", d)
            con.execute("INSERT INTO daily_bars SELECT * FROM incoming")
            con.unregister("incoming")
        return len(d)

    def bulk_insert_daily(
        self, market: str, df: pd.DataFrame, replace: bool = False
    ) -> int:
        """
        批量写入: df 含 code 列, 一次写多只股票. 大幅快过逐 code insert_daily.
        replace=True 会先 DELETE 范围内行 (耗时), False 直接 INSERT 假定无重复.
        """
        if df is None or df.empty:
            return 0
        need = list(self.REQUIRED_COLS) + ["code"]
        for col in need:
            if col not in df.columns:
                raise ValueError(f"df 缺列 {col}; got {list(df.columns)}")
        d = df.copy()
        d["date"] = pd.to_datetime(d["date"]).dt.date
        d["market"] = market
        if market == "a_share":
            d["code"] = d["code"].astype(str).str.zfill(6)
        else:
            d["code"] = d["code"].astype(str)
        if "turnover_rate" not in d.columns:
            d["turnover_rate"] = None
        d = d[["market", "code", "date", "open", "high", "low", "close",
               "volume", "turnover_rate"]]
        for col in ["open", "high", "low", "close", "volume", "turnover_rate"]:
            d[col] = pd.to_numeric(d[col], errors="coerce")

        with self._lock:
            con = self._connect()
            con.register("incoming", d)
            if replace:
                con.execute(
                    "DELETE FROM daily_bars d "
                    "USING incoming i "
                    "WHERE d.market=i.market AND d.code=i.code AND d.date=i.date"
                )
            con.execute("INSERT INTO daily_bars SELECT * FROM incoming")
            con.unregister("incoming")
        return len(d)

    # ── 读取 ────────────────────────────────────────────────────────────

    def get_daily(
        self,
        market: str,
        code: str,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """
        返回单只股票日线 DataFrame.
        列: date(datetime64), open, high, low, close, volume, turnover_rate.
        未命中返回空 DataFrame.
        """
        code = str(code).zfill(6) if market == "a_share" else str(code)
        params: list = [market, code]
        sql = (
            "SELECT date, open, high, low, close, volume, turnover_rate "
            "FROM daily_bars WHERE market=? AND code=?"
        )
        if start:
            sql += " AND date >= ?"
            params.append(start)
        if end:
            sql += " AND date <= ?"
            params.append(end)
        sql += " ORDER BY date"
        with self._lock:
            con = self._connect()
            df = con.execute(sql, params).fetchdf()
        # 与 zhuang/equity_factor 现有接口对齐: date 列为 datetime64
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
        return df

    def has_code(self, market: str, code: str) -> bool:
        """检查该 (market, code) 在 db 中是否有数据."""
        code = str(code).zfill(6) if market == "a_share" else str(code)
        with self._lock:
            con = self._connect()
            row = con.execute(
                "SELECT 1 FROM daily_bars WHERE market=? AND code=? LIMIT 1",
                [market, code],
            ).fetchone()
        return row is not None

    def list_codes(self, market: str) -> list[str]:
        with self._lock:
            con = self._connect()
            rows = con.execute(
                "SELECT DISTINCT code FROM daily_bars WHERE market=? ORDER BY code",
                [market],
            ).fetchall()
        return [r[0] for r in rows]

    def stats(self) -> pd.DataFrame:
        """每个 market 的行数 / 股票数 / 日期范围."""
        with self._lock:
            con = self._connect()
            return con.execute(
                "SELECT market, COUNT(*) AS rows, "
                "COUNT(DISTINCT code) AS codes, "
                "MIN(date) AS first_date, MAX(date) AS last_date "
                "FROM daily_bars GROUP BY market ORDER BY market"
            ).fetchdf()


# ── 单例 ────────────────────────────────────────────────────────────────

_default_store: DuckDBStore | None = None
_default_store_lock = threading.Lock()


def get_default_store(db_path: Path | str | None = None) -> DuckDBStore:
    """进程级默认 DB 单例. 多 loader 共享同一连接."""
    global _default_store
    with _default_store_lock:
        if _default_store is None:
            _default_store = DuckDBStore(db_path)
    return _default_store
