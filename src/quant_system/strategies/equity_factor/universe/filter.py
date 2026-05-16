"""
Universe 过滤器：把“全市场扫描”收敛到“可交易的干净子集”。

设计目标（无黑盒）：
  - 每个 asof 输出：过滤前数量、过滤后数量、每条规则剔除数量、缺失数量
  - 对每只股票输出：每条规则的 pass/fail + 关键数值（便于回溯/压力测试）

注意（避免未来函数）：
  - 所有财务/市值数据必须以 asof 为截断（<= asof 的最新值）
  - 价格用 DataLoader 当前 price_adjust（推荐 raw）
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from quant_system.strategies.equity_factor.data.loader import DataLoader


@dataclass(frozen=True)
class UniverseFilterConfig:
    # --- 流动性/价格（硬过滤，daily 动态） ---
    daily_turnover_min: float = 5_000_000.0   # 成交额(近似=close*volume) >= 500万
    market_cap_min_billion: float = 20.0      # 总市值 >= 20亿
    ma20_price_min: float = 5.0               # MA20 >= 5 元

    # --- 质量门槛（硬过滤） ---
    roe_min: float = 0.05                     # ROE >= 5%
    debt_ratio_max: float = 0.70              # 资产负债率 <= 70%（若缺失则剔除，保证“硬过滤”语义）

    # --- 动态剔除 ---
    min_listed_days: int = 180                # 上市不足 180 个交易日（用可得日线数量近似）
    suspension_lookback_days: int = 10        # 近 N 日出现停牌(成交量=0 或缺 bar)则剔除


def _to_date_str(asof: str | datetime) -> str:
    if isinstance(asof, datetime):
        return asof.strftime("%Y-%m-%d")
    if isinstance(asof, str) and len(asof) == 8 and asof.isdigit():
        return datetime.strptime(asof, "%Y%m%d").strftime("%Y-%m-%d")
    return str(asof)


def _safe_float(x) -> float | None:
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except Exception:
        pass
    try:
        return float(x)
    except Exception:
        return None


class UniverseFilter:
    def __init__(self, loader: DataLoader, cfg: Optional[UniverseFilterConfig] = None):
        self.loader = loader
        self.cfg = cfg or UniverseFilterConfig()
        # price cache: code -> DataFrame(date, close, volume, ma20, turnover_est)
        self._price_cache: dict[str, pd.DataFrame] = {}
        self._price_cache_built = False

    def _build_price_cache(self, codes: list[str]) -> None:
        """
        一次性构建价格缓存（每只股票只读一次 parquet / cache），避免每个 asof 反复 IO。
        缓存内容包含：close、volume、turnover_est、ma20（rolling 20）。
        """
        if self._price_cache_built:
            return
        n_total = len(codes)
        for i, code in enumerate(codes, 1):
            if code in self._price_cache:
                continue
            try:
                px = self.loader.get_daily("a_share", code, "2018-01-01", "2030-01-01")
            except Exception:
                continue
            if px is None or px.empty:
                continue
            s = px[["date", "close", "volume"]].copy()
            s["close"] = pd.to_numeric(s["close"], errors="coerce")
            s["volume"] = pd.to_numeric(s["volume"], errors="coerce")
            s = s.dropna(subset=["date", "close", "volume"])
            if s.empty:
                continue
            s["turnover_est"] = s["close"] * s["volume"]
            s["ma20"] = s["close"].rolling(20, min_periods=20).mean()
            self._price_cache[code] = s
            if i % 200 == 0:
                print(f"  universe price cache: {i}/{n_total} built", flush=True)
        self._price_cache_built = True
        print(f"  universe price cache: DONE ({len(self._price_cache)}/{n_total})", flush=True)

    def filter_a_share(self, universe_df: pd.DataFrame, asof: str | datetime) -> tuple[pd.DataFrame, dict]:
        """
        输入：universe_df(code,name)，输出：(filtered_df, stats)

        filtered_df 含列：
          - code, name
          - close, volume, turnover_est, ma20
          - market_cap, roe, debt_ratio
          - is_limit_up, is_limit_down, recent_suspension
          - pass_* 布尔列（逐条规则）
        """
        asof_str = _to_date_str(asof)
        cfg = self.cfg

        df = universe_df.copy()
        df["code"] = df["code"].astype(str)
        if "name" in df.columns:
            df["name"] = df["name"].astype(str)
        else:
            df["name"] = ""

        # build price cache once (critical for performance in backtest)
        self._build_price_cache(df["code"].tolist())

        # ---------- 动态涨跌停（用东财涨停/跌停池；缺失时退化为“不剔除”，但会在 stats 里记录） ----------
        limit_up_set: set[str] = set()
        limit_down_set: set[str] = set()
        limit_data_ok = True
        try:
            zt = self.loader.get_zt_pool(asof_str)
            if zt is not None and not zt.empty and "代码" in zt.columns:
                limit_up_set = set(zt["代码"].astype(str).tolist())
        except Exception:
            limit_data_ok = False
        try:
            dt = self.loader.get_dt_pool(asof_str)
            if dt is not None and not dt.empty and "代码" in dt.columns:
                limit_down_set = set(dt["代码"].astype(str).tolist())
        except Exception:
            limit_data_ok = False

        # ---------- 逐票内存查表：先做“便宜过滤”把规模砍下来 ----------
        rows = []
        n_no_bar = 0
        n_short_hist = 0
        for code, name in zip(df["code"], df["name"]):
            px = self._price_cache.get(code)
            if px is None or px.empty:
                n_no_bar += 1
                continue
            sub = px[px["date"] <= asof_str]
            if sub.empty:
                n_no_bar += 1
                continue
            # 上市不足 min_listed_days：用可得交易日数量近似
            listed_days = len(sub)
            if listed_days < cfg.min_listed_days:
                n_short_hist += 1
            last = sub.iloc[-1]
            close = _safe_float(last.get("close"))
            vol = _safe_float(last.get("volume"))
            if close is None or vol is None:
                n_no_bar += 1
                continue
            turnover = _safe_float(last.get("turnover_est")) or (close * vol)
            ma20 = _safe_float(last.get("ma20"))
            ma20 = float(ma20) if ma20 is not None else np.nan
            # 近 N 日停牌：volume=0 视为停牌/无成交
            recent = sub.tail(cfg.suspension_lookback_days)
            recent_susp = bool((pd.to_numeric(recent["volume"], errors="coerce").fillna(0) <= 0).any())

            rows.append({
                "code": code,
                "name": name,
                "close": close,
                "volume": vol,
                "turnover_est": turnover,
                "ma20": ma20,
                "listed_days": listed_days,
                "recent_suspension": recent_susp,
                "is_limit_up": code in limit_up_set,
                "is_limit_down": code in limit_down_set,
            })

        base = pd.DataFrame(rows)
        if base.empty:
            stats = {
                "asof": asof_str,
                "input_n": int(len(df)),
                "output_n": 0,
                "limit_data_ok": limit_data_ok,
                "dropped_no_bar": int(n_no_bar),
                "dropped_short_history": int(n_short_hist),
                "config": asdict(cfg),
                "rule_counts": {},
            }
            return base, stats

        # --- 规则：上市天数 / 停牌 / 涨跌停 ---
        base["pass_listed_days"] = base["listed_days"] >= cfg.min_listed_days
        base["pass_no_suspension"] = ~base["recent_suspension"]
        base["pass_not_limit"] = ~(base["is_limit_up"] | base["is_limit_down"])

        # --- 规则：流动性 / 价格 ---
        base["pass_turnover"] = base["turnover_est"] >= cfg.daily_turnover_min
        base["pass_ma20_price"] = pd.to_numeric(base["ma20"], errors="coerce") >= cfg.ma20_price_min

        # 先应用便宜规则，缩小后再取市值/财务（避免全市场拉 fundamentals）
        cheap_mask = (
            base["pass_listed_days"]
            & base["pass_no_suspension"]
            & base["pass_not_limit"]
            & base["pass_turnover"]
            & base["pass_ma20_price"]
        )
        stage1 = base[cheap_mask].copy()

        # ---------- 市值/财务（以 asof 截断；缺失视为不通过硬过滤） ----------
        market_caps = []
        roes = []
        debts = []
        for code in stage1["code"].tolist():
            # 市值：valuation.total_mv（单位取 akshare 原始；只做“>=阈值”比较，阈值以“元”为准：20亿=2e10）
            mc = None
            try:
                val = self.loader.get_a_share_valuation(code)
                val = val[val["date"] <= asof_str]
                if not val.empty and "total_mv" in val.columns:
                    mc = _safe_float(pd.to_numeric(val["total_mv"], errors="coerce").dropna().iloc[-1])  # type: ignore[index]
            except Exception:
                mc = None

            roe = None
            try:
                abs_df = self.loader.get_a_share_abstract(code)
                # akshare abstract 常见为百分数（如 8.3 表示 8.3%），这里统一转成小数
                raw = self.loader.latest_indicator_value(abs_df, "净资产收益率(ROE)", asof=asof_str)
                if raw is not None:
                    roe = float(raw) / 100.0 if raw > 1.5 else float(raw)
            except Exception:
                roe = None

            debt = None
            try:
                debt = self.loader.get_a_share_debt_ratio(code, asof=asof_str)
            except Exception:
                debt = None

            market_caps.append(mc)
            roes.append(roe)
            debts.append(debt)

        stage1["market_cap"] = market_caps
        stage1["roe"] = roes
        stage1["debt_ratio"] = debts

        stage1["pass_market_cap"] = pd.to_numeric(stage1["market_cap"], errors="coerce") >= (cfg.market_cap_min_billion * 1e9)
        stage1["pass_roe"] = pd.to_numeric(stage1["roe"], errors="coerce") >= cfg.roe_min
        stage1["pass_debt_ratio"] = pd.to_numeric(stage1["debt_ratio"], errors="coerce") <= cfg.debt_ratio_max

        full_mask = (
            stage1["pass_market_cap"].fillna(False)
            & stage1["pass_roe"].fillna(False)
            & stage1["pass_debt_ratio"].fillna(False)
        )
        out = stage1[full_mask].copy()

        # ---------- stats（逐条规则剔除数） ----------
        def _count_false(s: pd.Series) -> int:
            return int((~s.fillna(False)).sum())

        rule_counts = {
            "pass_listed_days_false": _count_false(base["pass_listed_days"]),
            "pass_no_suspension_false": _count_false(base["pass_no_suspension"]),
            "pass_not_limit_false": _count_false(base["pass_not_limit"]),
            "pass_turnover_false": _count_false(base["pass_turnover"]),
            "pass_ma20_price_false": _count_false(base["pass_ma20_price"]),
            "stage1_after_cheap": int(len(stage1)),
            "pass_market_cap_false": _count_false(stage1["pass_market_cap"]) if len(stage1) else 0,
            "pass_roe_false": _count_false(stage1["pass_roe"]) if len(stage1) else 0,
            "pass_debt_ratio_false": _count_false(stage1["pass_debt_ratio"]) if len(stage1) else 0,
        }

        stats = {
            "asof": asof_str,
            "input_n": int(len(df)),
            "base_n": int(len(base)),
            "output_n": int(len(out)),
            "limit_data_ok": bool(limit_data_ok),
            "dropped_no_bar": int(n_no_bar),
            "dropped_short_history": int(n_short_hist),
            "missing_market_cap": int(pd.isna(stage1["market_cap"]).sum()) if len(stage1) else 0,
            "missing_roe": int(pd.isna(stage1["roe"]).sum()) if len(stage1) else 0,
            "missing_debt_ratio": int(pd.isna(stage1["debt_ratio"]).sum()) if len(stage1) else 0,
            "config": asdict(cfg),
            "rule_counts": rule_counts,
        }

        return out.reset_index(drop=True), stats

