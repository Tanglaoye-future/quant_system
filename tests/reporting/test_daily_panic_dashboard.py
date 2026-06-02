"""daily_panic_dashboard 单测 — 不依赖 akshare 网络.

只测纯函数逻辑:
  - score_keywords: 关键词计数
  - load_sleeve_candidates: JSON schema 适配
  - compute_sleeve_overlap: 交集计算
  - render_html: 主框架 + section 标题 + dataclass payload 兼容
  - scan_panic_and_rebound: 用 mock loader 跑边界 case
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "reporting"))

from daily_panic_dashboard import (
    PanicCandidate,
    ReboundCandidate,
    LHBRow,
    SentimentScore,
    SleeveOverlap,
    score_keywords,
    load_sleeve_candidates,
    compute_sleeve_overlap,
    scan_panic_and_rebound,
    render_html,
    _payload,
)


# ── score_keywords ────────────────────────────────────────────────────────

def test_score_keywords_bull():
    bull, bear = score_keywords("市场利好刺激, 突破新高, 积极反弹")
    assert bull >= 4   # 利好/刺激/突破/新高/积极/反弹 ≥ 4
    assert bear == 0


def test_score_keywords_bear():
    bull, bear = score_keywords("暴跌恐慌, 重挫破发利空")
    assert bull == 0
    assert bear >= 4


def test_score_keywords_neutral_empty():
    assert score_keywords("") == (0, 0)
    assert score_keywords("公司发布年报, 营收增长") == (0, 0)


def test_score_keywords_mixed():
    bull, bear = score_keywords("反弹后回调")
    assert bull == 1
    assert bear == 1


# ── load_sleeve_candidates ────────────────────────────────────────────────

def test_load_sleeve_candidates_zhuang_schema(tmp_path: Path):
    p = tmp_path / "z.json"
    p.write_text(json.dumps({
        "top_candidates": [
            {"code": "600519", "total": 85},
            {"code": "000001", "total": 80},
        ]
    }))
    codes = load_sleeve_candidates(p, ("top_candidates", "candidates", "signals"))
    assert codes == ["600519", "000001"]


def test_load_sleeve_candidates_quant_schema(tmp_path: Path):
    p = tmp_path / "q.json"
    p.write_text(json.dumps({
        "signals": [{"code": "1", "score": 1}],
        "candidates": [{"code": "600000"}],
    }))
    codes = load_sleeve_candidates(p, ("signals", "candidates"))
    # signals 的 code='1' 会 zfill 到 '000001'
    assert "000001" in codes
    assert "600000" in codes


def test_load_sleeve_candidates_missing_file(tmp_path: Path):
    assert load_sleeve_candidates(tmp_path / "nope.json", ("signals",)) == []


def test_load_sleeve_candidates_string_list(tmp_path: Path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"candidates": ["600519", "000001"]}))
    codes = load_sleeve_candidates(p, ("candidates",))
    assert codes == ["600519", "000001"]


# ── compute_sleeve_overlap ────────────────────────────────────────────────

def test_compute_sleeve_overlap(tmp_path: Path):
    # 模拟 report/data
    (tmp_path / "zhuang.json").write_text(json.dumps({
        "top_candidates": [{"code": "600519"}, {"code": "000001"}]
    }))
    (tmp_path / "quant_a_share_equity_momentum.json").write_text(json.dumps({
        "signals": [{"code": "600000"}, {"code": "000001"}]
    }))
    (tmp_path / "quant_a_share_mean_reversion.json").write_text(json.dumps({
        "signals": []
    }))

    overlaps = compute_sleeve_overlap(
        panic_codes=["600519", "002345"],
        rebound_codes=["000001"],
        data_dir=tmp_path,
    )
    assert len(overlaps) == 3
    z = next(o for o in overlaps if o.sleeve == "zhuang")
    assert z.overlap_with_panic == ["600519"]
    assert z.overlap_with_rebound == ["000001"]

    a_mom = next(o for o in overlaps if "A_mom" in o.sleeve)
    assert a_mom.overlap_with_panic == []
    assert a_mom.overlap_with_rebound == ["000001"]


# ── scan_panic_and_rebound (mock loader) ──────────────────────────────────

def _mock_loader_from_panel(panel: dict[str, pd.DataFrame]):
    """返回 loader stub, get_daily(market, code, start, end) → panel[code] 切片."""
    mock = MagicMock()
    def _get(market, code, start, end):
        df = panel.get(code, pd.DataFrame())
        if df.empty:
            return df
        return df[(df["date"] >= start) & (df["date"] <= end)].reset_index(drop=True)
    mock.get_daily.side_effect = _get
    return mock


def _build_synthetic_px(panic_at: int | None = None, prior_panic: bool = False) -> pd.DataFrame:
    """造 25 个 trading day 的 OHLCV. panic_at 指定哪一行设 -10% + vol×3."""
    dates = pd.date_range("2026-05-01", periods=25, freq="B").strftime("%Y-%m-%d")
    close = [10.0] * 25
    vol = [1_000_000] * 25
    open_ = [10.0] * 25
    high = [10.1] * 25
    low = [9.9] * 25
    if panic_at is not None and 1 <= panic_at < 25:
        close[panic_at] = close[panic_at - 1] * 0.90  # -10%
        vol[panic_at] = 3_000_000
        open_[panic_at] = close[panic_at - 1] * 0.95
        high[panic_at] = close[panic_at - 1] * 0.96
        low[panic_at] = close[panic_at]
    if prior_panic and panic_at is not None and panic_at + 1 < 25:
        # T (panic_at+1): open gap up 2% above T-1 close
        open_[panic_at + 1] = close[panic_at] * 1.02
        close[panic_at + 1] = close[panic_at] * 1.03   # 反包: close > T-1 high
    return pd.DataFrame({
        "date": dates, "open": open_, "high": high, "low": low,
        "close": close, "volume": vol,
    })


def test_scan_panic_detects_drop():
    px = _build_synthetic_px(panic_at=20)
    loader = _mock_loader_from_panel({"600519": px})
    panic, rebound = scan_panic_and_rebound(
        loader, {"hs300": ["600519"]}, target_date=px["date"].iloc[20],
    )
    assert len(panic) == 1
    assert panic[0].code == "600519"
    assert panic[0].drop_pct < -0.05
    assert panic[0].vol_ratio > 1.5
    assert rebound == []


def test_scan_rebound_detects_gap_up():
    px = _build_synthetic_px(panic_at=20, prior_panic=True)
    loader = _mock_loader_from_panel({"600519": px})
    # target T = panic_at + 1 (反包当日)
    panic, rebound = scan_panic_and_rebound(
        loader, {"hs300": ["600519"]}, target_date=px["date"].iloc[21],
    )
    assert len(rebound) == 1
    assert rebound[0].code == "600519"
    assert rebound[0].today_open_vs_prior_close >= 0.01
    assert rebound[0].prior_drop_pct < -0.05


def test_scan_panic_ignores_normal_day():
    px = _build_synthetic_px()  # 无 panic
    loader = _mock_loader_from_panel({"600519": px})
    panic, rebound = scan_panic_and_rebound(
        loader, {"hs300": ["600519"]}, target_date=px["date"].iloc[20],
    )
    assert panic == []
    assert rebound == []


def test_scan_panic_skips_short_history():
    short = _build_synthetic_px(panic_at=20).iloc[:10]   # 仅 10 行 < 22 阈值
    loader = _mock_loader_from_panel({"X": short})
    panic, rebound = scan_panic_and_rebound(
        loader, {"hs300": ["X"]}, target_date=short["date"].iloc[-1],
    )
    assert panic == []
    assert rebound == []


# ── render_html ───────────────────────────────────────────────────────────

def _empty_payload(report_date: str) -> dict:
    return _payload(panic=[], rebound=[], lhb=[], sentiment=[], overlaps=[])


def test_render_html_empty_renders_all_sections():
    payload = _empty_payload("2026-06-02")
    html = render_html(payload, "2026-06-02")
    assert "Panic / Capitulation Dashboard" in html
    assert "① Panic candidates" in html
    assert "② 反包候选" in html
    assert "③ LHB 机构净买" in html
    assert "④ 大盘情绪" in html
    assert "⑤ Sleeve overlap" in html
    assert "今日无 panic 候选" in html
    assert "今日无反包候选" in html


def test_render_html_with_data():
    panic = [PanicCandidate("600519", "hs300", -0.08, 2.5, 1500.0, -0.12)]
    rebound = [ReboundCandidate("000001", "csi1000", -0.06, 1.8, 0.025)]
    lhb = [LHBRow("002345", "X", "2026-06-01", 1.2e8, "日跌幅 -7%", -7.1)]
    sentiment = [SentimentScore("财新", 100, 5, 12, -7/17, ["sample_bull"], ["sample_bear"])]
    overlaps = [SleeveOverlap("zhuang", ["600519"], ["600519"], [])]
    payload = _payload(panic, rebound, lhb, sentiment, overlaps)
    html = render_html(payload, "2026-06-02")
    assert "600519" in html
    assert "000001" in html
    assert "002345" in html
    assert "1.20 亿" in html
    assert "-0.41" in html or "-0.412" in html      # sentiment score
    assert "zhuang" in html


def test_payload_dataclass_serializable():
    panic = [PanicCandidate("X", "hs300", -0.06, 1.6, 10.0, -0.08)]
    sentiment = [SentimentScore("src", 10, 1, 2, -0.33, [], [])]
    payload = _payload(panic, [], [], sentiment, [])
    s = json.dumps(payload, ensure_ascii=False)
    back = json.loads(s)
    assert back["panic"][0]["code"] == "X"
    assert back["sentiment"][0]["source"] == "src"
