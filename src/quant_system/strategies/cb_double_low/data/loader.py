"""CBDataLoader — 可转债数据接口 (PR3 实现).

封装 akshare 4 端点 (probe PASS, 见 memory/cb_data_probe_2026-06.md)：
- bond_zh_cov()                       → universe 池 (含退市债)
- bond_zh_cov_value_analysis(symbol)  → 个券日级面板 (价格 + 4 溢价率字段)
- bond_cb_redeem_jsl()                → 强赎事件
- bond_zh_hs_cov_spot()               → 实时 spot (实盘 daily)

上层模块 (strategy / backtest / daily) 不直接 import akshare, 全部收敛到这里.
日级面板 DuckDB cache 表 cb_panel PRIMARY KEY (date, bond_code).

字段映射 (akshare 中文 → 内部英文 schema): 见各方法内 _RENAME 字典.
"""
from __future__ import annotations

import sys
import threading
import time
from datetime import date
from pathlib import Path
from typing import Optional

import akshare as ak
import pandas as pd

try:
    import duckdb
except ImportError:  # pragma: no cover
    duckdb = None  # type: ignore


class CBDataLoader:
    """可转债数据 loader. cache_dir 下放 cb_cache.duckdb 单文件 cache."""

    UNIVERSE_COLUMNS = (
        "bond_code",
        "bond_name",
        "stock_code",
        "stock_name",
        "listing_date",
        "delisting_date",
        "scale_remain",
        "credit_rating",
        "exit_status",
    )
    PANEL_COLUMNS = (
        "date",
        "bond_code",
        "close",
        "pure_bond_value",
        "conversion_value",
        "pure_bond_premium_rate",
        "conversion_premium_rate",
    )
    REDEMPTION_COLUMNS = (
        "bond_code",
        "bond_name",
        "announcement_date",
        "last_trading_date",
        "maturity_date",
        "redemption_price",
        "status",
    )
    SPOT_COLUMNS = (
        "bond_code",
        "bond_name",
        "close",
        "change_pct",
        "volume",
        "amount",
    )

    # ── 字段映射 (akshare 中文 → 英文 schema) ───────────────────────────

    _UNIVERSE_RENAME = {
        "债券代码": "bond_code",
        "债券简称": "bond_name",
        "正股代码": "stock_code",
        "正股简称": "stock_name",
        "上市时间": "listing_date",
        "发行规模": "scale_remain",  # bond_zh_cov 字段是发行规模; 剩余规模另查 redeem
        "信用评级": "credit_rating",
    }
    _PANEL_RENAME = {
        "日期": "date",
        "收盘价": "close",
        "纯债价值": "pure_bond_value",
        "转股价值": "conversion_value",
        "纯债溢价率": "pure_bond_premium_rate",
        "转股溢价率": "conversion_premium_rate",
    }
    _REDEMPTION_RENAME = {
        "代码": "bond_code",
        "名称": "bond_name",
        "最后交易日": "last_trading_date",
        "到期日": "maturity_date",
        "强赎价": "redemption_price",
        "强赎状态": "status",
    }
    _SPOT_RENAME = {
        "code": "bond_code",
        "name": "bond_name",
        "trade": "close",
        "changepercent": "change_pct",
        "volume": "volume",
        "amount": "amount",
    }

    def __init__(self, cache_dir: Path, refresh_days: int = 1) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.refresh_days = int(refresh_days)
        self._db_path = self.cache_dir / "cb_cache.duckdb"
        self._lock = threading.RLock()
        self._con: "duckdb.DuckDBPyConnection | None" = None  # type: ignore

    # ── DuckDB ──────────────────────────────────────────────────────────

    def _connect(self) -> "duckdb.DuckDBPyConnection":  # type: ignore
        if duckdb is None:
            raise ImportError("duckdb 未安装。pip install duckdb")
        if self._con is None:
            self._con = duckdb.connect(str(self._db_path))
            self._con.execute(
                """
                CREATE TABLE IF NOT EXISTS cb_panel (
                    date DATE NOT NULL,
                    bond_code VARCHAR NOT NULL,
                    close DOUBLE,
                    pure_bond_value DOUBLE,
                    conversion_value DOUBLE,
                    pure_bond_premium_rate DOUBLE,
                    conversion_premium_rate DOUBLE,
                    PRIMARY KEY (date, bond_code)
                )
                """
            )
        return self._con

    def close(self) -> None:
        with self._lock:
            if self._con is not None:
                self._con.close()
                self._con = None

    # ── 1. universe ─────────────────────────────────────────────────────

    def load_universe(self, asof: Optional[date] = None) -> pd.DataFrame:
        """全市场可转债池 (含退市). asof 排除未来上市债 + 标 exit_status."""
        raw = ak.bond_zh_cov()
        df = raw.rename(columns=self._UNIVERSE_RENAME).copy()
        df["bond_code"] = df["bond_code"].astype(str)
        df["listing_date"] = pd.to_datetime(df["listing_date"], errors="coerce")
        # asof 过滤: 未来上市 + NaT 一并排除 (NaT 即"未上市/招标中")
        if asof is not None:
            asof_ts = pd.Timestamp(asof)
            df = df[df["listing_date"].notna() & (df["listing_date"] <= asof_ts)].copy()
        # 合并强赎/退市状态
        try:
            redeem_raw = ak.bond_cb_redeem_jsl()
            redeem = redeem_raw.rename(columns={"代码": "bond_code", "强赎状态": "_redeem_status"})
            redeem["bond_code"] = redeem["bond_code"].astype(str)
            df = df.merge(
                redeem[["bond_code", "_redeem_status"]],
                on="bond_code",
                how="left",
            )
        except Exception:
            df["_redeem_status"] = pd.NA
        # redeem 表里 "强赎状态" 可能是 NaN (未在 redeem 表) 也可能是 "" (在表但状态空).
        # 两者都视为 active. 修于 2026-06-15 mini-backfill 发现 247/1012 空字符串.
        df["exit_status"] = (
            df["_redeem_status"]
            .fillna("active")
            .astype(str)
            .replace("", "active")
        )
        # 占位列 (PR4+ 补)
        if "delisting_date" not in df.columns:
            df["delisting_date"] = pd.NaT
        if "stock_code" not in df.columns:
            df["stock_code"] = ""
        if "stock_name" not in df.columns:
            df["stock_name"] = ""
        if "credit_rating" not in df.columns:
            df["credit_rating"] = ""
        if "scale_remain" not in df.columns:
            df["scale_remain"] = pd.NA
        return df[list(self.UNIVERSE_COLUMNS)].reset_index(drop=True)

    # ── 2. panel (DuckDB cached) ────────────────────────────────────────

    def load_panel(
        self,
        start: date,
        end: date,
        codes: Optional[list[str]] = None,
    ) -> pd.DataFrame:
        """日级面板 (date, bond_code, close + 2 价值 + 2 溢价率).

        Cache 策略: 每个 code 在 cb_panel 表内若 [start, end] 范围有任意行
        视为已 cache (不重 fetch). 完全 missing 的 code 走 akshare 拉全历史,
        UPSERT 写 cache, 再 SELECT 切片.
        """
        if codes is None:
            raise NotImplementedError(
                "PR4: codes=None 全市场 panel 待 load_universe 集成"
            )
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        con = self._connect()
        # 检查每个 code 在 [start, end] 范围 cache 命中
        missing: list[str] = []
        with self._lock:
            for code in codes:
                code_str = str(code)
                row = con.execute(
                    "SELECT COUNT(*) FROM cb_panel "
                    "WHERE bond_code = ? AND date BETWEEN ? AND ?",
                    [code_str, start_ts.date(), end_ts.date()],
                ).fetchone()
                if row is None or row[0] == 0:
                    missing.append(code_str)
            # 拉缺失. akshare 端点对部分债 (新挂牌/特殊状态/退市边界) 内部解析失败抛 TypeError,
            # 不只是 return None — 必须 try/except 整个调用. Regression: 2026-06-16 --n 0 backfill
            # 跑到 ~920/946 只挂在 ak 内部 pd.DataFrame(data_json["result"]["data"]) NoneType.
            #
            # 2026-06-16 17:00 launchd run: 单 code 触发 curl_cffi Timeout 141s, 拖死整个
            # panel (走 sys.exit). 加 2 层防护:
            #   1. 数据解析异常 (TypeError/KeyError/...) → 立即 skip (旧逻辑)
            #   2. 网络异常 (Timeout/CurlError/ConnectionError/...) → 2 次短退避重试
            #   3. 任何漏网异常 (Exception) → skip + 计数, 不抛 (loop tolerance)
            # 统计计数 ok / fail_parse / fail_net, 收尾打印.
            stats = {"ok": 0, "fail_parse": 0, "fail_net": 0}
            for code in missing:
                raw = None
                for attempt in range(3):  # 1 + 2 重试
                    try:
                        raw = ak.bond_zh_cov_value_analysis(symbol=code)
                        stats["ok"] += 1
                        break
                    except (TypeError, KeyError, AttributeError, ValueError):
                        # 解析失败 = 该 code akshare 数据形态异常, 不重试
                        stats["fail_parse"] += 1
                        raw = None
                        break
                    except Exception as e:  # noqa: BLE001  网络层全捕, 防 daily 整体挂
                        # curl_cffi Timeout / CurlError / ConnectionError / 远程 500 等
                        if attempt < 2:
                            time.sleep(1.5 * (attempt + 1))  # 1.5s, 3s
                            continue
                        # 第 3 次仍挂 = skip
                        stats["fail_net"] += 1
                        print(
                            f"  [cb_panel] {code} 网络异常 3 次重试均失败 "
                            f"({type(e).__name__}): skip",
                            file=sys.stderr,
                        )
                        raw = None
                if raw is None or len(raw) == 0:
                    continue
                df = raw.rename(columns=self._PANEL_RENAME).copy()
                df["date"] = pd.to_datetime(df["date"], errors="coerce")
                df = df.dropna(subset=["date"]).copy()
                df["bond_code"] = code
                df = df[list(self.PANEL_COLUMNS)]
                con.register("_cb_tmp", df)
                con.execute(
                    """
                    INSERT INTO cb_panel
                    SELECT date::DATE, bond_code, close, pure_bond_value,
                           conversion_value, pure_bond_premium_rate,
                           conversion_premium_rate
                    FROM _cb_tmp
                    ON CONFLICT (date, bond_code) DO UPDATE SET
                        close = EXCLUDED.close,
                        pure_bond_value = EXCLUDED.pure_bond_value,
                        conversion_value = EXCLUDED.conversion_value,
                        pure_bond_premium_rate = EXCLUDED.pure_bond_premium_rate,
                        conversion_premium_rate = EXCLUDED.conversion_premium_rate
                    """
                )
                con.unregister("_cb_tmp")
            # 收尾打印 missing 拉取统计 (仅当真有 missing 时, 避免 noop log)
            if missing:
                print(
                    f"  [cb_panel] missing={len(missing)} ok={stats['ok']} "
                    f"fail_parse={stats['fail_parse']} fail_net={stats['fail_net']}",
                    flush=True,
                )
            # SELECT 切片
            placeholders = ",".join(["?"] * len(codes))
            out = con.execute(
                f"SELECT date, bond_code, close, pure_bond_value, conversion_value, "
                f"pure_bond_premium_rate, conversion_premium_rate "
                f"FROM cb_panel "
                f"WHERE bond_code IN ({placeholders}) AND date BETWEEN ? AND ? "
                f"ORDER BY date, bond_code",
                [*[str(c) for c in codes], start_ts.date(), end_ts.date()],
            ).fetchdf()
        out["date"] = pd.to_datetime(out["date"])
        return out

    # ── 3. redemption events ────────────────────────────────────────────

    def load_redemption_events(self, asof: Optional[date] = None) -> pd.DataFrame:
        """强赎事件. announcement_date akshare 不直接给, PR4+ 接入 (本 PR NaT 占位)."""
        raw = ak.bond_cb_redeem_jsl()
        df = raw.rename(columns=self._REDEMPTION_RENAME).copy()
        df["bond_code"] = df["bond_code"].astype(str)
        df["last_trading_date"] = pd.to_datetime(df["last_trading_date"], errors="coerce")
        df["maturity_date"] = pd.to_datetime(df["maturity_date"], errors="coerce")
        # PR3 占位: announcement_date 字段未在 akshare 直接暴露, 置 NaT
        # asof 过滤仅对 notna 的行生效 (此处全 NaT -> 不过滤, 安全)
        df["announcement_date"] = pd.NaT
        if asof is not None:
            asof_ts = pd.Timestamp(asof)
            mask_known = df["announcement_date"].notna()
            df = df[(~mask_known) | (df["announcement_date"] <= asof_ts)].copy()
        return df[list(self.REDEMPTION_COLUMNS)].reset_index(drop=True)

    # ── 4. spot ─────────────────────────────────────────────────────────

    def get_spot_today(self) -> pd.DataFrame:
        """实时全市场 CB spot. 实盘 daily ranking 入口."""
        raw = ak.bond_zh_hs_cov_spot()
        df = raw.rename(columns=self._SPOT_RENAME).copy()
        df["bond_code"] = df["bond_code"].astype(str)
        return df[list(self.SPOT_COLUMNS)].reset_index(drop=True)
