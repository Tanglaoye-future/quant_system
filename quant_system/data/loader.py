"""
数据层: A 股 + 港股的统一接口。
所有外部数据源（akshare）都收敛到这里，上层模块不直接 import akshare。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import akshare as ak
import pandas as pd

Market = Literal["a_share", "hk_share"]


class DataLoader:
    def __init__(self, cache_dir: Path, refresh_days: int = 1):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.refresh_days = refresh_days

    # ---------- universe ----------

    def get_universe(self, market: Market, name: str) -> pd.DataFrame:
        """成分股清单, 返回列: code, name"""
        cache = self.cache_dir / f"universe_{market}_{name}.parquet"
        if self._is_fresh(cache):
            return pd.read_parquet(cache)

        if market == "a_share":
            if name == "hs300":
                df = ak.index_stock_cons_csindex(symbol="000300")
                df = df.rename(columns={"成分券代码": "code", "成分券名称": "name"})[["code", "name"]]
            elif name == "zz500":
                df = ak.index_stock_cons_csindex(symbol="000905")
                df = df.rename(columns={"成分券代码": "code", "成分券名称": "name"})[["code", "name"]]
            elif name == "zz1000":
                df = ak.index_stock_cons_csindex(symbol="000852")
                df = df.rename(columns={"成分券代码": "code", "成分券名称": "name"})[["code", "name"]]
            elif name == "a_all":
                # A 股全市场, 排除 ST/退市/9 开头 (B 股或非常规)
                df = ak.stock_info_a_code_name()
                df = df[~df["name"].str.contains("ST", na=False)]
                df = df[~df["code"].str.startswith("9")]
                df = df[["code", "name"]].reset_index(drop=True)
            else:
                raise ValueError(f"未知 A 股 universe: {name}")
        elif market == "hk_share":
            if name == "hsi":
                df = ak.stock_hk_index_components_em(symbol="HSI")
            elif name == "hsce":
                df = ak.stock_hk_index_components_em(symbol="HSCEI")
            else:
                raise ValueError(f"未知 港股 universe: {name}")
            df = df.rename(columns={"代码": "code", "名称": "name"})[["code", "name"]]
        else:
            raise ValueError(f"未知 market: {market}")

        df.to_parquet(cache)
        return df

    # ---------- daily prices ----------

    # 拉取下限: 缓存永远从这一天起, 上层任意 start 都能切片
    FETCH_FLOOR = "2018-01-01"

    def get_daily(
        self,
        market: Market,
        code: str,
        start: str,
        end: str | None = None,
    ) -> pd.DataFrame:
        """日线 OHLCV, 列: date, open, high, low, close, volume.
        缓存命中且范围覆盖 start->end 时直接返回, 否则全量重拉."""
        end = end or datetime.now().strftime("%Y-%m-%d")
        cache = self.cache_dir / f"daily_{market}_{code}.parquet"

        if cache.exists() and self._is_fresh(cache):
            df = pd.read_parquet(cache)
            if len(df) > 0:
                cache_min = df["date"].min()
                # 只要 cache 起点早于 user 请求的 start, 就可以切片返回
                if cache_min <= start:
                    return df[(df["date"] >= start) & (df["date"] <= end)]
            # 缓存范围不够 (cache 起点晚于请求的 start), 落到下面重拉

        if market == "a_share":
            # sina 比 eastmoney 稳定 (eastmoney 高频拉取易触发限流).
            # symbol 需要带交易所前缀: 6 -> sh, 0/3 -> sz, 8 -> bj
            prefix = "sh" if code.startswith("6") else (
                "bj" if code.startswith("8") else "sz"
            )
            raw = ak.stock_zh_a_daily(
                symbol=f"{prefix}{code}",
                start_date=self.FETCH_FLOOR.replace("-", ""),
                end_date=end.replace("-", ""),
                adjust="qfq",
            )
            df = raw[["date", "open", "high", "low", "close", "volume"]].copy()
        elif market == "hk_share":
            raw = ak.stock_hk_daily(symbol=code, adjust="qfq")
            df = raw.rename(columns={
                "date": "date", "open": "open", "high": "high",
                "low": "low", "close": "close", "volume": "volume",
            })[["date", "open", "high", "low", "close", "volume"]]
        else:
            raise ValueError(f"未知 market: {market}")

        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df.to_parquet(cache)
        return df[(df["date"] >= start) & (df["date"] <= end)]

    # ---------- index daily (回测交易日历 + 基准) ----------

    def get_index_daily(self, symbol: str = "sh000300") -> pd.DataFrame:
        """指数日线. symbol 例: sh000300 / sh000905 / sz399001"""
        cache = self.cache_dir / f"index_daily_{symbol}.parquet"
        if cache.exists() and self._is_fresh(cache):
            return pd.read_parquet(cache)
        raw = ak.stock_zh_index_daily(symbol=symbol)
        df = raw[["date", "open", "high", "low", "close", "volume"]].copy()
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df.to_parquet(cache)
        return df

    # ---------- fundamentals (A 股) ----------

    def get_a_share_valuation(self, code: str) -> pd.DataFrame:
        """A 股按日估值序列. 列: date, pe_ttm, pe_static, pb, peg, pcf, ps, total_mv"""
        cache = self.cache_dir / f"val_a_{code}.parquet"
        if self._is_fresh(cache):
            return pd.read_parquet(cache)

        df = ak.stock_value_em(symbol=code)
        df = df.rename(columns={
            "数据日期": "date", "PE(TTM)": "pe_ttm", "PE(静)": "pe_static",
            "市净率": "pb", "PEG值": "peg", "市现率": "pcf",
            "市销率": "ps", "总市值": "total_mv",
        })[["date", "pe_ttm", "pe_static", "pb", "peg", "pcf", "ps", "total_mv"]]
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df.to_parquet(cache)
        return df

    def get_a_share_abstract(self, code: str) -> pd.DataFrame:
        """
        A 股财务摘要. 长格式: 列 ['选项', '指标', YYYYMMDD, ...]
        关键指标 (在 '指标' 列):
          - '净资产收益率(ROE)'           (盈利能力)
          - '营业总收入增长率'             (成长能力)
          - '归属母公司净利润增长率'        (成长能力)
        """
        cache = self.cache_dir / f"abstract_a_{code}.parquet"
        if self._is_fresh(cache):
            return pd.read_parquet(cache)

        df = ak.stock_financial_abstract(symbol=code)
        df.to_parquet(cache)
        return df

    @staticmethod
    def latest_indicator_value(abstract_df: pd.DataFrame, indicator: str) -> float | None:
        """从 stock_financial_abstract 的长格式里取某指标的最新一期值."""
        rows = abstract_df[abstract_df["指标"] == indicator]
        if rows.empty:
            return None
        date_cols = [c for c in abstract_df.columns if c not in ("选项", "指标")]
        # 列名是 'YYYYMMDD', 倒序取第一个非空
        date_cols_sorted = sorted(date_cols, reverse=True)
        for col in date_cols_sorted:
            v = rows.iloc[0][col]
            if pd.notna(v):
                try:
                    return float(v)
                except (ValueError, TypeError):
                    continue
        return None

    # ---------- helpers ----------

    def _is_fresh(self, path: Path) -> bool:
        if not path.exists():
            return False
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        return datetime.now() - mtime < timedelta(days=self.refresh_days)
