"""US fundamentals via yfinance: latest_us_indicator + get_us_financial_indicator 字段映射 / publication_lag 测试。

不联网：用 monkeypatch 把 yfinance.Ticker 替换成内存桩。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from quant_system.strategies.equity_factor.data.loader import DataLoader


# --------------------------- latest_us_indicator ---------------------------

def _us_fin_df(rows: list[dict]) -> pd.DataFrame:
    """构造 get_us_financial_indicator 输出风格 DataFrame，按 report_date 升序。"""
    return pd.DataFrame(rows).sort_values("report_date").reset_index(drop=True)


def test_latest_us_indicator_excludes_within_lag_window():
    """报告期 2024-09-30 距 asof 2024-11-01 仅 32 天，默认 60 天 lag 应排除，取上一期。"""
    df = _us_fin_df([
        {"report_date": "2023-09-30", "roe_avg": 0.12},
        {"report_date": "2024-09-30", "roe_avg": 0.15},
    ])
    v = DataLoader.latest_us_indicator(df, "roe_avg", asof="2024-11-01")
    assert v == 0.12


def test_latest_us_indicator_includes_past_lag_window():
    """报告期 2024-09-30 距 asof 2024-12-01 共 62 天 > 60，应纳入。"""
    df = _us_fin_df([
        {"report_date": "2023-09-30", "roe_avg": 0.12},
        {"report_date": "2024-09-30", "roe_avg": 0.15},
    ])
    v = DataLoader.latest_us_indicator(df, "roe_avg", asof="2024-12-01")
    assert v == 0.15


def test_latest_us_indicator_custom_lag():
    """传 publication_lag_days=30 时窗口放宽，2024-09-30 报表在 2024-11-01 也算可见。"""
    df = _us_fin_df([
        {"report_date": "2023-09-30", "roe_avg": 0.12},
        {"report_date": "2024-09-30", "roe_avg": 0.15},
    ])
    v = DataLoader.latest_us_indicator(df, "roe_avg", asof="2024-11-01", publication_lag_days=30)
    assert v == 0.15


def test_latest_us_indicator_empty_df_returns_none():
    df = pd.DataFrame(columns=["report_date", "roe_avg"])
    assert DataLoader.latest_us_indicator(df, "roe_avg", asof="2024-07-01") is None


def test_latest_us_indicator_missing_column_returns_none():
    df = _us_fin_df([{"report_date": "2023-09-30", "roe_avg": 0.12}])
    assert DataLoader.latest_us_indicator(df, "no_such_col", asof="2024-12-01") is None


def test_latest_us_indicator_skips_nan():
    """窗口内最新一期为 NaN 时回退到上一期。"""
    df = _us_fin_df([
        {"report_date": "2022-09-30", "roe_avg": 0.10},
        {"report_date": "2023-09-30", "roe_avg": None},
        {"report_date": "2024-09-30", "roe_avg": 0.15},
    ])
    v = DataLoader.latest_us_indicator(df, "roe_avg", asof="2024-01-01")
    assert v == 0.10


# --------------------------- get_us_financial_indicator ---------------------------

class _FakeTicker:
    """yfinance.Ticker 桩；三表用 pd.DataFrame，列=Timestamp 降序，行=line item。"""
    def __init__(self, financials, balance_sheet, cashflow):
        self.financials = financials
        self.balance_sheet = balance_sheet
        self.cashflow = cashflow


def _ts(s):
    return pd.Timestamp(s)


@pytest.fixture
def fake_yf(monkeypatch):
    """注入伪 yfinance 模块到 sys.modules，被 get_us_financial_indicator 的 `import yfinance as yf` 看到。"""
    import sys, types

    fake = types.ModuleType("yfinance")
    fake._tickers = {}

    def Ticker(code):
        return fake._tickers[code]

    fake.Ticker = Ticker
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    return fake


def test_get_us_financial_indicator_maps_fields(tmp_path, fake_yf):
    cols = [_ts("2024-09-30"), _ts("2023-09-30")]
    fin = pd.DataFrame({
        cols[0]: {"Diluted EPS": 6.0, "Net Income": 90.0e9, "Total Revenue": 400.0e9},
        cols[1]: {"Diluted EPS": 5.5, "Net Income": 85.0e9, "Total Revenue": 380.0e9},
    })
    bs = pd.DataFrame({
        cols[0]: {"Stockholders Equity": 60.0e9, "Ordinary Shares Number": 15.0e9},
        cols[1]: {"Stockholders Equity": 55.0e9, "Ordinary Shares Number": 16.0e9},
    })
    cf = pd.DataFrame({
        cols[0]: {"Free Cash Flow": 105.0e9},
        cols[1]: {"Free Cash Flow": 99.0e9},
    })
    fake_yf._tickers["AAPL"] = _FakeTicker(fin, bs, cf)

    loader = DataLoader(cache_dir=tmp_path / "cache", refresh_days=0)
    df = loader.get_us_financial_indicator("AAPL")

    # 升序两行
    assert list(df["report_date"]) == ["2023-09-30", "2024-09-30"]
    # 字段映射
    r24 = df.iloc[1]
    assert r24["eps_ttm"] == pytest.approx(6.0)
    assert r24["bps"] == pytest.approx(60.0e9 / 15.0e9)
    assert r24["roe_avg"] == pytest.approx(90.0e9 / 60.0e9)
    assert r24["revenue_yoy"] == pytest.approx((400.0 - 380.0) / 380.0)
    assert r24["fcf_per_share"] == pytest.approx(105.0e9 / 15.0e9)


def test_get_us_financial_indicator_handles_missing_rows(tmp_path, fake_yf):
    """部分行缺失时不应崩，对应字段填 NaN，其他字段正常。"""
    cols = [_ts("2024-12-31")]
    fin = pd.DataFrame({cols[0]: {"Diluted EPS": 2.0, "Total Revenue": 100.0}})  # 缺 Net Income
    bs = pd.DataFrame({cols[0]: {"Stockholders Equity": 50.0, "Ordinary Shares Number": 10.0}})
    cf = pd.DataFrame()  # 全空
    fake_yf._tickers["NOFCF"] = _FakeTicker(fin, bs, cf)

    loader = DataLoader(cache_dir=tmp_path / "cache", refresh_days=0)
    df = loader.get_us_financial_indicator("NOFCF")
    assert len(df) == 1
    row = df.iloc[0]
    assert row["eps_ttm"] == pytest.approx(2.0)
    assert row["bps"] == pytest.approx(5.0)
    # Net Income 缺 → roe NaN
    assert pd.isna(row["roe_avg"])
    # cashflow 空 → fcf NaN
    assert pd.isna(row["fcf_per_share"])
    # 只有 1 年 → revenue_yoy 无前期 → NaN
    assert pd.isna(row["revenue_yoy"])


def test_get_us_financial_indicator_caches_empty_on_failure(tmp_path, monkeypatch):
    """yfinance ImportError 时也应写 cache 避免反复重试。"""
    import sys
    monkeypatch.setitem(sys.modules, "yfinance", None)   # import yfinance as yf → AttributeError on access

    loader = DataLoader(cache_dir=tmp_path / "cache", refresh_days=0)
    df = loader.get_us_financial_indicator("AAPL")
    assert df.empty
    cache_file = loader.cache_dir / "us_fin_AAPL.parquet"
    assert cache_file.exists()


def test_get_us_financial_indicator_uses_cache(tmp_path, fake_yf):
    """二次调用直接读 cache，不再访问 yfinance。"""
    cols = [_ts("2024-09-30")]
    fin = pd.DataFrame({cols[0]: {"Diluted EPS": 6.0, "Net Income": 1.0, "Total Revenue": 100.0}})
    bs = pd.DataFrame({cols[0]: {"Stockholders Equity": 10.0, "Ordinary Shares Number": 5.0}})
    cf = pd.DataFrame({cols[0]: {"Free Cash Flow": 20.0}})
    fake_yf._tickers["X"] = _FakeTicker(fin, bs, cf)

    loader = DataLoader(cache_dir=tmp_path / "cache", refresh_days=1)
    df1 = loader.get_us_financial_indicator("X")
    # 移除 fake ticker；如果再次拉数据会 KeyError，被 except 捕获返回空 cache (覆盖原 cache 但 _is_fresh 优先)
    fake_yf._tickers.clear()
    df2 = loader.get_us_financial_indicator("X")
    pd.testing.assert_frame_equal(df1, df2)
