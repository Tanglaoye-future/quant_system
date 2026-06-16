"""CBDataLoader 契约红灯测试（PR2）。

PR3 实现这些 mock 路径后红灯转绿。本 PR2 仅落契约，
所有用例预期 raise NotImplementedError 或 fail 在 contract 层。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from quant_system.strategies.cb_double_low.data.loader import CBDataLoader


@pytest.fixture
def loader(tmp_path: Path) -> CBDataLoader:
    return CBDataLoader(cache_dir=tmp_path, refresh_days=1)


# ---------- load_universe ----------

def test_load_universe_includes_delisted_bonds(loader: CBDataLoader) -> None:
    """支柱关键: 1022 行含 2007 起退市债, 无 survivorship bias.

    Mock bond_zh_cov 返回含 2018 上市的债 (今天 2026-06 已退市的 vintage).
    Expect 该债在结果中, exit_status 字段反映真实状态.
    """
    fake_cov = pd.DataFrame(
        {
            "债券代码": ["113008", "123273"],
            "债券简称": ["电气转债", "三江转债"],
            "正股代码": ["601727", "603312"],
            "正股简称": ["上海电气", "三江购物"],
            "上市时间": pd.to_datetime(["2015-02-16", "2026-06-22"]),
            "发行规模": [60.0, 2.9],
            "信用评级": ["AAA", "A+"],
        }
    )
    fake_redeem = pd.DataFrame(columns=["代码", "强赎状态", "最后交易日"])
    with patch("akshare.bond_zh_cov", return_value=fake_cov), \
         patch("akshare.bond_cb_redeem_jsl", return_value=fake_redeem):
        df = loader.load_universe(asof=date(2026, 6, 15))
    assert set(CBDataLoader.UNIVERSE_COLUMNS).issubset(df.columns)
    assert "113008" in df["bond_code"].astype(str).values, \
        "2015 上市的老券必须在 universe 内（survivorship bias 防御）"


def test_load_universe_exit_status_empty_string_maps_to_active(loader: CBDataLoader) -> None:
    """Regression — 2026-06-15 mini-backfill 发现 redeem 表里 "强赎状态" 列
    部分行是空字符串 (in-table 但状态为空), 247/1012 占 24% 错分类成 exit_status="",
    应归 "active" 与 NaN 同语义.
    """
    fake_cov = pd.DataFrame(
        {
            "债券代码": ["113001", "113002", "113003"],
            "债券简称": ["A 转债", "B 转债", "C 转债"],
            "正股代码": ["600001", "600002", "600003"],
            "正股简称": ["A 股", "B 股", "C 股"],
            "上市时间": pd.to_datetime(["2020-01-01", "2020-01-01", "2020-01-01"]),
            "发行规模": [10.0, 10.0, 10.0],
            "信用评级": ["AA", "AA", "AA"],
        }
    )
    # 113001 在 redeem 表里状态空; 113002 NaN (不在表, merge 后是 NaN); 113003 已公告强赎
    fake_redeem = pd.DataFrame(
        {
            "代码": ["113001", "113003"],
            "强赎状态": ["", "已公告强赎"],
            "最后交易日": pd.to_datetime(["2026-05-30", "2026-05-30"]),
        }
    )
    with patch("akshare.bond_zh_cov", return_value=fake_cov), \
         patch("akshare.bond_cb_redeem_jsl", return_value=fake_redeem):
        df = loader.load_universe(asof=date(2026, 6, 15))
    statuses = dict(zip(df["bond_code"].astype(str), df["exit_status"]))
    assert statuses["113001"] == "active", "redeem 表内空字符串状态必须归 active"
    assert statuses["113002"] == "active", "不在 redeem 表的 NaN 必须归 active"
    assert statuses["113003"] == "已公告强赎", "真实强赎状态保留"


def test_load_universe_asof_filters_future_listings(loader: CBDataLoader) -> None:
    """asof 2026-06-15 下, 2026-06-22 才上市的债应排除（防未来函数）."""
    fake_cov = pd.DataFrame(
        {
            "债券代码": ["113008", "123273"],
            "债券简称": ["电气转债", "三江转债"],
            "正股代码": ["601727", "603312"],
            "正股简称": ["上海电气", "三江购物"],
            "上市时间": pd.to_datetime(["2015-02-16", "2026-06-22"]),
            "发行规模": [60.0, 2.9],
            "信用评级": ["AAA", "A+"],
        }
    )
    fake_redeem = pd.DataFrame(columns=["代码", "强赎状态", "最后交易日"])
    with patch("akshare.bond_zh_cov", return_value=fake_cov), \
         patch("akshare.bond_cb_redeem_jsl", return_value=fake_redeem):
        df = loader.load_universe(asof=date(2026, 6, 15))
    codes = set(df["bond_code"].astype(str).values)
    assert "123273" not in codes, "asof 之后才上市的债必须排除"


# ---------- load_panel ----------

def test_load_panel_returns_long_format_with_4_premium_fields(loader: CBDataLoader) -> None:
    """value_analysis 6 列必须全部映射到 panel 输出（4 个溢价率字段是双低评分核心）."""
    fake_va = pd.DataFrame(
        {
            "日期": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "收盘价": [105.0, 106.5],
            "纯债价值": [85.0, 85.1],
            "转股价值": [98.0, 99.5],
            "纯债溢价率": [23.5, 25.1],
            "转股溢价率": [7.1, 7.0],
        }
    )
    with patch("akshare.bond_zh_cov_value_analysis", return_value=fake_va):
        df = loader.load_panel(
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
            codes=["113537"],
        )
    assert set(CBDataLoader.PANEL_COLUMNS).issubset(df.columns)
    assert len(df) == 2
    assert "pure_bond_premium_rate" in df.columns
    assert "conversion_premium_rate" in df.columns


def test_load_panel_caches_to_duckdb(loader: CBDataLoader) -> None:
    """第二次调用同 (date, code) 切片不应再触发 akshare（DuckDB cache PASS）."""
    fake_va = pd.DataFrame(
        {
            "日期": pd.to_datetime(["2024-01-02"]),
            "收盘价": [105.0],
            "纯债价值": [85.0],
            "转股价值": [98.0],
            "纯债溢价率": [23.5],
            "转股溢价率": [7.1],
        }
    )
    with patch("akshare.bond_zh_cov_value_analysis", return_value=fake_va) as mock_ak:
        loader.load_panel(date(2024, 1, 1), date(2024, 1, 31), codes=["113537"])
        loader.load_panel(date(2024, 1, 1), date(2024, 1, 31), codes=["113537"])
    assert mock_ak.call_count == 1, "第二次相同切片必须走 DuckDB cache"


# ---------- load_redemption_events ----------

def test_load_redemption_events_filters_by_asof(loader: CBDataLoader) -> None:
    """asof 之后才公告的强赎事件必须排除（防未来函数）."""
    fake_redeem = pd.DataFrame(
        {
            "代码": ["123198", "128137"],
            "名称": ["金埔转债", "洁美转债"],
            "强赎天计数": ["15/30", "15/30"],
            "最后交易日": pd.to_datetime(["2026-05-30", "2026-07-10"]),
            "到期日": pd.to_datetime(["2026-12-01", "2027-01-15"]),
            "强赎价": [100.5, 100.3],
            "强赎状态": ["已公告强赎", "已公告强赎"],
        }
    )
    with patch("akshare.bond_cb_redeem_jsl", return_value=fake_redeem):
        df = loader.load_redemption_events(asof=date(2026, 6, 15))
    assert set(CBDataLoader.REDEMPTION_COLUMNS).issubset(df.columns)
    codes = set(df["bond_code"].astype(str).values)
    assert "123198" in codes, "asof 前公告必须保留"


# ---------- get_spot_today ----------

def test_get_spot_today_returns_min_columns(loader: CBDataLoader) -> None:
    """实盘 daily ranking 必须能从 spot 拿到 close + change_pct."""
    fake_spot = pd.DataFrame(
        {
            "symbol": ["sh113537"],
            "code": ["113537"],
            "name": ["紫银转债"],
            "trade": [105.5],
            "changepercent": [0.95],
            "volume": [100000],
            "amount": [10550000],
        }
    )
    with patch("akshare.bond_zh_hs_cov_spot", return_value=fake_spot):
        df = loader.get_spot_today()
    assert set(CBDataLoader.SPOT_COLUMNS).issubset(df.columns)
    assert len(df) == 1
