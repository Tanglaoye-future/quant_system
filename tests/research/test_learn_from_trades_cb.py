"""PR12 — learn_from_trades.py CB 分支契约测试 (2026-06-17).

延续 [[session_2026_06_08_self_learning_pipeline]] L5 设计:
  - Backstop #3 强制: N < min_sample 拒输出分布差结论
  - Backstop #5: 无 scipy 依赖

CB-specific:
  - PR12 bug fix: 修 fetch_closed_trades A_mom 桶不再吞 CB 行 (PR8 前 if market!=hk: A_mom 把 cb_a 误归)
  - PR12 §5 sleeve-aware: CB 用 cb_exit_type (PR11 taxonomy SCORE_EXIT/STOP_LOSS/FORCE_REDEEM/REBALANCE/DELISTED/OTHER)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "research" / "learn_from_trades.py"


@pytest.fixture(scope="module")
def learn_mod():
    spec = importlib.util.spec_from_file_location("_learn_from_trades_for_test_cb", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_learn_from_trades_for_test_cb"] = mod
    spec.loader.exec_module(mod)
    return mod


def _cb_trade(
    code: str, pnl: float, cb_exit_type: str = "SCORE_EXIT",
    dual_low_score: float = 128.0, conversion_premium: float = 20.0,
    scale_remain_yi: float = 4.5, rating: str = "AA",
    hold_days: int = 31, exit_reason: str = "score_over_180",
) -> dict:
    return {
        "symbol": code, "market": "cb_a", "strategy": "cb_double_low",
        "entry_date": "2026-07-01", "exit_date": "2026-08-01",
        "entry_price": 108.0, "exit_price": 108.0 * (1 + pnl),
        "pnl_pct": pnl, "hold_days": hold_days,
        "exit_reason": exit_reason,
        "entry_features": {
            "dual_low_score": dual_low_score,
            "conversion_premium_rate": conversion_premium,
            "scale_remain_yi": scale_remain_yi,
            "rating": rating,
            "rank_at_entry": 5,
        },
        "exit_features": {
            "cb_exit_type": cb_exit_type,
            "exit_type": "OTHER",  # equity-flavor 兜底 (PR11 update_exit_features 浅合并保留)
            "hold_days_bucket": "21-60",
            "pnl_yuan": pnl * 108.0 * 10,
            "exit_reason_raw": exit_reason,
        },
    }


# ── 1. fetch_closed_trades sleeve classification ──────────────────────────


def test_classify_cb_sleeve_via_market_and_strategy(learn_mod):
    """journal_trades market='cb_a' & strategy='cb_double_low' → cb_double_low sleeve."""
    fake_trade = MagicMock()
    fake_trade.market = "cb_a"
    fake_trade.strategy = "cb_double_low"
    assert learn_mod._classify_journal_sleeve(fake_trade) == "cb_double_low"


def test_classify_a_share_equity_into_a_mom(learn_mod):
    """A 股 equity_momentum 仍归 A_mom (无回归)."""
    fake = MagicMock(market="a_share", strategy="equity_momentum")
    assert learn_mod._classify_journal_sleeve(fake) == "A_mom"


def test_classify_hk_into_hk_mom(learn_mod):
    fake = MagicMock(market="hk_share", strategy="equity_hk_momentum")
    assert learn_mod._classify_journal_sleeve(fake) == "HK_mom"


def test_classify_cb_a_without_strategy_falls_back_to_a_mom(learn_mod):
    """防御性: market='cb_a' 但 strategy 缺 → 不归 cb (避免 mislabeled 数据混桶)."""
    fake = MagicMock(market="cb_a", strategy=None)
    # 当前实现: cb_a + no strategy → A_mom (fallback, 保守)
    assert learn_mod._classify_journal_sleeve(fake) == "A_mom"


# ── 2. build_report 含 CB sleeve ──────────────────────────────────────────


def test_empty_cb_sleeve_n_zero(learn_mod):
    closed = {"A_mom": [], "HK_mom": [], "cb_double_low": [], "zhuang": []}
    rep = learn_mod.build_report(closed, min_sample=10,
                                  benchmark_fetcher=lambda *a, **k: None)
    cb = rep["sleeves"]["cb_double_low"]
    assert cb["n_closed"] == 0
    assert cb["pnl_summary"] is None
    assert cb["alpha_summary"] is None


def test_cb_sleeve_small_sample_warns(learn_mod):
    """N=3 < min_sample=10: pnl_summary 出, winner_vs_loser None + warn."""
    closed = {
        "A_mom": [], "HK_mom": [],
        "cb_double_low": [
            _cb_trade("113008", 0.10),
            _cb_trade("127090", -0.02),
            _cb_trade("128137", -0.05),
        ],
        "zhuang": [],
    }
    rep = learn_mod.build_report(closed, min_sample=10,
                                  benchmark_fetcher=lambda *a, **k: None)
    cb = rep["sleeves"]["cb_double_low"]
    assert cb["n_closed"] == 3
    assert cb["sample_sufficient"] is False
    assert cb["pnl_summary"]["win_rate"] == pytest.approx(1 / 3)
    assert cb.get("winner_vs_loser_numeric") is None
    assert any("min_sample" in w for w in cb["warnings"])


def test_cb_sleeve_alpha_summary_not_connected(learn_mod):
    """CB 没接入 benchmark (集思录无 baostock 接口) → alpha_summary reason='未接入'."""
    closed = {
        "A_mom": [], "HK_mom": [],
        "cb_double_low": [_cb_trade("113008", 0.05)],
        "zhuang": [],
    }
    rep = learn_mod.build_report(closed, min_sample=10,
                                  benchmark_fetcher=lambda *a, **k: None)
    cb = rep["sleeves"]["cb_double_low"]
    assert cb["alpha_summary"]["benchmark_code"] is None
    assert cb["alpha_summary"]["benchmark_name"] is None
    assert "未接入" in cb["alpha_summary"]["reason"]


# ── 3. §5 sleeve-aware exit_type (CB 用 cb_exit_type) ────────────────────


def test_cb_exit_summary_uses_cb_exit_type(learn_mod):
    """PR12 关键: CB sleeve exit_summary 按 cb_exit_type 分桶 (PR11 taxonomy),
    不用 equity exit_type (CB reason 在 equity taxonomy 全 OTHER 无信息量).
    """
    # 12 笔 CB closed, 混合 exit_type: 6 winners SCORE_EXIT + 6 losers (4 STOP_LOSS + 2 FORCE_REDEEM)
    closed = {
        "A_mom": [], "HK_mom": [],
        "cb_double_low": (
            [_cb_trade(f"W{i}", 0.10, cb_exit_type="SCORE_EXIT") for i in range(6)]
            + [_cb_trade(f"L{i}", -0.15, cb_exit_type="STOP_LOSS",
                         exit_reason="stop_loss") for i in range(4)]
            + [_cb_trade(f"R{i}", -0.05, cb_exit_type="FORCE_REDEEM",
                         exit_reason="redeem_announced") for i in range(2)]
        ),
        "zhuang": [],
    }
    rep = learn_mod.build_report(closed, min_sample=10,
                                  benchmark_fetcher=lambda *a, **k: None)
    cb = rep["sleeves"]["cb_double_low"]
    ex = cb["exit_summary"]
    # 关键: exit_type_field 标 cb_exit_type
    assert ex["exit_type_field"] == "cb_exit_type"
    # winners 全是 SCORE_EXIT (6)
    assert ex["exit_type_winners"] == {"SCORE_EXIT": 6}
    # losers 4 STOP_LOSS + 2 FORCE_REDEEM
    assert ex["exit_type_losers"] == {"STOP_LOSS": 4, "FORCE_REDEEM": 2}


def test_equity_exit_summary_still_uses_equity_exit_type(learn_mod):
    """无回归: A_mom / HK_mom / zhuang sleeve exit_summary 仍按 equity exit_type 分桶."""
    eq_trade = {
        "symbol": "601939", "market": "a_share", "strategy": "equity_momentum",
        "entry_date": "2026-05-22", "exit_date": "2026-06-01",
        "entry_price": 10.0, "exit_price": 11.0,
        "pnl_pct": 0.10, "hold_days": 10,
        "exit_reason": "trailing_stop",
        "entry_features": {"rsi": 60.0},
        "exit_features": {"exit_type": "STOP_TRAIL", "hold_days_bucket": "6-20"},
    }
    closed = {
        "A_mom": [{**eq_trade, "symbol": f"S{i}"} for i in range(12)],
        "HK_mom": [], "cb_double_low": [], "zhuang": [],
    }
    rep = learn_mod.build_report(closed, min_sample=10,
                                  benchmark_fetcher=lambda *a, **k: None)
    a = rep["sleeves"]["A_mom"]
    assert a["exit_summary"]["exit_type_field"] == "exit_type"
    assert a["exit_summary"]["exit_type_winners"] == {"STOP_TRAIL": 12}


# ── 4. CB winner-vs-loser numeric (CB 特有 features) ─────────────────────


def test_cb_winner_vs_loser_numeric_uses_cb_entry_features(learn_mod):
    """N >= min_sample: CB winner-vs-loser §3 拿 entry_features 的 CB 特有数值字段
    (dual_low_score / conversion_premium_rate / scale_remain_yi).
    """
    # 高 dual_low_score 入场 = winners; 低 dual_low_score = losers
    closed = {
        "A_mom": [], "HK_mom": [],
        "cb_double_low": (
            [_cb_trade(f"W{i}", 0.10, dual_low_score=130.0,
                       conversion_premium=15.0, scale_remain_yi=5.0)
             for i in range(6)]
            + [_cb_trade(f"L{i}", -0.10, dual_low_score=110.0,
                         conversion_premium=25.0, scale_remain_yi=2.0,
                         cb_exit_type="STOP_LOSS",
                         exit_reason="stop_loss")
               for i in range(6)]
        ),
        "zhuang": [],
    }
    rep = learn_mod.build_report(closed, min_sample=10,
                                  benchmark_fetcher=lambda *a, **k: None)
    cb = rep["sleeves"]["cb_double_low"]
    nrows = cb["winner_vs_loser_numeric"]
    features_seen = {r["feature"] for r in nrows}
    # CB 特有 entry_features 都进 numeric 表
    assert "dual_low_score" in features_seen
    assert "conversion_premium_rate" in features_seen
    assert "scale_remain_yi" in features_seen
    # rating 是 categorical (str) 不应进 numeric
    assert "rating" not in features_seen


# ── 5. render_markdown 不挂在 CB sleeve ──────────────────────────────────


def test_render_markdown_with_cb_sleeve(learn_mod):
    closed = {
        "A_mom": [], "HK_mom": [],
        "cb_double_low": [_cb_trade("113008", 0.05)],
        "zhuang": [],
    }
    rep = learn_mod.build_report(closed, min_sample=10,
                                  benchmark_fetcher=lambda *a, **k: None)
    md = learn_mod.render_markdown(rep)
    assert "## cb_double_low" in md
    assert "n_closed = **1**" in md


def test_render_markdown_cb_exit_summary_section(learn_mod):
    """§5 exit_features 分布段, CB 数据展示 cb_exit_type bucket."""
    closed = {
        "A_mom": [], "HK_mom": [],
        "cb_double_low": (
            [_cb_trade(f"W{i}", 0.10, cb_exit_type="SCORE_EXIT") for i in range(6)]
            + [_cb_trade(f"L{i}", -0.10, cb_exit_type="STOP_LOSS",
                         exit_reason="stop_loss") for i in range(6)]
        ),
        "zhuang": [],
    }
    rep = learn_mod.build_report(closed, min_sample=10,
                                  benchmark_fetcher=lambda *a, **k: None)
    md = learn_mod.render_markdown(rep)
    assert "SCORE_EXIT" in md  # CB taxonomy 标签
    assert "STOP_LOSS" in md
