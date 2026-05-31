"""L9-B 新增因子单测: ROIC + 应收账款周转率同比 (ar_turnover_yoy)."""
from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from quant_system.strategies.equity_factor.bottomup.factors import (
    FactorWeights,
    compute_raw_factors,
)


def _abstract(rows: list[tuple[str, dict[str, float | None]]]) -> pd.DataFrame:
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


def _mock_loader(abstract_df: pd.DataFrame, valuation_df: pd.DataFrame | None = None):
    """构造最小 mock loader: 只 stub compute_raw_factors 走 a_share 路径用到的方法."""
    from quant_system.strategies.equity_factor.data.loader import DataLoader

    loader = MagicMock()
    loader.get_a_share_abstract.return_value = abstract_df
    val = valuation_df if valuation_df is not None else pd.DataFrame(
        columns=["date", "pe_ttm", "pb"]
    )
    loader.get_a_share_valuation.return_value = val
    loader.get_daily.return_value = pd.DataFrame(columns=["date", "close"])
    # 静态方法走真实实现 (asof 截断 + NaN 兜底)
    loader.latest_indicator_value = DataLoader.latest_indicator_value
    loader.latest_n_indicator_values = DataLoader.latest_n_indicator_values
    return loader


def test_factor_weights_includes_new_fields():
    fw = FactorWeights()
    s = fw.as_series()
    assert "roic" in s.index
    assert "ar_turnover_yoy" in s.index
    assert s["roic"] == 0.0
    assert s["ar_turnover_yoy"] == 0.0


def test_factor_weights_custom_values():
    fw = FactorWeights(roic=0.10, ar_turnover_yoy=0.05)
    s = fw.as_series()
    assert s["roic"] == 0.10
    assert s["ar_turnover_yoy"] == 0.05


def test_roic_extracted_from_abstract():
    """投入资本回报率最新值正确取出 (90 天披露窗口)."""
    df = _abstract([
        ("投入资本回报率", {"20230630": 10.5, "20221231": 8.0}),
    ])
    loader = _mock_loader(df)
    f = compute_raw_factors(loader, "a_share", "601939", asof="2023-10-01")
    # 20230630 + 90 天 = 2023-09-28 < asof → 纳入
    assert f["roic"] == pytest.approx(10.5)


def test_roic_excluded_within_publication_lag():
    """报告期 20230630 距 asof 2023-08-01 仅 32 天 < 90 → 回退到 20221231."""
    df = _abstract([
        ("投入资本回报率", {"20230630": 10.5, "20221231": 8.0}),
    ])
    loader = _mock_loader(df)
    f = compute_raw_factors(loader, "a_share", "601939", asof="2023-08-01")
    assert f["roic"] == pytest.approx(8.0)


def test_ar_turnover_yoy_positive_when_turnover_improves():
    """应收账款周转率 8 → 10 (本期 > 上期) → YoY = +0.25."""
    df = _abstract([
        ("应收账款周转率", {"20230630": 10.0, "20220630": 8.0}),
    ])
    loader = _mock_loader(df)
    f = compute_raw_factors(loader, "a_share", "601939", asof="2023-10-01")
    assert f["ar_turnover_yoy"] == pytest.approx(0.25)


def test_ar_turnover_yoy_negative_when_turnover_degrades():
    """周转率 10 → 6 (本期 < 上期, 应收扩张快于营收) → YoY = -0.4."""
    df = _abstract([
        ("应收账款周转率", {"20230630": 6.0, "20220630": 10.0}),
    ])
    loader = _mock_loader(df)
    f = compute_raw_factors(loader, "a_share", "601939", asof="2023-10-01")
    assert f["ar_turnover_yoy"] == pytest.approx(-0.4)


def test_ar_turnover_yoy_nan_when_only_one_period():
    """只有一期数据 → 不能算 YoY → 保持 NaN."""
    df = _abstract([
        ("应收账款周转率", {"20230630": 10.0}),
    ])
    loader = _mock_loader(df)
    f = compute_raw_factors(loader, "a_share", "601939", asof="2023-10-01")
    assert np.isnan(f["ar_turnover_yoy"])


def test_ar_turnover_yoy_skips_nan_period():
    """中间一期为 NaN → 跳到下一期对比."""
    df = _abstract([
        ("应收账款周转率", {"20230630": 12.0, "20220630": None, "20210630": 8.0}),
    ])
    loader = _mock_loader(df)
    f = compute_raw_factors(loader, "a_share", "601939", asof="2023-10-01")
    # latest_n_indicator_values 跳 NaN, 取 [12.0, 8.0] → (12-8)/8 = 0.5
    assert f["ar_turnover_yoy"] == pytest.approx(0.5)


def test_roic_and_ar_turnover_default_nan_when_indicator_missing():
    """abstract 没有这两个指标 → 都是 NaN, 不影响其他因子."""
    df = _abstract([("ROE", {"20230630": 12.0})])
    loader = _mock_loader(df)
    f = compute_raw_factors(loader, "a_share", "601939", asof="2023-10-01")
    assert np.isnan(f["roic"])
    assert np.isnan(f["ar_turnover_yoy"])
