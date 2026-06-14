"""
数据层: A 股 + 港股 + 美股的统一接口。
所有外部数据源（akshare）都收敛到这里，上层模块不直接 import akshare。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import re
from typing import Any, Literal

import akshare as ak
import pandas as pd

from quant_system.strategies.equity_factor.data.hang_seng_indexes import (
    HangSengDataError,
    load_hschk100_constituents,
    read_hk_constituent_daily_csv,
    read_hschk100_index_daily_csv,
)

Market = Literal["a_share", "hk_share", "us_share"]


class DataLoader:
    def __init__(
        self,
        cache_dir: Path,
        refresh_days: int = 1,
        price_adjust: str = "qfq",
        hang_seng_indexes: dict[str, Any] | None = None,
        us_market: dict[str, Any] | None = None,
        us_universe: str | None = None,
        duckdb_path: str = "data/quant.duckdb",
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.refresh_days = refresh_days
        # akshare adjust: "qfq"(前复权) / "hfq"(后复权) / ""(不复权)
        self.price_adjust = price_adjust
        self._hsi_cfg: dict[str, Any] = hang_seng_indexes or {}
        self._us_cfg: dict[str, Any] = us_market or {}
        # us_universe 影响 _us_cfg 中路径键的选择（nasdaq100 默认 vs sp500_*）
        self.us_universe: str = us_universe or "nasdaq100"
        self._duckdb_path = duckdb_path
        self._store: Any = None  # lazy

    def _us_paths(self) -> dict[str, str]:
        """根据 us_universe 返回 {daily_dir, index_daily_csv, constituents_csv}。
        sp500 走 sp500_* 前缀字段；all 走 us_all_* 字段；nasdaq100 / 未指定 走旧字段（向后兼容）。"""
        if self.us_universe == "sp500":
            return {
                "daily_dir": self._us_cfg.get("sp500_daily_dir")
                             or self._us_cfg.get("daily_dir") or "",
                "index_daily_csv": self._us_cfg.get("sp500_index_daily_csv")
                             or self._us_cfg.get("index_daily_csv") or "",
                "constituents_csv": self._us_cfg.get("sp500_constituents_csv")
                             or self._us_cfg.get("constituents_csv") or "",
            }
        if self.us_universe == "all":
            return {
                "daily_dir": self._us_cfg.get("us_all_daily_dir")
                             or self._us_cfg.get("daily_dir") or "",
                "index_daily_csv": self._us_cfg.get("index_daily_csv") or "",
                "constituents_csv": self._us_cfg.get("constituents_csv") or "",
            }
        return {
            "daily_dir": self._us_cfg.get("daily_dir") or "",
            "index_daily_csv": self._us_cfg.get("index_daily_csv") or "",
            "constituents_csv": self._us_cfg.get("constituents_csv") or "",
        }

    def _get_store(self):
        """DuckDB store (lazy). 不可用时返回 None, get_daily 自动 fallback."""
        if self._store is False:
            return None
        if self._store is None:
            try:
                from quant_system.data import DuckDBStore
                self._store = DuckDBStore(self._duckdb_path)
            except ImportError:
                self._store = False
                return None
        return self._store

    # ---------- universe ----------

    def get_universe(self, market: Market, name: str) -> pd.DataFrame:
        """成分股清单, 返回列: code, name。
        name="all" 时返回全市场股票（acache 24h 过期因为 spot 是当日快照）。
        """
        cache = self.cache_dir / f"universe_{market}_{name}.parquet"
        if name != "all" and self._is_fresh(cache):
            return pd.read_parquet(cache)

        if market == "a_share":
            if name == "hs300":
                df = ak.index_stock_cons_csindex(symbol="000300")
                df = df.rename(columns={"成分券代码": "code", "成分券名称": "name"})[["code", "name"]]
            elif name == "all":
                df = self._a_share_full_universe()
            else:
                raise ValueError(
                    f"未知 A 股 universe: {name}（本项目支持 hs300 / all）",
                )
        elif market == "hk_share":
            if name == "hs100":
                df = load_hschk100_constituents(self._hsi_cfg)
            elif name == "all":
                df = self._hk_full_universe()
            else:
                raise ValueError(
                    f"未知 港股 universe: {name}（本项目支持 hs100=恒生 HSCHK100 / all）",
                )
        elif market == "us_share":
            if name in ("nasdaq100", "sp500"):
                # 切换 universe 上下文（影响后续 get_daily / get_index_daily 路径）
                self.us_universe = name
                csvp = self._us_paths()["constituents_csv"]
                if not csvp:
                    raise ValueError(
                        f"请先运行 scripts/prefetch/prefetch_{'us' if name == 'nasdaq100' else 'sp500'}_universe.py，"
                        f"并在 config 设置 data.us_market.{'constituents_csv' if name == 'nasdaq100' else 'sp500_constituents_csv'}"
                    )
                from quant_system.config import PROJECT_ROOT
                p = Path(csvp)
                if not p.is_absolute():
                    p = PROJECT_ROOT / p
                df = pd.read_csv(p)[["code", "name"]]
            elif name == "all":
                self.us_universe = "all"
                df = self._us_full_universe()
            else:
                raise ValueError(f"未知美股 universe: {name}（本项目支持 nasdaq100 / sp500 / all）")
        else:
            raise ValueError(f"未知 market: {market}")

        df.to_parquet(cache)
        return df

    def _a_share_full_universe(self) -> pd.DataFrame:
        """全 A 股 universe — 优先从 data/prices/ 已缓存 CSV 文件扫描，失败回退 akshare。"""
        from quant_system.config import PROJECT_ROOT

        csv_dir = PROJECT_ROOT / "data" / "prices"
        if csv_dir.exists():
            codes = sorted(
                f.stem.replace("_daily", "")
                for f in csv_dir.glob("*_daily.csv")
                if not f.stem.startswith("sh.") and not f.stem.startswith("sz.")
            )
            if codes:
                return pd.DataFrame({"code": codes, "name": codes})

        # 回退 akshare 实时行情
        spot = ak.stock_zh_a_spot_em()
        df = spot[["代码", "名称"]].copy()
        df.columns = ["code", "name"]
        df = df[~df["name"].str.contains("ST", na=False)]
        df = df[~df["code"].str.contains("ST", na=False)]
        return df.reset_index(drop=True)

    def _hk_full_universe(self) -> pd.DataFrame:
        """全港股 universe — 优先扫 data/hk_prices/ 已 prefetch 的 CSV，
        无缓存才回 akshare spot (sina；em 端点 push2 在本机被拦)。"""
        from quant_system.config import PROJECT_ROOT
        csv_dir = PROJECT_ROOT / "data" / "hk_prices"
        if csv_dir.exists():
            codes = sorted(f.stem for f in csv_dir.glob("*.csv"))
            if codes:
                return pd.DataFrame({"code": codes, "name": codes})

        spot = ak.stock_hk_spot()
        df = spot[["代码", "中文名称"]].copy()
        df.columns = ["code", "name"]
        return df.reset_index(drop=True)

    def _us_full_universe(self) -> pd.DataFrame:
        """全美股 universe — 优先扫 data/us_prices_all/ 已 prefetch 的 CSV，
        无缓存才回 akshare spot (sina, 17000+ 只)。"""
        from quant_system.config import PROJECT_ROOT
        csv_dir = PROJECT_ROOT / "data" / "us_prices_all"
        if csv_dir.exists():
            codes = sorted(f.stem for f in csv_dir.glob("*.csv"))
            if codes:
                return pd.DataFrame({"code": codes, "name": codes})

        spot = ak.stock_us_spot()
        df = spot[["symbol", "cname"]].copy()
        df.columns = ["code", "name"]
        return df.reset_index(drop=True)

    # ---------- daily prices ----------

    # 拉取下限: 缓存永远从这一天起, 上层任意 start 都能切片
    FETCH_FLOOR = "2018-01-01"

    def daily_cache_path(self, market: Market, code: str) -> Path:
        """当前 price_adjust 对应的 daily cache 路径."""
        if self.price_adjust == "qfq":
            return self.cache_dir / f"daily_{market}_{code}.parquet"
        key = self.price_adjust if self.price_adjust else "raw"
        return self.cache_dir / f"daily_{market}_{code}_{key}.parquet"

    def get_daily(
        self,
        market: Market,
        code: str,
        start: str,
        end: str | None = None,
    ) -> pd.DataFrame:
        """日线 OHLCV, 列: date, open, high, low, close, volume.
        优先级: DuckDB → parquet 缓存 → akshare 远程."""
        end = end or datetime.now().strftime("%Y-%m-%d")
        cache = self.daily_cache_path(market, code)
        adjust_key = "qfq" if self.price_adjust == "qfq" else self.price_adjust

        # 1. DuckDB hot path（仅 qfq；非 qfq 走原 parquet 缓存以避免 adjust 混淆）
        # M5 of duckdb_cache_freshness: cache 落后 end - skew_days 天时强 fall through
        # 防 06-08 实盘 case (cache 截止 06-04, 算 pnl/距 stop/α 全用过时价).
        if self.price_adjust == "qfq":
            store = self._get_store()
            if store is not None and store.has_code(market, code):
                cache_latest = store.latest_date(market, code)
                try:
                    end_dt = pd.to_datetime(end).date()
                    skew_days = 3  # 落后 >=3 个交易日强 refresh
                    fresh = cache_latest is not None and (end_dt - cache_latest).days <= skew_days
                except Exception:
                    fresh = True  # 保守 fallback
                if fresh:
                    df = store.get_daily(market, code, start, end)
                    if not df.empty:
                        df = df.copy()
                        df["date"] = df["date"].dt.strftime("%Y-%m-%d")
                        return df[["date", "open", "high", "low", "close", "volume"]]

        # 2. parquet 缓存
        if cache.exists() and self._is_fresh(cache):
            df = pd.read_parquet(cache)
            if len(df) > 0:
                cache_min = df["date"].min()
                # 只要 cache 起点早于 user 请求的 start, 就可以切片返回
                if cache_min <= start:
                    return df[(df["date"] >= start) & (df["date"] <= end)]
            # 缓存范围不够 (cache 起点晚于请求的 start), 落到下面重拉

        if market == "a_share":
            # 3a. CSV 文件缓存（data/prices/{code}_daily.csv，zhuang 子策略已预热）
            from quant_system.config import PROJECT_ROOT
            csv_path = PROJECT_ROOT / "data" / "prices" / f"{code}_daily.csv"
            if csv_path.exists():
                raw = pd.read_csv(csv_path)
                if len(raw) > 0:
                    raw["date"] = raw["date"].astype(str)
                    raw = raw[(raw["date"] >= start) & (raw["date"] <= end)]
                    if not raw.empty:
                        cols = ["date", "open", "high", "low", "close", "volume"]
                        available = [c for c in cols if c in raw.columns]
                        return raw[available].copy()

            # 3b. 远程 akshare
            prefix = "sh" if code.startswith("6") else (
                "bj" if code.startswith("8") else "sz"
            )
            raw = ak.stock_zh_a_daily(
                symbol=f"{prefix}{code}",
                start_date=self.FETCH_FLOOR.replace("-", ""),
                end_date=end.replace("-", ""),
                adjust=adjust_key,
            )
            df = raw[["date", "open", "high", "low", "close", "volume"]].copy()
        elif market == "hk_share":
            daily_dir = self._hsi_cfg.get("hk_constituent_daily_dir") or ""
            if not daily_dir:
                raise HangSengDataError(
                    "港股日线须来自恒生指数相关数据产品导出文件。"
                    "请在 config.yaml 设置 data.hang_seng_indexes.hk_constituent_daily_dir "
                    "（每只股票一个 {code}.csv，列: date,open,high,low,close,volume）。"
                    "恒生不向本仓库提供免费公共个股行情接口；订阅见 https://www.hsi.com.hk/en-hk/solutions/data-analytics/",
                )
            from quant_system.config import PROJECT_ROOT

            dpath = Path(daily_dir)
            if not dpath.is_absolute():
                dpath = PROJECT_ROOT / dpath
            df = read_hk_constituent_daily_csv(dpath, code)
        elif market == "us_share":
            daily_dir = self._us_paths()["daily_dir"]
            if not daily_dir:
                raise ValueError(
                    "美股日线须先运行 scripts/prefetch/prefetch_us_universe.py 或 prefetch_sp500_universe.py 预取。"
                    f"当前 us_universe={self.us_universe}，请在 config 设置对应 daily_dir。"
                )
            from quant_system.config import PROJECT_ROOT

            dpath = Path(daily_dir)
            if not dpath.is_absolute():
                dpath = PROJECT_ROOT / dpath
            csv_path = dpath / f"{code}.csv"
            if not csv_path.exists():
                # 备用：sp500 universe 下查不到时回退到 nasdaq100 dir（103 只 overlap）
                alt = self._us_cfg.get("daily_dir") or ""
                if alt and self.us_universe == "sp500":
                    alt_path = Path(alt) if Path(alt).is_absolute() else PROJECT_ROOT / alt
                    if (alt_path / f"{code}.csv").exists():
                        csv_path = alt_path / f"{code}.csv"
                    else:
                        raise FileNotFoundError(f"美股日线文件不存在: {csv_path}（备用 {alt_path}/{code}.csv 也无）")
                else:
                    raise FileNotFoundError(f"美股日线文件不存在: {csv_path}")
            raw = pd.read_csv(csv_path)
            # akshare stock_us_daily 可能返回中/英文列名，统一映射
            cn_map = {"日期": "date", "开盘": "open", "最高": "high", "最低": "low", "收盘": "close", "成交量": "volume"}
            raw = raw.rename(columns=cn_map)
            df = raw[["date", "open", "high", "low", "close", "volume"]].copy()
        else:
            raise ValueError(f"未知 market: {market}")

        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df.to_parquet(cache)
        # 同步写 DuckDB（仅 qfq；非 qfq 不入 DB 防止 adjust 混淆）
        if self.price_adjust == "qfq":
            store = self._get_store()
            if store is not None:
                try:
                    store.insert_daily(market, code, df, replace=True)
                except Exception:
                    pass  # DB 写入失败不影响 parquet 路径
        return df[(df["date"] >= start) & (df["date"] <= end)]

    # ---------- index daily (回测交易日历 + 基准) ----------

    def get_index_daily(self, symbol: str = "sh000300") -> pd.DataFrame:
        """指数日线. A 股例: sh000300；港股恒生指数 HSCHK100 见 config hang_seng_indexes.hschk100_index_daily_csv。"""
        sym_key = symbol.replace(".", "_")
        cache = self.cache_dir / f"index_daily_{sym_key}.parquet"
        if cache.exists() and self._is_fresh(cache):
            return pd.read_parquet(cache)
        if symbol.upper() == "HSCHK100":
            csvp = self._hsi_cfg.get("hschk100_index_daily_csv") or ""
            if not csvp:
                raise HangSengDataError(
                    "港股基准 HSCHK100 须使用恒生提供的指数日线 CSV。"
                    "请设置 data.hang_seng_indexes.hschk100_index_daily_csv（列: date,open,high,low,close,volume）。",
                )
            from quant_system.config import PROJECT_ROOT

            p = Path(csvp)
            if not p.is_absolute():
                p = PROJECT_ROOT / p
            df = read_hschk100_index_daily_csv(p)
        elif symbol.upper() in ("NDX", "SPX"):
            # 临时切上下文确保 _us_paths() 返回对应 universe 路径
            saved = self.us_universe
            if symbol.upper() == "SPX":
                self.us_universe = "sp500"
            elif symbol.upper() == "NDX":
                self.us_universe = "nasdaq100"
            csvp = self._us_paths()["index_daily_csv"]
            self.us_universe = saved
            if not csvp:
                raise ValueError(
                    f"美股基准 {symbol.upper()} 须先运行对应 prefetch 脚本。"
                    f"请设置 data.us_market.{'sp500_index_daily_csv' if symbol.upper() == 'SPX' else 'index_daily_csv'}"
                )
            from quant_system.config import PROJECT_ROOT

            p = Path(csvp)
            if not p.is_absolute():
                p = PROJECT_ROOT / p
            raw = pd.read_csv(p)
            cn_map = {"日期": "date", "开盘": "open", "最高": "high", "最低": "low", "收盘": "close", "成交量": "volume"}
            raw = raw.rename(columns=cn_map)
            if "volume" not in raw.columns:
                raw["volume"] = 0.0
            df = raw[["date", "open", "high", "low", "close", "volume"]].copy()
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        else:
            raw = ak.stock_zh_index_daily(symbol=symbol)
            df = raw[["date", "open", "high", "low", "close", "volume"]].copy()
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df.to_parquet(cache)
        return df

    # ---------- limit up/down pools (A股) ----------

    def get_zt_pool(self, asof: str) -> pd.DataFrame:
        """涨停板池（东财）。asof: 'YYYY-MM-DD'."""
        date = asof.replace("-", "")
        cache = self.cache_dir / f"zt_{date}.parquet"
        if cache.exists() and self._is_fresh(cache):
            return pd.read_parquet(cache)
        try:
            df = ak.stock_zt_pool_em(date=date)
        except Exception:
            df = pd.DataFrame()
        df.to_parquet(cache)
        return df

    def get_dt_pool(self, asof: str) -> pd.DataFrame:
        """跌停板池（东财）。asof: 'YYYY-MM-DD'."""
        date = asof.replace("-", "")
        cache = self.cache_dir / f"dt_{date}.parquet"
        if cache.exists() and self._is_fresh(cache):
            return pd.read_parquet(cache)
        # akshare 跌停池接口名在不同版本可能变化；这里做宽容调用，失败返回空表并缓存
        df = pd.DataFrame()
        try:
            fn = getattr(ak, "stock_dt_pool_em", None)
            if fn is not None:
                df = fn(date=date)
        except Exception:
            df = pd.DataFrame()
        df.to_parquet(cache)
        return df

    # ---------- debt ratio (A股) ----------

    def get_a_share_debt_ratio(self, code: str, asof: str) -> float | None:
        """
        资产负债率（<= asof 的最新值）。

        实现说明（无黑盒）：
        - 优先用同花顺资产负债表接口 `stock_financial_debt_ths` 计算：
            debt_ratio = 负债合计 / 资产合计
        - 若接口不可用/字段缺失，则返回 None（上层可决定是否硬过滤）
        """
        # 注意：THS 原始表含大量 object 列（bool/str 混用），直接 parquet 缓存会失败。
        # 因此缓存“窄表”（仅报告期 + 资产/负债合计 + 派生比率），可复现且可序列化。
        cache = self.cache_dir / f"debt_ratio_sheet_a_{code}.parquet"

        def _parse_cn_amount(v) -> float | None:
            """
            解析 THS 资产负债表里的中文金额，例如：'6.03万亿' / '123.45亿' / '1,234.5万'。
            返回“以万为单位”的 float（仅用于同一列内相对比较；比值与具体单位无关）。
            """
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return None
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                try:
                    return float(v)
                except Exception:
                    return None

            s = str(v).strip()
            if not s or s in {"--", "-", "—"}:
                return None

            # 去掉千分位
            s = s.replace(",", "")

            m = re.match(r"^([+-]?\d+(?:\.\d+)?)\s*(万亿|亿|万|元)?$", s)
            if not m:
                # 兜底：尝试抽取第一个数字
                m2 = re.search(r"([+-]?\d+(?:\.\d+)?)", s)
                if not m2:
                    return None
                try:
                    return float(m2.group(1))
                except Exception:
                    return None

            num = float(m.group(1))
            unit = m.group(2) or ""
            # 统一到 “万”
            if unit == "万亿":
                return num * 1e8  # 1万亿 = 1e8万
            if unit == "亿":
                return num * 1e4  # 1亿 = 1e4万
            if unit == "万":
                return num
            if unit == "元":
                return num / 1e4
            return num

        def _build_sheet(raw: pd.DataFrame) -> pd.DataFrame:
            if raw is None or raw.empty:
                return pd.DataFrame()
            cols = [str(c) for c in raw.columns]
            if "报告期" not in cols:
                return pd.DataFrame()

            asset_col = None
            liab_col = None
            for c in raw.columns:
                s = str(c)
                if s.endswith("资产合计") and not s.startswith("*"):
                    asset_col = c
                if s.endswith("负债合计") and not s.startswith("*"):
                    liab_col = c
            if asset_col is None or liab_col is None:
                return pd.DataFrame()

            out = raw[["报告期", asset_col, liab_col]].copy()
            out = out.rename(columns={asset_col: "assets_raw", liab_col: "liabilities_raw"})
            out["report_date"] = pd.to_datetime(out["报告期"], errors="coerce")
            out = out.dropna(subset=["report_date"])
            out["assets"] = out["assets_raw"].map(_parse_cn_amount)
            out["liabilities"] = out["liabilities_raw"].map(_parse_cn_amount)
            out["debt_ratio"] = out["liabilities"] / out["assets"]
            out = out.dropna(subset=["assets", "liabilities", "debt_ratio"])
            out = out[out["assets"] > 0]
            out = out.sort_values("report_date").reset_index(drop=True)
            return out[["report_date", "assets", "liabilities", "debt_ratio"]]

        if self._is_fresh(cache):
            sheet = pd.read_parquet(cache)
        else:
            raw = pd.DataFrame()
            try:
                raw = ak.stock_financial_debt_ths(symbol=code)
            except Exception:
                raw = pd.DataFrame()

            sheet = _build_sheet(raw)
            if not sheet.empty:
                sheet.to_parquet(cache)

        if sheet is None or sheet.empty:
            return None

        tmp = sheet[sheet["report_date"] <= pd.to_datetime(asof)]
        if tmp.empty:
            return None
        return float(tmp.iloc[-1]["debt_ratio"])

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
    def latest_n_indicator_values(
        abstract_df: pd.DataFrame, indicator: str, asof: str | None = None,
        n: int = 2, publication_lag_days: int = 90,
    ) -> list[float]:
        """从 stock_financial_abstract 里取某指标最近 N 期的有效值（降序排列，最新在前）。
        asof 截断：报告期 <= (asof - publication_lag_days) 才纳入，保守模拟实际公告窗口。
        A 股一季报通常 4 月底披露 = 报告期 3-31 起约 30 天；半/年报最长约 90 天。
        publication_lag_days=90 与 HK latest_hk_indicator 同步，安全侧偏严。
        """
        rows = abstract_df[abstract_df["指标"] == indicator]
        if rows.empty:
            return []
        date_cols = [c for c in abstract_df.columns if c not in ("选项", "指标")]
        if asof:
            cutoff = (pd.to_datetime(asof) - pd.Timedelta(days=publication_lag_days)).strftime("%Y%m%d")
            date_cols = [c for c in date_cols if str(c) <= cutoff]
        results: list[float] = []
        for col in sorted(date_cols, reverse=True):
            if len(results) >= n:
                break
            v = rows.iloc[0][col]
            if pd.notna(v):
                try:
                    results.append(float(v))
                except (ValueError, TypeError):
                    continue
        return results

    @staticmethod
    def latest_indicator_value(
        abstract_df: pd.DataFrame, indicator: str, asof: str | None = None,
        publication_lag_days: int = 90,
    ) -> float | None:
        """从 stock_financial_abstract 的长格式里取某指标的最新一期值.

        asof 截断：报告期 <= (asof - publication_lag_days) 才纳入。
        publication_lag_days=90 与 HK 同步；A 股年报最长披露窗口约 4 个月。
        """
        rows = abstract_df[abstract_df["指标"] == indicator]
        if rows.empty:
            return None
        date_cols = [c for c in abstract_df.columns if c not in ("选项", "指标")]
        if asof:
            cutoff = (pd.to_datetime(asof) - pd.Timedelta(days=publication_lag_days)).strftime("%Y%m%d")
            date_cols = [c for c in date_cols if str(c) <= cutoff]
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

    # ---------- 边际资金流向（HK 南向 / A 股北向）----------

    def _fetch_hsgt_flow(self, symbol: str, cache_filename: str) -> pd.DataFrame:
        """通用：拉取沪股通/深股通/南向/北向日级数据并缓存。
        symbol 必须是 akshare stock_hsgt_hist_em 接受的字符串。"""
        cache = self.cache_dir / cache_filename
        if self._is_fresh(cache):
            return pd.read_parquet(cache)
        try:
            raw = ak.stock_hsgt_hist_em(symbol=symbol)
        except Exception:
            df = pd.DataFrame(columns=["date", "net_buy"])
            df.to_parquet(cache)
            return df
        if raw is None or raw.empty:
            df = pd.DataFrame(columns=["date", "net_buy"])
            df.to_parquet(cache)
            return df
        df = raw.rename(columns={"日期": "date", "当日成交净买额": "net_buy"})[["date", "net_buy"]]
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        df["net_buy"] = pd.to_numeric(df["net_buy"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        df.to_parquet(cache)
        return df

    def get_hk_southbound_flow(self) -> pd.DataFrame:
        """港股通南向资金日级（HK 边际买盘信号）。[date, net_buy(亿元)] 升序。"""
        return self._fetch_hsgt_flow("南向资金", "hk_southbound_flow.parquet")

    def get_a_share_northbound_flow(self) -> pd.DataFrame:
        """陆股通北向资金日级（A 股边际买盘信号）。[date, net_buy(亿元)] 升序。"""
        return self._fetch_hsgt_flow("北向资金", "a_share_northbound_flow.parquet")

    def get_marginal_flow(self, market: "Market") -> pd.DataFrame:
        """按市场分发：HK→南向；A 股→北向；其他→空。"""
        if market == "hk_share":
            return self.get_hk_southbound_flow()
        if market == "a_share":
            return self.get_a_share_northbound_flow()
        return pd.DataFrame(columns=["date", "net_buy"])

    # ---------- fundamentals (HK 港股) ----------

    def get_hk_financial_indicator(self, code: str) -> pd.DataFrame:
        """HK 年度财务分析指标 (东财 stock_financial_hk_analysis_indicator_em).
        返回 [report_date, eps_ttm, bps, roe_avg, revenue_yoy]，按 report_date 升序。
        失败时返回空 DataFrame 并缓存以避免反复重试。"""
        cache = self.cache_dir / f"hk_fin_{code}.parquet"
        if self._is_fresh(cache):
            return pd.read_parquet(cache)
        cols = ["report_date", "eps_ttm", "bps", "roe_avg", "revenue_yoy"]
        try:
            raw = ak.stock_financial_hk_analysis_indicator_em(symbol=code, indicator="年度")
        except Exception:
            df = pd.DataFrame(columns=cols)
            df.to_parquet(cache)
            return df
        if raw is None or raw.empty:
            df = pd.DataFrame(columns=cols)
            df.to_parquet(cache)
            return df
        df = raw.rename(columns={
            "REPORT_DATE": "report_date", "EPS_TTM": "eps_ttm", "BPS": "bps",
            "ROE_AVG": "roe_avg", "OPERATE_INCOME_YOY": "revenue_yoy",
        })
        for c in cols:
            if c not in df.columns:
                df[c] = None
        df = df[cols].copy()
        df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        for c in ["eps_ttm", "bps", "roe_avg", "revenue_yoy"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=["report_date"]).sort_values("report_date").reset_index(drop=True)
        df.to_parquet(cache)
        return df

    @staticmethod
    def latest_hk_indicator(
        df: pd.DataFrame, col: str, asof: str, publication_lag_days: int = 90
    ) -> float | None:
        """HK 年度财务取 asof 之前 publication_lag_days 天的最新有效值。
        默认 90 天滞后保守模拟 HK 年报披露窗口（FY-end 起 3-4 个月）。"""
        if df is None or df.empty or col not in df.columns:
            return None
        cutoff = (pd.to_datetime(asof) - pd.Timedelta(days=publication_lag_days)).strftime("%Y-%m-%d")
        eligible = df[df["report_date"] <= cutoff]
        if eligible.empty:
            return None
        s = pd.to_numeric(eligible[col], errors="coerce").dropna()
        return float(s.iloc[-1]) if len(s) else None

    # ---------- fundamentals (US 美股) ----------

    def get_us_financial_indicator(self, code: str) -> pd.DataFrame:
        """US 年度财务指标 (yfinance .financials / .balance_sheet / .cashflow).
        返回 [report_date, eps_ttm, bps, roe_avg, revenue_yoy, fcf_per_share]，按 report_date 升序。
        yfinance 通常提供最近 4-5 年年报；2018-2020 段可能缺失。
        失败时返回空 DataFrame 并缓存以避免反复重试。
        """
        cache = self.cache_dir / f"us_fin_{code}.parquet"
        if self._is_fresh(cache):
            return pd.read_parquet(cache)
        cols = ["report_date", "eps_ttm", "bps", "roe_avg", "revenue_yoy", "fcf_per_share"]
        try:
            import yfinance as yf
            t = yf.Ticker(code)
            fin = t.financials       # income statement annual: 行=line item, 列=report_date 降序
            bs = t.balance_sheet     # balance sheet annual
            cf = t.cashflow          # cashflow annual
        except Exception:
            df = pd.DataFrame(columns=cols)
            df.to_parquet(cache)
            return df
        if fin is None or fin.empty or bs is None or bs.empty:
            df = pd.DataFrame(columns=cols)
            df.to_parquet(cache)
            return df

        # 所有年报列时间戳（取 income stmt 的列做主轴；如 bs/cf 缺某年用 NaN 填）
        report_dates = sorted([pd.Timestamp(c) for c in fin.columns])

        def _at(table: pd.DataFrame, row: str, dt: pd.Timestamp) -> float | None:
            if table is None or table.empty or row not in table.index:
                return None
            if dt not in table.columns:
                return None
            v = table.loc[row, dt]
            try:
                f = float(v)
                return f if not pd.isna(f) else None
            except (TypeError, ValueError):
                return None

        rows = []
        revs: list[tuple[pd.Timestamp, float | None]] = []
        for dt in report_dates:
            eps = _at(fin, "Diluted EPS", dt) or _at(fin, "Basic EPS", dt)
            equity = _at(bs, "Stockholders Equity", dt) or _at(bs, "Common Stock Equity", dt)
            shares = _at(bs, "Ordinary Shares Number", dt) or _at(bs, "Share Issued", dt)
            ni = _at(fin, "Net Income", dt) or _at(fin, "Net Income Common Stockholders", dt)
            revenue = _at(fin, "Total Revenue", dt) or _at(fin, "Operating Revenue", dt)
            fcf = _at(cf, "Free Cash Flow", dt)

            bps_v = (equity / shares) if (equity is not None and shares and shares > 0) else None
            roe_v = (ni / equity) if (ni is not None and equity and equity > 0) else None
            fcf_ps_v = (fcf / shares) if (fcf is not None and shares and shares > 0) else None
            revs.append((dt, revenue))
            # revenue_yoy 后面统一回填
            rows.append({
                "report_date": dt.strftime("%Y-%m-%d"),
                "eps_ttm": eps,
                "bps": bps_v,
                "roe_avg": roe_v,
                "revenue_yoy": None,   # placeholder
                "fcf_per_share": fcf_ps_v,
            })

        # revenue_yoy：用 revs 按 report_date 升序计算 (rev_t - rev_{t-1}) / rev_{t-1}
        for i, (dt, rev) in enumerate(revs):
            if i == 0 or rev is None or revs[i-1][1] in (None, 0):
                continue
            prev = revs[i-1][1]
            if prev and prev != 0:
                rows[i]["revenue_yoy"] = (rev - prev) / abs(prev)

        df = pd.DataFrame(rows, columns=cols)
        for c in ["eps_ttm", "bps", "roe_avg", "revenue_yoy", "fcf_per_share"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=["report_date"]).sort_values("report_date").reset_index(drop=True)
        df.to_parquet(cache)
        return df

    @staticmethod
    def latest_us_indicator(
        df: pd.DataFrame, col: str, asof: str, publication_lag_days: int = 60
    ) -> float | None:
        """US 年度财务取 asof 之前 publication_lag_days 天的最新有效值。
        默认 60 天滞后模拟 SEC 10-K 披露窗口（large accelerated filers 60 天内披露）。
        与 latest_hk_indicator 同款逻辑，仅默认窗口不同。"""
        if df is None or df.empty or col not in df.columns:
            return None
        cutoff = (pd.to_datetime(asof) - pd.Timedelta(days=publication_lag_days)).strftime("%Y-%m-%d")
        eligible = df[df["report_date"] <= cutoff]
        if eligible.empty:
            return None
        s = pd.to_numeric(eligible[col], errors="coerce").dropna()
        return float(s.iloc[-1]) if len(s) else None

    def get_a_share_industry_map(self) -> dict[str, str]:
        """
        A 股 code -> 行业名称（东财 A 股实时行情整表，单日 parquet 缓存）。
        列名随 akshare 版本可能变化，做宽松匹配；失败时返回空 dict。
        """
        cache = self.cache_dir / "industry_spot_a_map.parquet"
        if self._is_fresh(cache):
            try:
                df = pd.read_parquet(cache)
            except Exception:
                df = pd.DataFrame()
            if not df.empty and "code" in df.columns and "industry" in df.columns:
                return dict(zip(df["code"].astype(str), df["industry"].astype(str)))
        out_rows: list[tuple[str, str]] = []
        try:
            raw = ak.stock_zh_a_spot_em()
        except Exception:
            raw = pd.DataFrame()
        if raw is None or raw.empty:
            pd.DataFrame({"code": [], "industry": []}).to_parquet(cache)
            return {}
        code_col = ind_col = None
        for c in raw.columns:
            s = str(c)
            if s in ("代码", "code"):
                code_col = c
            if s in ("行业", "所属行业", "industry"):
                ind_col = c
        if code_col is None or ind_col is None:
            pd.DataFrame({"code": [], "industry": []}).to_parquet(cache)
            return {}
        codes = raw[code_col].astype(str).str.replace(r"\.(SH|SZ|sh|sz)$", "", regex=True)
        inds = raw[ind_col].astype(str)
        tmp = pd.DataFrame({"code": codes, "industry": inds})
        tmp.to_parquet(cache)
        return dict(zip(tmp["code"], tmp["industry"]))

    # ---------- helpers ----------

    def _is_fresh(self, path: Path) -> bool:
        if not path.exists():
            return False
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        return datetime.now() - mtime < timedelta(days=self.refresh_days)
