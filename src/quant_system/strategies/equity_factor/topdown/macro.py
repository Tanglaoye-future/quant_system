"""
自上而下: 宏观周期 -> 行业景气 -> 候选池.

数据源 (akshare):
  宏观:  macro_china_cpi_monthly, macro_china_ppi
  行业:  stock_board_industry_name_em, stock_board_industry_hist_em,
        stock_board_industry_cons_em (东财行业, 含一级 + 概念)

简化 4 象限分类 (基于 CPI 同比 + PPI 同比方向):
  - Recovery:    CPI↓ + PPI↑   (成本下行 + 企业景气回暖)
  - Expansion:   CPI↑ + PPI↑   (经济过热前夕)
  - Stagflation: CPI↑ + PPI↓   (滞胀)
  - Recession:   CPI↓ + PPI↓   (通缩衰退)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import akshare as ak
import numpy as np
import pandas as pd


# ---------- 宏观 ----------

@dataclass
class MacroSnapshot:
    cpi_yoy: Optional[float] = None
    cpi_yoy_3m_ago: Optional[float] = None
    ppi_yoy: Optional[float] = None
    ppi_yoy_3m_ago: Optional[float] = None
    regime: str = "unknown"            # recovery / expansion / stagflation / recession
    cpi_direction: str = "?"           # rising / falling
    ppi_direction: str = "?"
    asof_cpi: Optional[str] = None
    asof_ppi: Optional[str] = None


def _safe_float(x) -> Optional[float]:
    if x is None or pd.isna(x):
        return None
    try:
        return float(x)
    except (ValueError, TypeError):
        return None


def assess_macro(cache_dir: Path, refresh_days: int = 1) -> MacroSnapshot:
    """拉最新 CPI / PPI 序列, 比较最新和 3 个月前的同比, 判定周期."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    snap = MacroSnapshot()

    # CPI
    try:
        cpi = _load_cached(cache_dir / "macro_cpi.parquet", refresh_days,
                           lambda: ak.macro_china_cpi_monthly())
        # 列: 商品, 日期, 今值, 预测值, 前值. "今值" 是月率, 不是同比!
        # 月率累加近 12 个月得到近似同比. 简化: 直接用最新 12 个月月率之和作为 12M 累计.
        cpi = cpi.dropna(subset=["今值"]).copy()
        cpi["日期"] = pd.to_datetime(cpi["日期"])
        cpi = cpi.sort_values("日期").reset_index(drop=True)
        if len(cpi) >= 15:
            snap.cpi_yoy = float(cpi["今值"].tail(12).sum())
            snap.cpi_yoy_3m_ago = float(cpi["今值"].iloc[-15:-3].sum())
            snap.asof_cpi = cpi["日期"].iloc[-1].strftime("%Y-%m-%d")
            snap.cpi_direction = "rising" if snap.cpi_yoy > snap.cpi_yoy_3m_ago else "falling"
    except Exception:
        pass

    # PPI
    try:
        ppi = _load_cached(cache_dir / "macro_ppi.parquet", refresh_days,
                           lambda: ak.macro_china_ppi())
        # 列: 月份, 当月, 当月同比增长, 累计.  最新在前面 (倒序).
        ppi = ppi.copy()
        ppi["yoy"] = pd.to_numeric(ppi["当月同比增长"], errors="coerce")
        ppi = ppi.dropna(subset=["yoy"]).reset_index(drop=True)
        # 数据是按月份倒序 (新 -> 旧), 第 0 行是最新
        if len(ppi) >= 4:
            snap.ppi_yoy = float(ppi["yoy"].iloc[0])
            snap.ppi_yoy_3m_ago = float(ppi["yoy"].iloc[3])
            snap.asof_ppi = str(ppi["月份"].iloc[0])
            snap.ppi_direction = "rising" if snap.ppi_yoy > snap.ppi_yoy_3m_ago else "falling"
    except Exception:
        pass

    # 4 象限分类 (基于方向)
    if snap.cpi_direction != "?" and snap.ppi_direction != "?":
        if snap.ppi_direction == "rising" and snap.cpi_direction == "falling":
            snap.regime = "recovery"
        elif snap.ppi_direction == "rising" and snap.cpi_direction == "rising":
            snap.regime = "expansion"
        elif snap.ppi_direction == "falling" and snap.cpi_direction == "rising":
            snap.regime = "stagflation"
        else:
            snap.regime = "recession"

    return snap


# ---------- 行业 ----------

@dataclass
class SectorRanking:
    sector: str
    code: str
    pct_chg_today: float       # 当日涨跌幅
    pct_chg_60d: float          # 近 60 日涨幅
    health: float               # 上涨家数 / (上涨 + 下跌)
    score: float                # 综合分


class SectorEngine:
    def __init__(self, cache_dir: Path, refresh_days: int = 1):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.refresh_days = refresh_days

    def _name_table(self) -> pd.DataFrame:
        return _load_cached(
            self.cache_dir / "sector_name_em.parquet",
            self.refresh_days,
            lambda: ak.stock_board_industry_name_em(),
        )

    def _sector_hist(self, sector: str, end: str) -> pd.DataFrame:
        cache = self.cache_dir / f"sector_hist_em_{sector}.parquet"
        if cache.exists() and self._is_fresh(cache):
            return pd.read_parquet(cache)
        start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=120)).strftime("%Y%m%d")
        try:
            df = ak.stock_board_industry_hist_em(
                symbol=sector,
                start_date=start,
                end_date=end.replace("-", ""),
                period="日k",
                adjust="",
            )
            df.to_parquet(cache)
            return df
        except Exception:
            return pd.DataFrame()

    def rank(self, asof: str, top_n: int = 10, only_cached_hist: bool = False) -> list[SectorRanking]:
        names = self._name_table()
        # 列: 排名, 板块名称, 板块代码, 最新价, 涨跌额, 涨跌幅, 总市值, 换手率, 上涨家数, 下跌家数, 领涨股票, 领涨股票-涨跌幅
        rankings: list[SectorRanking] = []
        for _, row in names.iterrows():
            sector = str(row["板块名称"])
            up = _safe_float(row.get("上涨家数")) or 0.0
            down = _safe_float(row.get("下跌家数")) or 0.0
            health = up / (up + down) if (up + down) > 0 else 0.5
            today_chg = _safe_float(row.get("涨跌幅")) or 0.0

            cache_path = self.cache_dir / f"sector_hist_em_{sector}.parquet"
            if only_cached_hist and not cache_path.exists():
                # 没缓存就跳过 60 日动量, 仍能给个基础分
                pct_60d = float("nan")
            else:
                hist = self._sector_hist(sector, asof)
                if hist.empty or len(hist) < 60:
                    pct_60d = float("nan")
                else:
                    closes = pd.to_numeric(hist["收盘"], errors="coerce").dropna()
                    if len(closes) < 60:
                        pct_60d = float("nan")
                    else:
                        pct_60d = float(closes.iloc[-1] / closes.iloc[-60] - 1) * 100

            # 综合分: 60 日动量为主 + 当日涨幅 + 内部健康度
            # 缺动量时, 用 0 替代避免被排末尾
            mom = pct_60d if not np.isnan(pct_60d) else 0.0
            score = 0.6 * mom + 0.3 * today_chg + 0.1 * (health * 100)

            rankings.append(SectorRanking(
                sector=sector,
                code=str(row.get("板块代码", "")),
                pct_chg_today=today_chg,
                pct_chg_60d=pct_60d if not np.isnan(pct_60d) else 0.0,
                health=health,
                score=score,
            ))

        rankings.sort(key=lambda r: -r.score)
        return rankings[:top_n]

    def constituents(self, sector: str) -> list[tuple[str, str]]:
        """返回 [(code, name), ...] 行业成分股."""
        cache = self.cache_dir / f"sector_cons_em_{sector}.parquet"
        if cache.exists() and self._is_fresh(cache):
            df = pd.read_parquet(cache)
        else:
            try:
                df = ak.stock_board_industry_cons_em(symbol=sector)
                df.to_parquet(cache)
            except Exception:
                return []
        return list(zip(df["代码"].astype(str), df["名称"].astype(str)))

    def candidate_pool(
        self, asof: str, top_n_sectors: int = 5, only_cached_hist: bool = False
    ) -> dict[str, list[tuple[str, str]]]:
        """top N 行业的成分股合集. 返回 {sector_name: [(code, name)]}."""
        top = self.rank(asof, top_n=top_n_sectors, only_cached_hist=only_cached_hist)
        return {r.sector: self.constituents(r.sector) for r in top}

    def _is_fresh(self, path: Path) -> bool:
        if not path.exists():
            return False
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        return datetime.now() - mtime < timedelta(days=self.refresh_days)


# ---------- 内部 helper ----------

def _load_cached(cache_path: Path, refresh_days: int, fetch_fn) -> pd.DataFrame:
    """通用 parquet 缓存."""
    if cache_path.exists():
        mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
        if datetime.now() - mtime < timedelta(days=refresh_days):
            return pd.read_parquet(cache_path)
    df = fetch_fn()
    df.to_parquet(cache_path)
    return df
