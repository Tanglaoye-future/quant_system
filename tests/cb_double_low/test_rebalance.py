"""PR9 — CB 月度 rebalance signal payload + mode 判定单测 (2026-06-17).

PR4 已覆盖策略层 evaluate_holdings / compute_target_portfolio 6 出场场景.
PR9 不重复, 只测:
  - is_rebalance_day 月初判定
  - build_rebalance_payload payload 结构 + urgent / deferred flag
  - list_open_cb_holdings 从 Journal 反查 bond_code 列表
  - 整合 6 场景: 空首跑 / 全 HOLD / 1 SELL 1 BUY / 强赎 SELL / 止损 SELL / score 越线 SELL
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from quant_system.db.models import Base
from quant_system.strategies.cb_double_low.engine.rebalance import (
    build_rebalance_payload,
    is_rebalance_day,
)
from quant_system.strategies.cb_double_low.journal import (
    CB_MARKET,
    CB_STRATEGY,
    Journal,
    build_cb_trade_open,
    list_open_cb_holdings,
)


# ── 1. is_rebalance_day ─────────────────────────────────────────────────


def test_is_rebalance_day_month_start():
    assert is_rebalance_day(date(2026, 7, 1)) is True
    assert is_rebalance_day(date(2026, 7, 3)) is True
    assert is_rebalance_day(date(2026, 7, 5)) is True


def test_is_rebalance_day_month_middle_and_end():
    assert is_rebalance_day(date(2026, 7, 6)) is False
    assert is_rebalance_day(date(2026, 7, 15)) is False
    assert is_rebalance_day(date(2026, 7, 31)) is False


# ── 2. list_open_cb_holdings ────────────────────────────────────────────


@pytest.fixture
def journal() -> Journal:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Journal(sessionmaker=sessionmaker(bind=engine, expire_on_commit=False))


def _open_cb(j: Journal, code: str, score: float = 128.0):
    j.open_trade(build_cb_trade_open(
        bond_code=code, bond_name=f"{code}转债", entry_date="2026-07-01",
        entry_price=108.0, entry_size=10, dual_low_score=score, rank=1,
        conversion_premium_rate=20.0,
    ))


def test_list_open_cb_holdings_empty(journal: Journal):
    assert list_open_cb_holdings(journal) == []


def test_list_open_cb_holdings_returns_only_cb_codes(journal: Journal):
    _open_cb(journal, "113008")
    _open_cb(journal, "127090")
    # 混入 equity 仓: 不应混回
    from quant_system.strategies.equity_factor.journal.journal import TradeOpen
    journal.open_trade(TradeOpen(
        symbol="601939", market="a_share", strategy="equity_momentum",
        entry_date="2026-07-01", entry_price=10.0, entry_size=100,
    ))
    holdings = list_open_cb_holdings(journal)
    assert set(holdings) == {"113008", "127090"}


# ── 3. build_rebalance_payload — 6 场景 ──────────────────────────────────


def _make_ranked(entries: list[tuple[str, str, float, float, float]]) -> list[dict]:
    """entries: [(code, name, close, prem, score), ...] → advisory_entries dict list."""
    return [
        {
            "rank": i + 1, "bond_code": code, "bond_name": name,
            "close": close, "conversion_premium_rate": prem,
            "dual_low_score": score, "warn_redeem_near": False,
        }
        for i, (code, name, close, prem, score) in enumerate(entries)
    ]


def test_payload_empty_holdings_rebalance_day_all_buy():
    """场景 1: 空持仓 + rebalance day → 全 entered, BUY 不 deferred, HOLD/SELL 空."""
    ranked = _make_ranked([
        ("100001", "AA转债", 105.0, 22.0, 127.0),
        ("100002", "BB转债", 108.0, 18.0, 126.0),
    ])
    out = {
        "kept": [],
        "exited": [],
        "entered": ["100001", "100002"],
        "target_weights": {"100001": 0.05, "100002": 0.05},
        "filter_stats": {},
    }
    p = build_rebalance_payload(
        portfolio_out=out, ranked=ranked, redeem_active=set(), is_rebalance=True,
    )
    assert p["mode"] == "rebalance"
    assert p["diff_summary"]["n_hold"] == 0
    assert p["diff_summary"]["n_sell"] == 0
    assert p["diff_summary"]["n_buy"] == 2
    assert p["diff_summary"]["n_buy_deferred"] == 0
    assert all(b["deferred"] is False for b in p["buy"])
    assert p["buy"][0]["bond_code"] == "100001"
    assert p["buy"][0]["bond_name"] == "AA转债"
    assert p["buy"][0]["weight"] == pytest.approx(0.05)


def test_payload_maintenance_day_buy_is_deferred():
    """场景 2: 平日 BUY 标 deferred (等月初执行)."""
    ranked = _make_ranked([("100001", "AA转债", 105.0, 22.0, 127.0)])
    out = {
        "kept": [], "exited": [], "entered": ["100001"],
        "target_weights": {"100001": 0.05}, "filter_stats": {},
    }
    p = build_rebalance_payload(
        portfolio_out=out, ranked=ranked, redeem_active=set(), is_rebalance=False,
    )
    assert p["mode"] == "maintenance"
    assert p["buy"][0]["deferred"] is True
    assert p["diff_summary"]["n_buy_deferred"] == 1


def test_payload_full_hold_no_diff():
    """场景 3: 全 HOLD (kept full), entered/exited 空 → diff_summary 全 0."""
    ranked = _make_ranked([
        ("100001", "AA转债", 105.0, 22.0, 127.0),
        ("100002", "BB转债", 108.0, 18.0, 126.0),
    ])
    out = {
        "kept": ["100001", "100002"],
        "exited": [],
        "entered": [],
        "target_weights": {"100001": 0.05, "100002": 0.05},
        "filter_stats": {},
    }
    p = build_rebalance_payload(
        portfolio_out=out, ranked=ranked, redeem_active=set(), is_rebalance=True,
    )
    assert p["diff_summary"]["n_hold"] == 2
    assert p["diff_summary"]["n_sell"] == 0
    assert p["diff_summary"]["n_buy"] == 0
    assert {h["bond_code"] for h in p["hold"]} == {"100001", "100002"}
    assert p["hold"][0]["weight"] == pytest.approx(0.05)


def test_payload_one_sell_one_buy():
    """场景 4: 1 SELL (out_of_top_band) + 1 BUY (替换)."""
    ranked = _make_ranked([
        ("100001", "AA转债", 105.0, 22.0, 127.0),
        ("100003", "CC转债", 110.0, 16.0, 126.0),  # 新 BUY
    ])
    out = {
        "kept": ["100001"],
        "exited": [("100002", "out_of_top_band")],
        "entered": ["100003"],
        "target_weights": {"100001": 0.05, "100003": 0.05},
        "filter_stats": {},
    }
    p = build_rebalance_payload(
        portfolio_out=out, ranked=ranked, redeem_active=set(), is_rebalance=True,
    )
    assert p["diff_summary"]["n_hold"] == 1
    assert p["diff_summary"]["n_sell"] == 1
    assert p["diff_summary"]["n_buy"] == 1
    assert p["sell"][0]["bond_code"] == "100002"
    assert p["sell"][0]["reason"] == "out_of_top_band"
    assert p["sell"][0]["urgent"] is False  # rank 漂移非 urgent


def test_payload_redeem_announced_sell_is_urgent():
    """场景 5: 强赎 SELL → urgent=True, 无论 mode 都立即出场."""
    ranked = _make_ranked([("100001", "AA转债", 105.0, 22.0, 127.0)])
    out = {
        "kept": ["100001"],
        "exited": [("100002", "redeem_announced")],
        "entered": [],
        "target_weights": {"100001": 0.05},
        "filter_stats": {},
    }
    # maintenance day 也照样 urgent
    p = build_rebalance_payload(
        portfolio_out=out, ranked=ranked, redeem_active={"100002"},
        is_rebalance=False,
    )
    assert p["sell"][0]["reason"] == "redeem_announced"
    assert p["sell"][0]["urgent"] is True
    assert p["diff_summary"]["n_sell_urgent"] == 1


def test_payload_stop_loss_sell_is_urgent():
    """场景 6: 止损 SELL (close<85) → urgent=True."""
    ranked = _make_ranked([("100001", "AA转债", 105.0, 22.0, 127.0)])
    out = {
        "kept": ["100001"],
        "exited": [("100099", "stop_loss")],
        "entered": [],
        "target_weights": {"100001": 0.05},
        "filter_stats": {},
    }
    p = build_rebalance_payload(
        portfolio_out=out, ranked=ranked, redeem_active=set(), is_rebalance=True,
    )
    assert p["sell"][0]["reason"] == "stop_loss"
    assert p["sell"][0]["urgent"] is True


def test_payload_dual_low_too_high_sell_not_urgent():
    """补充: score>180 SELL → 非 urgent (慢出场, 可等月初统一执行)."""
    ranked = _make_ranked([("100001", "AA转债", 105.0, 22.0, 127.0)])
    out = {
        "kept": ["100001"],
        "exited": [("100099", "dual_low_too_high")],
        "entered": [],
        "target_weights": {"100001": 0.05},
        "filter_stats": {},
    }
    p = build_rebalance_payload(
        portfolio_out=out, ranked=ranked, redeem_active=set(), is_rebalance=True,
    )
    assert p["sell"][0]["reason"] == "dual_low_too_high"
    assert p["sell"][0]["urgent"] is False


def test_payload_missing_code_in_ranked_degrades_gracefully():
    """SELL 项可能在 advisory top N 外 (score 越线后不在 entries_top), 容错降级.

    HOLD/BUY 也容错 (避免 crash). 不在 ranked 的 code → bond_name='' / 其他 None.
    """
    ranked = _make_ranked([("100001", "AA转债", 105.0, 22.0, 127.0)])
    out = {
        "kept": ["100099"],  # 不在 ranked
        "exited": [("100098", "out_of_top_band")],
        "entered": [],
        "target_weights": {"100099": 0.05},
        "filter_stats": {},
    }
    p = build_rebalance_payload(
        portfolio_out=out, ranked=ranked, redeem_active=set(), is_rebalance=True,
    )
    # HOLD degrade
    assert p["hold"][0]["bond_code"] == "100099"
    assert p["hold"][0]["bond_name"] == ""
    assert p["hold"][0]["dual_low_score"] is None
    # SELL 仍有 code + reason
    assert p["sell"][0]["bond_code"] == "100098"
    assert p["sell"][0]["reason"] == "out_of_top_band"
