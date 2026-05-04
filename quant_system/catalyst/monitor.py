"""
催化剂监控.

数据源 (akshare):
  1. 业绩预告  stock_yjyg_em(date='YYYYMMDD')   按报告期一次拉全市场, 按 code 切片
  2. 龙虎榜    stock_lhb_detail_em(start, end)
  3. 涨停板池  stock_zt_pool_em(date='YYYYMMDD')

用途:
  - 给候选股打"事件标签": 业绩预增 / 龙虎榜净买入 / N 连板涨停
  - 给持仓股打"风险标签": 业绩预减 / 续亏 / 龙虎榜净卖出
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import akshare as ak
import pandas as pd


_QUARTER_ENDS = [(3, 31), (6, 30), (9, 30), (12, 31)]


def latest_period(asof: str) -> str:
    """asof 'YYYY-MM-DD' or 'YYYYMMDD', 返回最近一个过去的季度末 'YYYYMMDD'."""
    s = asof.replace("-", "")
    d = datetime.strptime(s, "%Y%m%d")
    cands: list[datetime] = []
    for y in (d.year - 1, d.year):
        for m, day in _QUARTER_ENDS:
            qd = datetime(y, m, day)
            if qd <= d:
                cands.append(qd)
    return max(cands).strftime("%Y%m%d")


@dataclass
class CatalystSummary:
    code: str
    forecast_type: Optional[str] = None       # 预增 / 预减 / 续亏 / 减亏 / 略减 / 扭亏 ...
    forecast_change_pct: Optional[float] = None
    forecast_announce_date: Optional[str] = None
    forecast_reason: Optional[str] = None
    on_lhb_recent: bool = False
    lhb_net_buy_total: float = 0.0
    lhb_dates: tuple[str, ...] = ()
    on_zt_today: bool = False
    zt_consecutive: Optional[int] = None
    zt_sector: Optional[str] = None

    def is_positive(self) -> bool:
        if self.forecast_type and any(k in self.forecast_type for k in ("预增", "扭亏", "续盈", "略增")):
            return True
        if self.lhb_net_buy_total > 0:
            return True
        if self.on_zt_today:
            return True
        return False

    def is_negative(self) -> bool:
        if self.forecast_type and any(k in self.forecast_type for k in ("预减", "续亏", "首亏", "略减")):
            return True
        if self.lhb_net_buy_total < 0:
            return True
        return False

    def to_label(self) -> str:
        bits = []
        if self.forecast_type:
            pct = f" {self.forecast_change_pct:+.0f}%" if self.forecast_change_pct is not None else ""
            bits.append(f"业绩{self.forecast_type}{pct}")
        if self.on_lhb_recent:
            bits.append(
                f"龙虎榜净{'买' if self.lhb_net_buy_total >= 0 else '卖'}"
                f"{abs(self.lhb_net_buy_total)/1e8:.2f}亿"
            )
        if self.on_zt_today:
            bits.append(f"{self.zt_consecutive or '?'}连板")
        return " | ".join(bits) if bits else "-"


class CatalystMonitor:
    def __init__(self, cache_dir: Path, refresh_days: int = 1):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.refresh_days = refresh_days

    def _all_forecasts(self, period: str) -> pd.DataFrame:
        cache = self.cache_dir / f"yjyg_{period}.parquet"
        if self._is_fresh(cache):
            return pd.read_parquet(cache)
        try:
            df = ak.stock_yjyg_em(date=period)
        except Exception:
            df = pd.DataFrame()
        df.to_parquet(cache)
        return df

    def _all_lhb(self, start: str, end: str) -> pd.DataFrame:
        cache = self.cache_dir / f"lhb_{start}_{end}.parquet"
        if self._is_fresh(cache):
            return pd.read_parquet(cache)
        try:
            df = ak.stock_lhb_detail_em(start_date=start, end_date=end)
        except Exception:
            df = pd.DataFrame()
        df.to_parquet(cache)
        return df

    def _all_zt(self, date: str) -> pd.DataFrame:
        cache = self.cache_dir / f"zt_{date}.parquet"
        if self._is_fresh(cache):
            return pd.read_parquet(cache)
        try:
            df = ak.stock_zt_pool_em(date=date)
        except Exception:
            df = pd.DataFrame()
        df.to_parquet(cache)
        return df

    def summarize(
        self,
        code: str,
        asof: Optional[str] = None,
        period: Optional[str] = None,
        lhb_lookback_days: int = 7,
    ) -> CatalystSummary:
        asof_full = asof or datetime.now().strftime("%Y-%m-%d")
        asof_yyyymmdd = asof_full.replace("-", "")
        period = period or latest_period(asof_full)
        out = CatalystSummary(code=code)

        try:
            yj = self._all_forecasts(period)
            rows = yj[yj["股票代码"].astype(str) == code]
            if not rows.empty:
                # 防止“公告日期在 asof 之后”的未来信息泄漏：回测时只能用已公告的那条
                if "公告日期" in rows.columns:
                    rows = rows[pd.to_datetime(rows["公告日期"], errors="coerce") <= pd.to_datetime(asof_yyyymmdd)]
                if rows.empty:
                    return out
                rows = rows.sort_values("公告日期", ascending=False)
                r = rows.iloc[0]
                out.forecast_type = str(r.get("预告类型") or "")
                cp = r.get("业绩变动幅度")
                out.forecast_change_pct = float(cp) if pd.notna(cp) else None
                out.forecast_announce_date = str(r.get("公告日期") or "")
                out.forecast_reason = str(r.get("业绩变动原因") or "")
        except Exception:
            pass

        try:
            start = (
                datetime.strptime(asof_yyyymmdd, "%Y%m%d")
                - timedelta(days=lhb_lookback_days)
            ).strftime("%Y%m%d")
            lhb = self._all_lhb(start, asof_yyyymmdd)
            rows = lhb[lhb["代码"].astype(str) == code]
            if not rows.empty:
                out.on_lhb_recent = True
                out.lhb_net_buy_total = float(
                    pd.to_numeric(rows["龙虎榜净买额"], errors="coerce").sum()
                )
                out.lhb_dates = tuple(sorted(set(str(d) for d in rows["上榜日"])))
        except Exception:
            pass

        try:
            zt = self._all_zt(asof_yyyymmdd)
            if not zt.empty:
                rows = zt[zt["代码"].astype(str) == code]
                if not rows.empty:
                    r = rows.iloc[0]
                    out.on_zt_today = True
                    cons = r.get("连板数")
                    out.zt_consecutive = int(cons) if pd.notna(cons) else None
                    out.zt_sector = str(r.get("所属行业") or "")
        except Exception:
            pass

        return out

    def _is_fresh(self, path: Path) -> bool:
        if not path.exists():
            return False
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        return datetime.now() - mtime < timedelta(days=self.refresh_days)
