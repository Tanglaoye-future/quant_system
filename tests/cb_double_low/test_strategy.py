"""CB double-low §1 评分 + §3 入场/持有/出场 单元测试 (PR4).

锁定 docs/specs/convertible_bond_sleeve.md §1 + §3:
- score = close + conversion_premium_rate
- 入场: 每日按 score 升序取前 N=20 等权
- 持仓: 仍在前 N*1.5 名内则保留, 否则换仓
- 出场: 强赎公告 / 剩余年限<0.5 / score>150 / close<85
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from quant_system.strategies.cb_double_low.engine.strategy import (
    CBDoubleLowConfig,
    compute_target_portfolio,
    evaluate_holdings,
    score_dual_low,
    select_entry,
)
from quant_system.strategies.cb_double_low.universe.filter import UniverseFilterConfig


def _make_scored(n: int = 30) -> pd.DataFrame:
    """生成 n 只债, dual_low_score 从 100 递增到 100+n-1."""
    codes = [f"1{i:05d}" for i in range(n)]
    return pd.DataFrame(
        {
            "bond_code": codes,
            "close": [100.0 + i for i in range(n)],
            "conversion_premium_rate": [0.0] * n,
            "dual_low_score": [100.0 + i for i in range(n)],
        }
    )


# ── §1 评分 ──────────────────────────────────────────────────────────


def test_score_dual_low_formula():
    """score = close + conversion_premium_rate."""
    df = pd.DataFrame(
        {
            "close": [100.0, 110.0, 95.5],
            "conversion_premium_rate": [10.0, 5.0, 25.5],
        }
    )
    scores = score_dual_low(df)
    assert list(scores) == [110.0, 115.0, 121.0]


# ── §3 入场: select_entry ────────────────────────────────────────────


def test_select_entry_returns_top_n_by_lowest_score():
    """按 score 升序取前 N."""
    scored = _make_scored(30)
    top10 = select_entry(scored, n=10)
    assert len(top10) == 10
    assert top10[0] == "100000", "score 最低的必须排第一"
    assert top10[-1] == "100009"


def test_select_entry_drops_nan_scores():
    """score NaN 自动排除 (不进 entry)."""
    scored = _make_scored(5)
    scored.loc[2, "dual_low_score"] = float("nan")
    top3 = select_entry(scored, n=3)
    assert "100002" not in top3, "NaN score 必须排除"
    assert len(top3) == 3


# ── §3 持仓: evaluate_holdings ────────────────────────────────────────


def test_evaluate_holdings_keeps_within_buffer():
    """仍在前 N*1.5 名内的持仓保留."""
    scored = _make_scored(50)
    cfg = CBDoubleLowConfig(n_entry=20, n_hold_buffer=1.5)
    # 持仓 100025 在第 25 名 (rank index 25), 在 buffer 30 名内 → 保留
    result = evaluate_holdings(["100025"], scored, cfg, redemption_today_codes=set())
    assert result["kept"] == ["100025"]
    assert result["exited"] == []


def test_evaluate_holdings_exits_outside_buffer():
    """跌出 N*1.5 名 → 出场, reason='out_of_top_band'."""
    scored = _make_scored(50)
    cfg = CBDoubleLowConfig(n_entry=20, n_hold_buffer=1.5)
    # 100035 在第 35 名 > 30 buffer
    result = evaluate_holdings(["100035"], scored, cfg, redemption_today_codes=set())
    assert result["kept"] == []
    assert result["exited"] == [("100035", "out_of_top_band")]


def test_evaluate_holdings_exits_on_redeem():
    """持仓里命中 redemption_today_codes → 强制出场, reason='redeem_announced'."""
    scored = _make_scored(20)
    cfg = CBDoubleLowConfig()
    result = evaluate_holdings(
        ["100005"], scored, cfg, redemption_today_codes={"100005"}
    )
    assert result["exited"] == [("100005", "redeem_announced")]


def test_evaluate_holdings_exits_on_stop_loss():
    """持仓 close < stop_loss_close → 出场, reason='stop_loss'."""
    scored = _make_scored(20)
    cfg = CBDoubleLowConfig(stop_loss_close=85.0)
    scored.loc[scored["bond_code"] == "100005", "close"] = 80.0
    result = evaluate_holdings(["100005"], scored, cfg, redemption_today_codes=set())
    assert result["exited"] == [("100005", "stop_loss")]


def test_evaluate_holdings_exits_on_high_dual_low():
    """持仓 score > exit_dual_low_threshold → 出场, reason='dual_low_too_high'."""
    scored = _make_scored(20)
    cfg = CBDoubleLowConfig(exit_dual_low_threshold=150.0)
    scored.loc[scored["bond_code"] == "100005", "dual_low_score"] = 160.0
    result = evaluate_holdings(["100005"], scored, cfg, redemption_today_codes=set())
    # 注意: rank 排序会因为 100005 score 改成 160 后落到末尾, 应被 dual_low_too_high
    # 命中而非 out_of_top_band (优先级: redeem > out_of_universe > stop_loss > dual_low > rank)
    assert ("100005", "dual_low_too_high") in result["exited"]


def test_evaluate_holdings_exits_out_of_universe():
    """持仓码不在 scored (被 filter 砍掉) → 出场, reason='out_of_universe'."""
    scored = _make_scored(20)
    cfg = CBDoubleLowConfig()
    result = evaluate_holdings(
        ["999999"], scored, cfg, redemption_today_codes=set()
    )
    assert result["exited"] == [("999999", "out_of_universe")]


# ── 端到端: compute_target_portfolio ─────────────────────────────────


def _make_e2e_fixtures(n: int = 30):
    """端到端: universe + panel + redemption 同步."""
    codes = [f"1{i:05d}" for i in range(n)]
    universe = pd.DataFrame(
        {
            "bond_code": codes,
            "bond_name": codes,
            "stock_code": codes,
            "stock_name": codes,
            "listing_date": pd.to_datetime(["2020-01-01"] * n),
            "delisting_date": [pd.NaT] * n,
            "scale_remain": [10.0] * n,
            "credit_rating": ["AAA"] * n,
            "exit_status": ["active"] * n,
        }
    )
    panel = pd.DataFrame(
        {
            "bond_code": codes,
            "close": [100.0 + i for i in range(n)],
            "conversion_premium_rate": [0.0] * n,
        }
    )
    redemption = pd.DataFrame(
        columns=[
            "bond_code", "bond_name", "announcement_date",
            "last_trading_date", "maturity_date", "redemption_price", "status",
        ]
    )
    return universe, panel, redemption


def test_compute_target_portfolio_end_to_end_n_equal_weight():
    """端到端: 空仓 → 入场 N=20 等权 (每只 0.05)."""
    universe, panel, redemption = _make_e2e_fixtures(n=30)
    cfg = CBDoubleLowConfig(n_entry=20)
    out = compute_target_portfolio(
        universe, panel, redemption,
        current_holdings=[],
        asof=date(2026, 6, 16),
        config=cfg,
    )
    assert len(out["target_weights"]) == 20
    assert all(abs(w - 1 / 20) < 1e-9 for w in out["target_weights"].values())
    assert out["entered"] == [f"1{i:05d}" for i in range(20)]
    assert out["kept"] == []


def test_compute_target_portfolio_keeps_holdings_inside_buffer():
    """端到端: 持仓 100025 在 buffer 内 → 保留 + 补 19 只新仓."""
    universe, panel, redemption = _make_e2e_fixtures(n=50)
    cfg = CBDoubleLowConfig(n_entry=20, n_hold_buffer=1.5)
    out = compute_target_portfolio(
        universe, panel, redemption,
        current_holdings=["100025"],
        asof=date(2026, 6, 16),
        config=cfg,
    )
    assert "100025" in out["kept"]
    assert len(out["target_weights"]) == 20
    # 100025 在保留集, 不进 entered
    assert "100025" not in out["entered"]


def test_compute_target_portfolio_returns_filter_stats():
    """filter_stats 必须穿透到 output."""
    universe, panel, redemption = _make_e2e_fixtures(n=30)
    cfg = CBDoubleLowConfig()
    out = compute_target_portfolio(
        universe, panel, redemption,
        current_holdings=[],
        asof=date(2026, 6, 16),
        config=cfg,
    )
    assert "filter_stats" in out
    assert out["filter_stats"]["initial"] == 30
