"""PR10 — CB sleeve 实时风控单测 (2026-06-17).

复用 AlertEvent + alerts_sent 表 + Telegram 通道. CB-specific 评估:
  - cb_break_stop_loss: close < stop_loss_close (默认 85)
  - cb_redeem_imminent: last_trading_date 在 N 天内

不在 PR10 范围: dual_low_score>180 (慢信号 → PR9 daily rebalance 覆盖),
portfolio_unrealized_floor / peak_drawdown (PR11+).
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from quant_system.strategies.cb_double_low.journal import CB_MARKET, CB_STRATEGY
from quant_system.strategies.cb_double_low.risk.intraday import (
    CBIntradayConfig,
    CBPositionSnapshot,
    build_cb_position_snapshots,
    evaluate_cb_alerts,
)


# ── 1. CBIntradayConfig.from_yaml_dict ───────────────────────────────────


def test_cfg_disabled_default():
    cfg = CBIntradayConfig.from_yaml_dict({})
    assert cfg.enabled is False
    assert cfg.stop_loss_close == 85.0
    assert cfg.redeem_within_days == 30


def test_cfg_pulls_stop_loss_from_cb_strategy_yaml():
    """stop_loss_close 单源: config/cb_double_low.yaml strategy.stop_loss_close, 避免 PM 两处改漏."""
    cb_strat = {"strategy": {"stop_loss_close": 80.0}}
    cfg = CBIntradayConfig.from_yaml_dict(
        {"enabled": True, "redeem_within_days": 14}, cb_strat,
    )
    assert cfg.enabled is True
    assert cfg.stop_loss_close == 80.0
    assert cfg.redeem_within_days == 14


# ── 2. evaluate_cb_alerts — 4 场景 ────────────────────────────────────────


def _cfg(enabled: bool = True, stop_loss: float = 85.0, redeem_days: int = 30) -> CBIntradayConfig:
    return CBIntradayConfig(
        enabled=enabled,
        stop_loss_close=stop_loss,
        redeem_within_days=redeem_days,
    )


def test_no_alerts_when_disabled():
    snaps = [CBPositionSnapshot(
        bond_code="113008", bond_name="电气", current_close=70.0,
    )]
    out = evaluate_cb_alerts(snaps, date(2026, 7, 1), _cfg(enabled=False))
    assert out == []


def test_cb_break_stop_loss_critical():
    """close=70 < stop_loss=85 → cb_break_stop_loss critical."""
    snaps = [CBPositionSnapshot(
        bond_code="113008", bond_name="电气", current_close=70.0,
    )]
    out = evaluate_cb_alerts(snaps, date(2026, 7, 1), _cfg())
    assert len(out) == 1
    ev = out[0]
    assert ev.alert_type == "cb_break_stop_loss"
    assert ev.severity == "critical"
    assert ev.strategy_name == CB_STRATEGY
    assert ev.symbol == "113008"
    assert ev.payload["current_close"] == 70.0
    assert ev.payload["stop_loss_close"] == 85.0
    assert ev.payload["breach_pct"] == pytest.approx((85.0 - 70.0) / 85.0)
    assert "113008" in ev.message
    assert "电气" in ev.message
    assert "70.00" in ev.message


def test_no_break_when_close_above_threshold():
    snaps = [CBPositionSnapshot(
        bond_code="113008", bond_name="电气", current_close=100.0,
    )]
    out = evaluate_cb_alerts(snaps, date(2026, 7, 1), _cfg())
    assert out == []


def test_no_break_when_close_zero_or_negative():
    """spot 数据异常 (close<=0) → 静默跳过, 不发误告警."""
    snaps = [CBPositionSnapshot(
        bond_code="113008", bond_name="电气", current_close=0.0,
    )]
    out = evaluate_cb_alerts(snaps, date(2026, 7, 1), _cfg())
    assert out == []


def test_cb_redeem_imminent_within_window():
    """last_trading_date 在 30 天内 → cb_redeem_imminent critical."""
    snaps = [CBPositionSnapshot(
        bond_code="113008", bond_name="电气", current_close=120.0,
        redeem_last_trading_date=date(2026, 7, 20),  # 距 7/1 19 天
    )]
    out = evaluate_cb_alerts(snaps, date(2026, 7, 1), _cfg())
    assert len(out) == 1
    ev = out[0]
    assert ev.alert_type == "cb_redeem_imminent"
    assert ev.severity == "critical"
    assert ev.payload["days_to_redeem"] == 19
    assert ev.payload["last_trading_date"] == "2026-07-20"
    assert "19 天" in ev.message


def test_no_redeem_alert_outside_window():
    snaps = [CBPositionSnapshot(
        bond_code="113008", bond_name="电气", current_close=120.0,
        redeem_last_trading_date=date(2026, 9, 1),  # 距 7/1 62 天 > 30
    )]
    out = evaluate_cb_alerts(snaps, date(2026, 7, 1), _cfg(redeem_days=30))
    assert out == []


def test_no_redeem_alert_when_date_passed():
    """已过 last_trading_date 不再告警 (退市后不属于持仓评估范围)."""
    snaps = [CBPositionSnapshot(
        bond_code="113008", bond_name="电气", current_close=120.0,
        redeem_last_trading_date=date(2026, 6, 25),  # 在 asof 之前
    )]
    out = evaluate_cb_alerts(snaps, date(2026, 7, 1), _cfg())
    assert out == []


def test_both_alerts_can_fire_simultaneously():
    """close=70 + 强赎临近 → 2 个 alerts 同时触发 (不互斥)."""
    snaps = [CBPositionSnapshot(
        bond_code="113008", bond_name="电气", current_close=70.0,
        redeem_last_trading_date=date(2026, 7, 15),
    )]
    out = evaluate_cb_alerts(snaps, date(2026, 7, 1), _cfg())
    assert len(out) == 2
    types = {ev.alert_type for ev in out}
    assert types == {"cb_break_stop_loss", "cb_redeem_imminent"}


# ── 3. build_cb_position_snapshots ───────────────────────────────────────


def test_build_snapshots_skips_missing_spot():
    """spot_map 缺 code → 跳过 (网络挂时不发误告警)."""
    holdings = [
        {"symbol": "113008", "market": CB_MARKET, "notes": "电气转债"},
        {"symbol": "127090", "market": CB_MARKET, "notes": "兴瑞转债"},
    ]
    spot = {"113008": {"close": 90.0, "bond_name": "电气"}}
    snaps = build_cb_position_snapshots(holdings, spot, None)
    assert len(snaps) == 1
    assert snaps[0].bond_code == "113008"
    # notes 优先于 spot.bond_name
    assert snaps[0].bond_name == "电气转债"
    assert snaps[0].redeem_last_trading_date is None  # redemption_df None


def test_build_snapshots_filters_non_cb_market():
    """混入 equity (a_share) 不应混回 CB 评估."""
    holdings = [
        {"symbol": "113008", "market": CB_MARKET, "notes": "电气转债"},
        {"symbol": "601939", "market": "a_share", "notes": "建行"},  # 不是 CB
    ]
    spot = {
        "113008": {"close": 90.0, "bond_name": "电气"},
        "601939": {"close": 10.0, "bond_name": "建行"},
    }
    snaps = build_cb_position_snapshots(holdings, spot, None)
    assert {s.bond_code for s in snaps} == {"113008"}


def test_build_snapshots_attaches_redemption_date():
    holdings = [{"symbol": "113008", "market": CB_MARKET, "notes": "电气转债"}]
    spot = {"113008": {"close": 120.0, "bond_name": "电气"}}
    redemption = pd.DataFrame({
        "bond_code": ["113008"],
        "last_trading_date": [pd.Timestamp("2026-07-15")],
    })
    snaps = build_cb_position_snapshots(holdings, spot, redemption)
    assert snaps[0].redeem_last_trading_date == date(2026, 7, 15)


def test_build_snapshots_handles_empty_notes():
    """notes 为空时回退 spot.bond_name."""
    holdings = [{"symbol": "113008", "market": CB_MARKET, "notes": ""}]
    spot = {"113008": {"close": 90.0, "bond_name": "spot 电气"}}
    snaps = build_cb_position_snapshots(holdings, spot, None)
    assert snaps[0].bond_name == "spot 电气"
