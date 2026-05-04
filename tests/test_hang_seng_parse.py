"""恒生 HSCHK100 成份解析与 CSV 读取（无网络）。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_system.data.hang_seng_indexes import (
    HangSengDataError,
    load_hschk100_constituents,
    parse_constituent_lines_from_factsheet_text,
)


def test_parse_constituent_lines_strips_trailing_weight() -> None:
    text = """
00939 ABCDEFGHIJKL CHINA CONSTRUCT BANK 1.234
01234 ABCDEFGHIJK1 EXAMPLE HOLDINGS 2.5
"""
    df = parse_constituent_lines_from_factsheet_text(text)
    assert list(df["code"]) == ["00939", "01234"]
    assert df.iloc[0]["name"] == "CHINA CONSTRUCT BANK"
    assert df.iloc[1]["name"] == "EXAMPLE HOLDINGS"


def test_parse_deduplicates_by_code() -> None:
    text = """00700 ABCDEFGHIJKL TENCENT 1.0
00700 ABCDEFGHIJKL TENCENT HLDGS 1.0
"""
    df = parse_constituent_lines_from_factsheet_text(text)
    assert len(df) == 1
    assert df.iloc[0]["code"] == "00700"


def test_parse_empty_raises() -> None:
    try:
        parse_constituent_lines_from_factsheet_text("no valid lines here\n")
    except HangSengDataError:
        return
    raise AssertionError("expected HangSengDataError")


def test_load_full_constituents_csv(tmp_path: Path) -> None:
    p = tmp_path / "hs.csv"
    p.write_text(
        "Stock Code,Company Name\n700,Tencent\n9988,Alibaba\n",
        encoding="utf-8-sig",
    )
    df = load_hschk100_constituents({"full_constituents_csv": str(p.resolve())})
    assert len(df) == 2
    assert set(df["code"]) == {"00700", "09988"}


def test_read_hk_daily_roundtrip(tmp_path: Path) -> None:
    from quant_system.data.hang_seng_indexes import read_hk_constituent_daily_csv

    q = tmp_path / "00700.csv"
    pd.DataFrame({
        "date": ["2024-01-02", "2024-01-03"],
        "open": [1.0, 1.1],
        "high": [1.1, 1.2],
        "low": [0.9, 1.0],
        "close": [1.05, 1.15],
        "volume": [1e6, 2e6],
    }).to_csv(q, index=False, encoding="utf-8-sig")
    df = read_hk_constituent_daily_csv(tmp_path, "00700")
    assert len(df) == 2
    assert df.iloc[-1]["close"] == 1.15
