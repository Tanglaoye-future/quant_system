"""DataLoader.latest_indicator_value / latest_n_indicator_values 的 publication_lag_days 防未来函数语义。"""
from __future__ import annotations

import pandas as pd

from quant_system.strategies.equity_factor.data.loader import DataLoader


def _abstract(rows: list[tuple[str, dict[str, float | None]]]) -> pd.DataFrame:
    """构造 stock_financial_abstract 风格的长表。

    rows = [(指标名, {报告期 'YYYYMMDD': 值, ...}), ...]
    """
    date_cols: list[str] = []
    for _, vals in rows:
        for d in vals:
            if d not in date_cols:
                date_cols.append(d)
    records = []
    for indicator, vals in rows:
        rec = {"选项": "—", "指标": indicator}
        for d in date_cols:
            rec[d] = vals.get(d)
        records.append(rec)
    return pd.DataFrame(records, columns=["选项", "指标", *date_cols])


def test_latest_indicator_value_excludes_report_within_lag_window():
    """报告期 20240331 距 asof 2024-04-30 仅 30 天，默认 90 天 lag 应排除。"""
    df = _abstract([("ROE", {"20240331": 12.0, "20231231": 9.5})])
    v = DataLoader.latest_indicator_value(df, "ROE", asof="2024-04-30")
    assert v == 9.5


def test_latest_indicator_value_includes_report_past_lag_window():
    """报告期 20240331 距 asof 2024-07-01 共 92 天 > 90 天，应纳入。"""
    df = _abstract([("ROE", {"20240331": 12.0, "20231231": 9.5})])
    v = DataLoader.latest_indicator_value(df, "ROE", asof="2024-07-01")
    assert v == 12.0


def test_latest_indicator_value_lag_zero_disables_window():
    """publication_lag_days=0 退化为旧行为：只要报告期 <= asof 就取最新。"""
    df = _abstract([("ROE", {"20240331": 12.0, "20231231": 9.5})])
    v = DataLoader.latest_indicator_value(df, "ROE", asof="2024-04-01", publication_lag_days=0)
    assert v == 12.0


def test_latest_indicator_value_asof_none_takes_latest():
    """asof=None 不截断，返回最新一期。"""
    df = _abstract([("ROE", {"20240331": 12.0, "20231231": 9.5})])
    v = DataLoader.latest_indicator_value(df, "ROE", asof=None)
    assert v == 12.0


def test_latest_indicator_value_skips_nan_within_window():
    """窗口内最新一期为 NaN 时回退到上一期。"""
    df = _abstract([("ROE", {"20231231": None, "20230930": 8.0, "20230630": 7.0})])
    v = DataLoader.latest_indicator_value(df, "ROE", asof="2024-07-01")
    assert v == 8.0


def test_latest_n_indicator_values_respects_lag_window():
    """n=2 + 90 天 lag：asof 2024-07-01 应只见 20240331 及更早。"""
    df = _abstract([
        ("营业总收入", {
            "20240630": 1000.0,  # 距 asof 1 天，应排除
            "20240331": 900.0,   # 距 asof 92 天，纳入
            "20231231": 800.0,
            "20230930": 700.0,
        }),
    ])
    vals = DataLoader.latest_n_indicator_values(df, "营业总收入", asof="2024-07-01", n=2)
    assert vals == [900.0, 800.0]


def test_latest_n_indicator_values_custom_lag():
    """传 publication_lag_days=30 时窗口放宽，20240630 也可纳入。"""
    df = _abstract([
        ("营业总收入", {
            "20240630": 1000.0,
            "20240331": 900.0,
        }),
    ])
    vals = DataLoader.latest_n_indicator_values(
        df, "营业总收入", asof="2024-08-01", n=2, publication_lag_days=30,
    )
    assert vals == [1000.0, 900.0]


def test_indicator_missing_returns_empty():
    df = _abstract([("ROE", {"20240331": 12.0})])
    assert DataLoader.latest_indicator_value(df, "净利润", asof="2024-07-01") is None
    assert DataLoader.latest_n_indicator_values(df, "净利润", asof="2024-07-01", n=2) == []
