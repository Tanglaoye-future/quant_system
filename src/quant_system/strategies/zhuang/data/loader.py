"""
zhuang_system 数据加载器.

数据源 (Phase 1-C 按 market dispatch):
  - a_share: BaoStock 全量历史 + query_profit_data 总股本 → 市值
  - hk_small: Phase 1-D 接入 (akshare/yfinance, 当前调用直接 NotImplementedError)

调用者优先用装配后 config (含 markets[market] 子字典). 旧调用 (顶层 universe 不带 markets)
仍向后兼容: market=a_share 默认, 顶层 universe 字段当作 fallback.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    import baostock as bs
except ImportError:
    bs = None  # type: ignore


def _require_bs() -> None:
    if bs is None:
        raise ImportError("请先安装 baostock：pip install baostock")


_ATR_PERIOD = 14

# BaoStock 代码格式：sh.600000 / sz.000001
def _to_bs_code(code: str) -> str:
    code = str(code).zfill(6)
    if code.startswith("6"):
        return f"sh.{code}"
    return f"sz.{code}"


def _to_plain_code(bs_code: str) -> str:
    return bs_code.split(".")[-1]


class ZhuangDataLoader:
    """庄股策略专用数据加载器（DuckDB 优先 + CSV/BaoStock fallback）.

    Phase 1-C: 加 market 参数支持多市场 dispatch.
        - market='a_share' (默认, 向下兼容): BaoStock 全量 + DuckDB store key='a_share'
        - market='hk_small': Phase 1-D 待接入, 调用直接 NotImplementedError
    """

    def __init__(
        self, config: dict, refresh_days: int = 1, market: str = "a_share",
    ) -> None:
        self.config = config
        self.refresh_days = refresh_days
        # 优先用 config["markets"][market] (Phase 1-C 新结构), 缺失回退到顶层 universe (legacy)
        markets_node = config.get("markets") or {}
        if market in markets_node:
            self.market_cfg = markets_node[market]
        else:
            # legacy single-market config: 顶层 universe + fees 等
            self.market_cfg = {
                "universe": config.get("universe", {}),
                "data_provider": "baostock",
            }
        self.market = market
        self.data_provider = self.market_cfg.get("data_provider", "baostock")

        # 数据源前置检查 - baostock 只在真正用 (login/fetch) 时才检查 ImportError
        # hk_small/hk_yfinance provider 当前是占位, 立即 NotImplementedError 阻止构造
        if self.data_provider in ("hk_akshare", "hk_yfinance"):
            raise NotImplementedError(
                f"market={market} data_provider={self.data_provider} 待 Phase 1-D 接入. "
                "当前架构占位; HK 小盘股 universe 数据源 + benchmark + provider 实施在 task #8."
            )
        if self.data_provider != "baostock":
            raise ValueError(f"未知 data_provider: {self.data_provider}")

        data_cfg = config.get("data", {})
        self.cache_dir = Path(data_cfg.get("cache_dir", "./data/cache"))
        self.daily_dir = Path(data_cfg.get("daily_dir", "./data/prices"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        self._bs_logged_in = False

        # DuckDB 共享 store（lazy）；用 hot path 替代 CSV 读取。
        # 配置 data.duckdb_path 控制位置；未配置默认 data/quant.duckdb。
        self._duckdb_path = data_cfg.get("duckdb_path", "data/quant.duckdb")
        self._store = None  # 延迟初始化

    def _get_store(self):
        if self._store is None:
            from quant_system.data import DuckDBStore
            try:
                self._store = DuckDBStore(self._duckdb_path)
            except ImportError:
                self._store = False  # 标记不可用，避免重试
        return self._store if self._store else None

    def _login(self) -> None:
        _require_bs()
        if not self._bs_logged_in:
            lg = bs.login()
            if lg.error_code != "0":
                raise RuntimeError(f"BaoStock login failed: {lg.error_msg}")
            self._bs_logged_in = True

    def _logout(self) -> None:
        if self._bs_logged_in:
            bs.logout()
            self._bs_logged_in = False

    # ── Universe ─────────────────────────────────────────────────────────────

    def get_universe(self, asof: str) -> list[str]:
        """返回满足 universe 过滤条件的 A 股代码列表."""
        cache_path = self.cache_dir / f"universe_{asof}.csv"
        if cache_path.exists() and self._cache_fresh(cache_path):
            return pd.read_csv(cache_path, dtype={"code": str})["code"].tolist()

        codes, _names = self._fetch_universe(asof)
        # 向后兼容: 旧调用方读 universe_<date>.csv 只取 code 列;
        # 新调用方走 get_name_map() 读同文件的 name 列
        out = pd.DataFrame({"code": codes})
        if _names:
            out["name"] = [_names.get(c, "") for c in codes]
        out.to_csv(cache_path, index=False)
        return codes

    def get_name_map(self, asof: str) -> dict[str, str]:
        """code -> 股票名称 映射. 三级 fallback:
        1. universe_<date>.csv 有 name 列直接读 (新格式 cache, ~ms)
        2. names_<date>.csv 单文件缓存 (~ms)
        3. baostock query_stock_basic 全量拉 (~5s, 不走慢的 totalShare 路径)

        dashboard / daily 报告需要给持仓 + top_candidates 填中文名.
        """
        # ── L1: universe cache 新格式
        uni_cache = self.cache_dir / f"universe_{asof}.csv"
        if uni_cache.exists() and self._cache_fresh(uni_cache):
            df = pd.read_csv(uni_cache, dtype={"code": str})
            if "name" in df.columns:
                return dict(zip(df["code"], df["name"].fillna("").astype(str)))

        # ── L2: 专用 names cache
        names_cache = self.cache_dir / f"names_{asof}.csv"
        if names_cache.exists() and self._cache_fresh(names_cache):
            df = pd.read_csv(names_cache, dtype={"code": str})
            return dict(zip(df["code"], df["name"].fillna("").astype(str)))

        # ── L3: 直接 query_stock_basic (5s 内, 不算 totalShare/价格那些慢字段)
        self._login()
        rs = bs.query_stock_basic()
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        df = pd.DataFrame(rows, columns=rs.fields)
        df = df[(df["type"] == "1") & (df["status"] == "1")].copy()
        df["plain_code"] = df["code"].apply(_to_plain_code)
        out = pd.DataFrame({"code": df["plain_code"], "name": df["code_name"]})
        out.to_csv(names_cache, index=False)
        return dict(zip(out["code"], out["name"].fillna("").astype(str)))

    def _fetch_universe(self, asof: str) -> tuple[list[str], dict[str, str]]:
        """
        用 BaoStock 拉全量 A 股基本信息，过滤市值/ST/上市天数/价格。

        市值估算：totalShare（万股，季报）× 近期收盘价
        精度足够做 5-200亿市值筛选，误差在季报披露延迟（约1-3个月）内。

        Phase 1-C: universe 字段优先从 market_cfg.universe 读 (新 markets 结构);
        缺失回退顶层 config.universe (legacy)。
        """
        self._login()
        ucfg = self.market_cfg.get("universe") or self.config.get("universe", {})
        cap_min = float(ucfg.get("market_cap_min_cny", 5e9))
        cap_max = float(ucfg.get("market_cap_max_cny", 2e11))
        min_listed = int(ucfg.get("min_listed_days", 365))
        min_price = float(ucfg.get("min_price", 2.0))
        exclude_st = bool(ucfg.get("exclude_st", True))
        asof_ts = pd.Timestamp(asof)

        # ── 1. 全量股票基本信息
        rs = bs.query_stock_basic()
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        all_df = pd.DataFrame(rows, columns=rs.fields)

        # 只保留普通A股（type=1）、上市中（status=1）
        all_df = all_df[(all_df["type"] == "1") & (all_df["status"] == "1")].copy()
        all_df["plain_code"] = all_df["code"].apply(_to_plain_code)

        # 上市时间过滤
        all_df["ipoDate"] = pd.to_datetime(all_df["ipoDate"], errors="coerce")
        all_df = all_df[(asof_ts - all_df["ipoDate"]).dt.days >= min_listed]

        # ST 过滤
        if exclude_st:
            all_df = all_df[~all_df["code_name"].str.contains("ST", na=False)]

        print(f"[loader] 基础过滤后: {len(all_df)} 只", flush=True)

        # ── 2. 用季报总股本 × 近期收盘价估算市值
        #    先批量拿近期价格（最近1个交易日），再逐只查总股本（带缓存）
        shares_cache = self.cache_dir / "bs_shares.csv"
        if shares_cache.exists() and self._cache_fresh(shares_cache, max_days=30):
            shares_df = pd.read_csv(shares_cache, dtype={"code": str})
        else:
            print(f"[loader] 正在拉取总股本（约需1-2分钟）...", flush=True)
            share_rows = []
            codes_list = all_df["code"].tolist()
            for i, code in enumerate(codes_list, 1):
                if i % 500 == 0:
                    print(f"  [{i}/{len(codes_list)}]", flush=True)
                try:
                    # Q4年报：4月底前查上上年，4月底后查上年
                    profit_year = asof_ts.year - 1 if asof_ts.month >= 5 else asof_ts.year - 2
                    rs2 = bs.query_profit_data(
                        code=code,
                        year=profit_year,
                        quarter=4,
                    )
                    d2 = []
                    while rs2.error_code == "0" and rs2.next():
                        d2.append(rs2.get_row_data())
                    if d2:
                        total_share = float(d2[0][rs2.fields.index("totalShare")] or 0)
                    else:
                        total_share = 0.0
                except Exception:
                    total_share = 0.0
                share_rows.append({"code": code, "total_share": total_share})
            shares_df = pd.DataFrame(share_rows)
            shares_df.to_csv(shares_cache, index=False)

        shares_df["code"] = shares_df["code"].astype(str)
        all_df = all_df.merge(shares_df, on="code", how="left")
        all_df["total_share"] = pd.to_numeric(all_df["total_share"], errors="coerce").fillna(0)

        # 2025Q4 可能缺失（部分公司未披露），回退到 2024Q4
        missing_codes = all_df.loc[all_df["total_share"] == 0, "code"].tolist()
        if missing_codes:
            print(f"[loader] 回退到 2024Q4 补充 {len(missing_codes)} 只缺失股本...", flush=True)
            fallback_rows = []
            for code in missing_codes:
                try:
                    rs_fb = bs.query_profit_data(code=code, year=profit_year - 1, quarter=4)
                    d_fb = []
                    while rs_fb.error_code == "0" and rs_fb.next():
                        d_fb.append(rs_fb.get_row_data())
                    if d_fb:
                        ts = float(d_fb[0][rs_fb.fields.index("totalShare")] or 0)
                    else:
                        ts = 0.0
                except Exception:
                    ts = 0.0
                fallback_rows.append({"code": code, "total_share": ts})
            fb_df = pd.DataFrame(fallback_rows)
            fb_df["code"] = fb_df["code"].astype(str)
            # update all_df in-place
            all_df = all_df.set_index("code")
            fb_df = fb_df.set_index("code")
            all_df.loc[all_df["total_share"] == 0, "total_share"] = fb_df["total_share"]
            all_df = all_df.reset_index()

        # 近期收盘价 — 只查有股本数据的股票，重连后再查（避免长时间空闲后TCP断开）
        start_dt = (asof_ts - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        end_dt = asof
        # 重新登录刷新连接
        bs.logout()
        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"BaoStock re-login failed: {lg.error_msg}")
        codes_with_shares = all_df.loc[all_df["total_share"] > 0, "code"].tolist()
        print(f"[loader] 正在拉取 {len(codes_with_shares)} 只有股本数据的股票价格...", flush=True)
        price_rows = []
        for i, code in enumerate(codes_with_shares, 1):
            if i % 500 == 0:
                print(f"  [price {i}/{len(codes_with_shares)}]", flush=True)
            try:
                rs3 = bs.query_history_k_data_plus(
                    code, "date,close",
                    start_date=start_dt, end_date=end_dt,
                    frequency="d", adjustflag="3",
                )
                d3 = []
                while rs3.error_code == "0" and rs3.next():
                    d3.append(rs3.get_row_data())
                if d3:
                    price_rows.append({"code": code, "close": float(d3[-1][1] or 0)})
            except Exception:
                pass

        price_df = pd.DataFrame(price_rows)
        if not price_df.empty:
            price_df["code"] = price_df["code"].astype(str)
            all_df = all_df.merge(price_df, on="code", how="left")
        else:
            all_df["close"] = 0.0
        self._bs_logged_in = True  # 标记重连完成

        all_df["close"] = pd.to_numeric(all_df["close"], errors="coerce").fillna(0)
        # total_share 已在上方转换；此处确保类型一致
        all_df["total_share"] = pd.to_numeric(all_df["total_share"], errors="coerce").fillna(0)
        # 市值（元）= 总股本（股）× 收盘价；BaoStock totalShare 单位是股
        all_df["market_cap"] = all_df["total_share"] * all_df["close"]

        # ── 3. 应用市值 + 价格过滤
        filtered = all_df[
            (all_df["market_cap"] >= cap_min) &
            (all_df["market_cap"] <= cap_max) &
            (all_df["close"] >= min_price) &
            (all_df["total_share"] > 0)
        ]

        print(f"[loader] 市值{cap_min/1e8:.0f}-{cap_max/1e8:.0f}亿 + 价格≥{min_price}: {len(filtered)} 只", flush=True)
        codes_sorted = sorted(filtered["plain_code"].tolist())
        name_map = dict(zip(filtered["plain_code"], filtered["code_name"]))
        return codes_sorted, name_map

    # ── 日线行情 ───────────────────────────────────────────────────────────────

    def get_daily(self, code: str, start: str, end: str) -> pd.DataFrame:
        """
        获取日线行情. 返回 date/open/high/low/close/volume/turnover_rate 列.

        优先级:
          1. DuckDB (data/quant.duckdb) — 命中即返回, sub-ms 响应
          2. data/prices/{code}_daily.csv — fallback (灾备)
          3. BaoStock 远程拉取 — 缓存不存在时
        """
        code = str(code).zfill(6)

        # 1. DuckDB hot path - Phase 1-C: 用 self.market 而非硬码 "a_share"
        store = self._get_store()
        if store is not None and store.has_code(self.market, code):
            df = store.get_daily(self.market, code, start, end)
            if not df.empty:
                return df.reset_index(drop=True)

        # 2. CSV fallback
        csv_path = self.daily_dir / f"{code}_daily.csv"
        if csv_path.exists() and self._cache_fresh(csv_path):
            df = pd.read_csv(csv_path, dtype={"date": str})
            df["date"] = pd.to_datetime(df["date"])
            mask = (df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))
            return df[mask].reset_index(drop=True)

        # 3. BaoStock 远程
        df = self._fetch_daily(code)
        if df is not None and not df.empty:
            df.to_csv(csv_path, index=False)
            # 同时写入 DuckDB 让下次更快 - Phase 1-C: 用 self.market
            if store is not None:
                try:
                    store.insert_daily(self.market, code, df, replace=True)
                except Exception:
                    pass
            df["date"] = pd.to_datetime(df["date"])
            mask = (df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))
            return df[mask].reset_index(drop=True)
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "turnover_rate"])

    def _fetch_daily(self, code: str) -> Optional[pd.DataFrame]:
        self._login()
        bs_code = _to_bs_code(code)
        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,turn",
                start_date="2020-01-01",
                end_date=datetime.now().strftime("%Y-%m-%d"),
                frequency="d",
                adjustflag="2",   # 前复权
            )
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())
            if not rows:
                return None
            df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "turnover_rate"])
            for col in ["open", "high", "low", "close", "volume", "turnover_rate"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["close"])
            return df
        except Exception as e:
            import sys
            print(f"[WARN] _fetch_daily({code}): {e}", file=sys.stderr)
            return None

    # ── ATR ───────────────────────────────────────────────────────────────────

    @staticmethod
    def compute_atr(df: pd.DataFrame, period: int = _ATR_PERIOD) -> pd.Series:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    # ── 工具 ──────────────────────────────────────────────────────────────────

    def _cache_fresh(self, path: Path, max_days: Optional[float] = None) -> bool:
        days = max_days if max_days is not None else self.refresh_days
        age_days = (time.time() - os.path.getmtime(path)) / 86400
        return age_days < days
