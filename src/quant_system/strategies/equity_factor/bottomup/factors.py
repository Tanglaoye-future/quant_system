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

from quant_system.strategies.equity_factor.data.loader import DataLoader, Market

if TYPE_CHECKING:
    from quant_system.strategies.equity_factor.bottomup.portfolio import M4Config


@dataclass
class FactorWeights:
    pe_inverse: float = 0.20
    pb_inverse: float = 0.15
    roe: float = 0.25
    revenue_growth: float = 0.20
    momentum_3m: float = 0.20
    momentum_6m: float = 0.0    # 默认关闭；US/动量市场可设 >0 启用6个月动量
    fcf_yield: float = 0.0      # A股 Level2：每股经营现金流/收盘价（现金流质量）
    rev_accel: float = 0.0      # A股 Level2：营收增速加速度（本期增速 − 上期增速）
    roic: float = 0.0           # A股 L9-B：投入资本回报率（资本效率，类 ROE 但剥离金融杠杆）
    ar_turnover_yoy: float = 0.0  # A股 L9-B：应收账款周转率同比变化（正值=收款效率提升；负值=应收扩张快于营收=造假风险）

    def as_series(self) -> pd.Series:
        return pd.Series({
            "pe_inverse": self.pe_inverse,
            "pb_inverse": self.pb_inverse,
            "roe": self.roe,
            "revenue_growth": self.revenue_growth,
            "momentum_3m": self.momentum_3m,
            "momentum_6m": self.momentum_6m,
            "fcf_yield": self.fcf_yield,
            "rev_accel": self.rev_accel,
            "roic": self.roic,
            "ar_turnover_yoy": self.ar_turnover_yoy,
        })


def _safe_latest(df: pd.DataFrame, col: str) -> float:
    if df is None or df.empty or col not in df.columns:
        return np.nan
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    return float(s.iloc[-1]) if len(s) else np.nan


def compute_raw_factors(
    loader: DataLoader, market: Market, code: str, asof: str
) -> dict[str, float]:
    """对单只股票, 拉取最新一期的因子原始值.
    Level2 新增: fcf_yield（每股企业自由现金流量/收盘价）、rev_accel（营收增速加速度）。
    """
    factors: dict[str, float] = {
        "pe_inverse": np.nan, "pb_inverse": np.nan,
        "roe": np.nan, "revenue_growth": np.nan,
        "momentum_3m": np.nan, "momentum_6m": np.nan,
        "fcf_yield": np.nan, "rev_accel": np.nan,
        "roic": np.nan, "ar_turnover_yoy": np.nan,
    }
    _fcf_per_share: float | None = None   # 暂存，待有 close 价后计算 fcf_yield

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

            # rev_accel: 营收增速加速度 = 本期增速 − 上期增速（两期均来自已缓存的 abstract）
            rev_vals = loader.latest_n_indicator_values(
                abstract, "营业总收入增长率", asof=asof, n=2
            )
            if len(rev_vals) >= 2:
                factors["rev_accel"] = rev_vals[0] - rev_vals[1]

            # 预取 fcf_yield 分子（每股经营现金流）；asof 截断规则同其他财务指标
            # 注：企业自由现金流在银行/金融股中为 NaN（资本结构特殊），用经营现金流覆盖率更高
            fcf_vals = loader.latest_n_indicator_values(
                abstract, "每股经营现金流", asof=asof, n=1
            )
            if fcf_vals:
                _fcf_per_share = fcf_vals[0]

            # L9-B: ROIC（投入资本回报率）— 同 asof + 90 天披露窗口
            roic_v = loader.latest_indicator_value(
                abstract, "投入资本回报率", asof=asof
            )
            if roic_v is not None:
                factors["roic"] = float(roic_v)

            # L9-B: 应收账款周转率同比 — 取最近两期对比，正值 = 收款加速 (好)
            ar_vals = loader.latest_n_indicator_values(
                abstract, "应收账款周转率", asof=asof, n=2
            )
            if len(ar_vals) >= 2 and ar_vals[1] is not None and ar_vals[1] != 0:
                factors["ar_turnover_yoy"] = (ar_vals[0] - ar_vals[1]) / abs(ar_vals[1])
        except Exception:
            pass

    elif market == "hk_share":
        # HK 财务（东财年度指标），带 90 天公告滞后避免未来信息
        try:
            fin = loader.get_hk_financial_indicator(code)
            eps_ttm = loader.latest_hk_indicator(fin, "eps_ttm", asof)
            bps = loader.latest_hk_indicator(fin, "bps", asof)
            roe = loader.latest_hk_indicator(fin, "roe_avg", asof)
            rev_yoy = loader.latest_hk_indicator(fin, "revenue_yoy", asof)
            # PE/PB 用最新收盘价 + EPS_TTM / BPS 反推
            end_dt = pd.to_datetime(asof)
            start_dt = max(end_dt - pd.Timedelta(days=30), pd.Timestamp("2018-01-01"))
            px_recent = loader.get_daily(market, code, start_dt.strftime("%Y-%m-%d"), asof)
            latest_close = float(px_recent["close"].iloc[-1]) if not px_recent.empty else None
            if eps_ttm is not None and latest_close and latest_close > 0:
                factors["pe_inverse"] = eps_ttm / latest_close   # 直接 EPS/P 而非 1/PE，处理负 EPS 时也能给出有意义信号
            if bps is not None and latest_close and latest_close > 0 and bps > 0:
                factors["pb_inverse"] = bps / latest_close
            if roe is not None:
                factors["roe"] = float(roe)
            if rev_yoy is not None:
                factors["revenue_growth"] = float(rev_yoy)
        except Exception:
            pass

    elif market == "us_share":
        # US 财务（yfinance 年度报表），带 60 天 10-K 披露滞后避免未来信息
        # yfinance 通常给 4-5 年数据；2018-2020 段大概率缺失 → 因子 NaN → z-score 填 0 (中性)
        try:
            fin = loader.get_us_financial_indicator(code)
            eps_ttm = loader.latest_us_indicator(fin, "eps_ttm", asof)
            bps = loader.latest_us_indicator(fin, "bps", asof)
            roe = loader.latest_us_indicator(fin, "roe_avg", asof)
            rev_yoy = loader.latest_us_indicator(fin, "revenue_yoy", asof)
            fcf_ps = loader.latest_us_indicator(fin, "fcf_per_share", asof)
            end_dt = pd.to_datetime(asof)
            start_dt = max(end_dt - pd.Timedelta(days=30), pd.Timestamp("2018-01-01"))
            px_recent = loader.get_daily(market, code, start_dt.strftime("%Y-%m-%d"), asof)
            latest_close = float(px_recent["close"].iloc[-1]) if not px_recent.empty else None
            if eps_ttm is not None and latest_close and latest_close > 0:
                factors["pe_inverse"] = eps_ttm / latest_close
            if bps is not None and latest_close and latest_close > 0 and bps > 0:
                factors["pb_inverse"] = bps / latest_close
            if roe is not None:
                factors["roe"] = float(roe)
            if rev_yoy is not None:
                factors["revenue_growth"] = float(rev_yoy)
            if fcf_ps is not None:
                _fcf_per_share = fcf_ps
        except Exception:
            pass

    try:
        end_dt = pd.to_datetime(asof)
        # Floor at FETCH_FLOOR to avoid cache misses when backtest starts near 2018-01-01
        start_dt = max(end_dt - pd.Timedelta(days=250), pd.Timestamp("2018-01-01"))
        px = loader.get_daily(market, code, start_dt.strftime("%Y-%m-%d"), asof)
        if len(px) >= 60:
            factors["momentum_3m"] = float(px["close"].iloc[-1] / px["close"].iloc[-60] - 1.0)
        if len(px) >= 120:
            factors["momentum_6m"] = float(px["close"].iloc[-1] / px["close"].iloc[-120] - 1.0)
        # fcf_yield = 每股自由现金流 / 收盘价（A 股 & US 共享此路径；HK 暂无 fcf 数据源）
        if market in ("a_share", "us_share") and _fcf_per_share is not None and len(px) > 0:
            close_at_asof = float(px["close"].iloc[-1])
            if close_at_asof > 0:
                factors["fcf_yield"] = _fcf_per_share / close_at_asof
    except Exception:
        pass

    return factors


def compute_raw_factors_pv(
    loader: DataLoader, market: Market, code: str, asof: str
) -> dict[str, float]:
    """纯量价因子 — 不拉取任何基本面数据，仅从日线 OHLCV 计算 4 个趋势信号。"""
    factors: dict[str, float] = {
        "momentum_3m": np.nan,
        "momentum_6m": np.nan,
        "vol_adj_momentum": np.nan,
        "trend_strength": np.nan,
    }
    try:
        end_dt = pd.to_datetime(asof)
        start_dt = max(end_dt - pd.Timedelta(days=250), pd.Timestamp("2018-01-01"))
        px = loader.get_daily(market, code, start_dt.strftime("%Y-%m-%d"), asof)
        if len(px) < 60:
            return factors
        close = px["close"].values.astype(float)
        factors["momentum_3m"] = float(close[-1] / close[-60] - 1.0)
        if len(px) >= 120:
            factors["momentum_6m"] = float(close[-1] / close[-120] - 1.0)
        # vol_adj_momentum: 3m动量 / 60日年化波动率
        rets = pd.Series(close).pct_change().dropna()
        if len(rets) >= 60:
            vol60 = float(rets.iloc[-60:].std() * np.sqrt(252))
            if vol60 > 0:
                factors["vol_adj_momentum"] = factors["momentum_3m"] / vol60
        # trend_strength: 收盘价 / MA60 - 1
        ma60 = float(np.mean(close[-60:]))
        if ma60 > 0:
            factors["trend_strength"] = float(close[-1] / ma60 - 1.0)
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


PV_FACTOR_WEIGHTS = {
    "momentum_3m": 0.30,
    "momentum_6m": 0.25,
    "vol_adj_momentum": 0.25,
    "trend_strength": 0.20,
}


def score_universe(
    loader: DataLoader,
    market: Market,
    codes: list[str],
    asof: str,
    weights: FactorWeights,
    verbose: bool = False,
    m4_cfg: Optional["M4Config"] = None,
    pure_pv: bool = False,
) -> pd.DataFrame:
    """对 universe 内每只股票打分, 返回按总分降序的 DataFrame。
    pure_pv=True 时跳过所有基本面数据拉取，仅用 4 个纯量价信号等权打分。
    """
    rows = []
    for i, code in enumerate(codes, 1):
        if verbose:
            print(f"  [{i}/{len(codes)}] {code}", flush=True)
        if pure_pv:
            f = compute_raw_factors_pv(loader, market, code, asof)
        else:
            f = compute_raw_factors(loader, market, code, asof)
        f["code"] = code
        rows.append(f)
    raw = pd.DataFrame(rows).set_index("code")

    z = raw.apply(zscore)
    if pure_pv:
        w = pd.Series(PV_FACTOR_WEIGHTS)
    else:
        w = weights.as_series()
    # 缺失因子用 0 (中性), 避免一只股票因为单个因子缺失就被淘汰
    z_filled = z.fillna(0.0)
    # 只取 weight 中存在的列
    common_cols = [c for c in w.index if c in z_filled.columns]
    raw["score"] = z_filled[common_cols].mul(w[common_cols], axis=1).sum(axis=1)
    if m4_cfg is not None and float(m4_cfg.m4_factor_dispersion_lambda) > 0:
        lam = float(m4_cfg.m4_factor_dispersion_lambda)
        row_std = z_filled[common_cols].std(axis=1, ddof=0).clip(upper=5.0)
        raw["score"] = raw["score"] - lam * row_std
    return raw.sort_values("score", ascending=False)
