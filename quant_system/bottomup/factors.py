"""
自下而上: 多因子打分.
当前覆盖 5 个基础因子 (估值 2 + 质量 1 + 成长 1 + 动量 1).
后续可加: 现金流质量, ROIC, 应收账款增速等.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import numpy as np
import pandas as pd

from quant_system.data.loader import DataLoader, Market

if TYPE_CHECKING:
    from quant_system.bottomup.portfolio import M4Config


@dataclass
class FactorWeights:
    pe_inverse: float = 0.20
    pb_inverse: float = 0.15
    roe: float = 0.25
    revenue_growth: float = 0.20
    momentum_3m: float = 0.20
    momentum_6m: float = 0.0    # 默认关闭；US/动量市场可设 >0 启用6个月动量

    def as_series(self) -> pd.Series:
        return pd.Series({
            "pe_inverse": self.pe_inverse,
            "pb_inverse": self.pb_inverse,
            "roe": self.roe,
            "revenue_growth": self.revenue_growth,
            "momentum_3m": self.momentum_3m,
            "momentum_6m": self.momentum_6m,
        })


def _safe_latest(df: pd.DataFrame, col: str) -> float:
    if df is None or df.empty or col not in df.columns:
        return np.nan
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    return float(s.iloc[-1]) if len(s) else np.nan


def compute_raw_factors(
    loader: DataLoader, market: Market, code: str, asof: str
) -> dict[str, float]:
    """对单只股票, 拉取最新一期的 5 个因子原始值."""
    factors: dict[str, float] = {
        "pe_inverse": np.nan, "pb_inverse": np.nan,
        "roe": np.nan, "revenue_growth": np.nan,
        "momentum_3m": np.nan, "momentum_6m": np.nan,
    }

    if market == "a_share":
        try:
            val = loader.get_a_share_valuation(code)
            val = val[val["date"] <= asof]
            pe = _safe_latest(val, "pe_ttm")
            pb = _safe_latest(val, "pb")
            factors["pe_inverse"] = 1.0 / pe if pe and pe > 0 else np.nan
            factors["pb_inverse"] = 1.0 / pb if pb and pb > 0 else np.nan
        except Exception:
            pass

        try:
            abstract = loader.get_a_share_abstract(code)
            roe = loader.latest_indicator_value(abstract, "净资产收益率(ROE)", asof=asof)
            rev_g = loader.latest_indicator_value(abstract, "营业总收入增长率", asof=asof)
            factors["roe"] = float(roe) if roe is not None else np.nan
            factors["revenue_growth"] = float(rev_g) if rev_g is not None else np.nan
        except Exception:
            pass

    # 港股财务在 akshare 覆盖窄, 暂时只算动量, 估值/质量后续接补丁

    try:
        end_dt = pd.to_datetime(asof)
        start_dt = end_dt - pd.Timedelta(days=250)   # 250 天覆盖 3m + 6m 动量
        px = loader.get_daily(market, code, start_dt.strftime("%Y-%m-%d"), asof)
        if len(px) >= 60:
            factors["momentum_3m"] = float(px["close"].iloc[-1] / px["close"].iloc[-60] - 1.0)
        if len(px) >= 120:
            factors["momentum_6m"] = float(px["close"].iloc[-1] / px["close"].iloc[-120] - 1.0)
    except Exception:
        pass

    return factors


def zscore(series: pd.Series) -> pd.Series:
    s = series.astype(float)
    mu = s.mean(skipna=True)
    sd = s.std(skipna=True)
    if not sd or np.isnan(sd):
        return pd.Series(np.nan, index=s.index)
    return (s - mu) / sd


def score_universe(
    loader: DataLoader,
    market: Market,
    codes: list[str],
    asof: str,
    weights: FactorWeights,
    verbose: bool = False,
    m4_cfg: Optional["M4Config"] = None,
) -> pd.DataFrame:
    """对 universe 内每只股票打分, 返回按总分降序的 DataFrame.m4_cfg 可选（M4 因子离散度惩罚）。"""
    rows = []
    for i, code in enumerate(codes, 1):
        if verbose:
            print(f"  [{i}/{len(codes)}] {code}", flush=True)
        f = compute_raw_factors(loader, market, code, asof)
        f["code"] = code
        rows.append(f)
    raw = pd.DataFrame(rows).set_index("code")

    z = raw.apply(zscore)
    w = weights.as_series()
    # 缺失因子用 0 (中性), 避免一只股票因为单个因子缺失就被淘汰
    z_filled = z.fillna(0.0)
    raw["score"] = z_filled.mul(w, axis=1).sum(axis=1)
    if m4_cfg is not None and float(m4_cfg.m4_factor_dispersion_lambda) > 0:
        lam = float(m4_cfg.m4_factor_dispersion_lambda)
        row_std = z_filled.std(axis=1, ddof=0).clip(upper=5.0)
        raw["score"] = raw["score"] - lam * row_std
    return raw.sort_values("score", ascending=False)
