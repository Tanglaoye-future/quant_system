"""盘中实时风控核心评估 + Telegram 推送 + dedup 契约测试 (PR5 of spec §6)。

覆盖 spec §6.6 全部 6 case + 数学不变量；网络/DB 全 mock。
"""
from __future__ import annotations

from datetime import date, datetime, time

import pytest

from quant_system.intraday.core import (
    AlertEvent,
    IntradayConfig,
    PortfolioSnapshot,
    PositionSnapshot,
    evaluate_alerts,
    is_in_trading_window,
)
from quant_system.notify.telegram import TelegramSender


# ── fixtures ────────────────────────────────────────────────────────

def _cfg(**overrides) -> IntradayConfig:
    defaults = dict(
        enabled=True,
        proximity_to_stop_loss_pct=0.005,
        proximity_to_take_profit_pct=0.005,
        portfolio_unrealized_floor_pct=-0.05,
        portfolio_drawdown_pct=-0.07,
    )
    defaults.update(overrides)
    return IntradayConfig(**defaults)


def _pos(symbol="601939", strategy="equity_factor", market="a_share",
         entry=10.0, current=10.10, stop=9.50, tp=11.0,
         ma_long=None) -> PositionSnapshot:
    return PositionSnapshot(
        strategy_name=strategy, symbol=symbol, market=market,
        entry_price=entry, current_price=current,
        stop_loss=stop, take_profit=tp, ma_long=ma_long,
    )


def _port(strategy="equity_factor", pnl=-0.02, dd=None) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        strategy_name=strategy, unrealized_pnl_pct=pnl,
        drawdown_from_peak_pct=dd,
    )


# ── §6.6 trigger / dedup core cases ─────────────────────────────────

def test_no_alert_when_safe():
    """距止损 +5% / 距止盈 +9% / 浮亏 -2% / dd None → 0 alerts"""
    positions = [_pos(current=10.05, stop=9.50, tp=11.00)]
    portfolios = [_port(pnl=-0.02, dd=None)]
    events = evaluate_alerts(positions, portfolios, _cfg())
    assert events == []


def test_stop_loss_proximity_triggers():
    """距止损 < 0.5% → critical stop_loss_proximity 触发"""
    # current 9.55 / stop 9.52 → dist 0.003 < 0.005
    positions = [_pos(current=9.55, stop=9.52)]
    events = evaluate_alerts(positions, [], _cfg())
    assert len(events) == 1
    ev = events[0]
    assert ev.alert_type == "stop_loss_proximity"
    assert ev.severity == "critical"
    assert ev.payload["dist_to_stop_pct"] < 0.005
    assert "贴近止损" in ev.message


def test_take_profit_proximity_triggers():
    """距止盈 < 0.5% → warning take_profit_proximity 触发"""
    # current 10.96 / tp 11.00 → dist 0.00365 < 0.005
    positions = [_pos(current=10.96, stop=9.50, tp=11.00)]
    events = evaluate_alerts(positions, [], _cfg())
    types = [e.alert_type for e in events]
    assert "take_profit_proximity" in types


def test_portfolio_unrealized_floor_triggers():
    """组合浮亏 -6% < 阈值 -5% → portfolio_unrealized_floor 触发"""
    events = evaluate_alerts([], [_port(pnl=-0.06)], _cfg())
    assert len(events) == 1
    assert events[0].alert_type == "portfolio_unrealized_floor"
    assert events[0].severity == "critical"


def test_portfolio_peak_drawdown_triggers():
    """组合层 peak DD -8% < 阈值 -7% → portfolio_peak_drawdown 触发"""
    events = evaluate_alerts([], [_port(pnl=-0.02, dd=-0.08)], _cfg())
    assert len(events) == 1
    assert events[0].alert_type == "portfolio_peak_drawdown"


def test_disabled_when_enabled_false():
    """cfg.enabled=False → 即使全部阈值触发也不出 event"""
    positions = [_pos(current=9.51, stop=9.50)]  # 距止损 0.1%
    portfolios = [_port(pnl=-0.50, dd=-0.50)]
    cfg = _cfg(enabled=False)
    events = evaluate_alerts(positions, portfolios, cfg)
    assert events == []


def test_strategies_filter_applies():
    """cfg.strategies 非空 → 不在白名单内的策略被跳过"""
    positions = [
        _pos(symbol="601939", strategy="equity_factor", current=9.51, stop=9.50),
        _pos(symbol="600519", strategy="zhuang", current=99.50, stop=99.0),  # 距 stop 0.5% < 0.5%? 实际算 0.503
    ]
    cfg = _cfg(strategies=["equity_factor"])
    events = evaluate_alerts(positions, [], cfg)
    syms = [e.symbol for e in events]
    assert "600519" not in syms


# ── trading window ──────────────────────────────────────────────────

def test_in_trading_window_morning():
    cfg = _cfg()
    assert is_in_trading_window(datetime(2026, 6, 8, 10, 30), cfg) is True


def test_in_trading_window_afternoon():
    cfg = _cfg()
    assert is_in_trading_window(datetime(2026, 6, 8, 14, 0), cfg) is True


def test_outside_trading_window_lunch():
    cfg = _cfg()
    assert is_in_trading_window(datetime(2026, 6, 8, 12, 0), cfg) is False


def test_outside_trading_window_morning_pre_open():
    cfg = _cfg()
    assert is_in_trading_window(datetime(2026, 6, 8, 9, 0), cfg) is False


def test_outside_trading_window_weekend():
    cfg = _cfg()
    # 2026-06-06 是周六
    assert is_in_trading_window(datetime(2026, 6, 6, 10, 30), cfg) is False


# ── safety / math invariants ────────────────────────────────────────

def test_position_zero_price_safe():
    """current_price=0 → 不参与评估，不抛 div-by-zero"""
    positions = [_pos(current=0.0)]
    events = evaluate_alerts(positions, [], _cfg())
    assert events == []


def test_stop_loss_none_safe():
    """stop_loss=None → 不触发 stop_loss_proximity"""
    positions = [_pos(stop=None)]
    events = evaluate_alerts(positions, [], _cfg())
    types = [e.alert_type for e in events]
    assert "stop_loss_proximity" not in types


def test_negative_dist_to_stop_does_not_trigger_proximity():
    """current < stop（已破止损）→ proximity 不触发；PR1 新增 break_stop_loss 接管"""
    # current 9.40 / stop 9.50 → dist = -0.0106 < 0
    positions = [_pos(current=9.40, stop=9.50)]
    events = evaluate_alerts(positions, [], _cfg())
    types = [e.alert_type for e in events]
    assert "stop_loss_proximity" not in types
    assert "break_stop_loss" in types  # PR1: 替代触发


# ── from_yaml_dict roundtrip ────────────────────────────────────────

def test_from_yaml_dict_defaults():
    cfg = IntradayConfig.from_yaml_dict({})
    assert cfg.enabled is False
    assert cfg.poll_interval_minutes == 5  # PR1: 15→5
    assert cfg.proximity_to_stop_loss_pct == 0.005
    assert cfg.portfolio_drawdown_pct == -0.07


def test_from_yaml_dict_full():
    raw = {
        "enabled": True,
        "poll_interval_minutes": 5,
        "trading_window": {"a_share": {"start": "09:30", "end": "15:00"}},
        "triggers": {
            "proximity_to_stop_loss_pct": 0.003,
            "proximity_to_take_profit_pct": 0.004,
            "portfolio_unrealized_floor_pct": -0.06,
            "portfolio_drawdown_pct": -0.08,
            "strategies": ["equity_factor", "zhuang"],
        },
    }
    cfg = IntradayConfig.from_yaml_dict(raw)
    assert cfg.enabled is True
    assert cfg.poll_interval_minutes == 5
    assert cfg.proximity_to_stop_loss_pct == 0.003
    assert cfg.strategies == ["equity_factor", "zhuang"]


# ── Telegram sender contract ────────────────────────────────────────

def test_telegram_unconfigured_returns_false(monkeypatch):
    """未配 env → send 返 (False, '...not set'); 不抛错"""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    sender = TelegramSender()
    assert sender.configured is False
    ok, err = sender.send("hello")
    assert ok is False
    assert "not set" in err


def test_telegram_configured_reads_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    sender = TelegramSender()
    assert sender.configured is True


def test_telegram_explicit_args_override():
    sender = TelegramSender(bot_token="x", chat_id="y")
    assert sender.configured is True


# ── AlertEvent shape ────────────────────────────────────────────────

def test_alert_event_message_includes_threshold():
    """payload + message 含阈值数字 + 现价，便于 Telegram 可读 + 事后回放"""
    positions = [_pos(symbol="601939", current=9.55, stop=9.52)]
    events = evaluate_alerts(positions, [], _cfg())
    assert len(events) == 1
    ev = events[0]
    assert "601939" in ev.message
    assert "0.50%" in ev.message  # threshold
    assert ev.payload["threshold_pct"] == 0.005
    assert isinstance(ev, AlertEvent)


# ── PR1: break_stop_loss / break_ma60 ────────────────────────────────

def test_break_stop_loss_triggers_critical():
    """current < stop → break_stop_loss critical；不再触发 proximity"""
    positions = [_pos(symbol="601838", current=18.50, stop=18.79, tp=22.0)]
    events = evaluate_alerts(positions, [], _cfg())
    types = [e.alert_type for e in events]
    assert "break_stop_loss" in types
    assert "stop_loss_proximity" not in types
    ev = next(e for e in events if e.alert_type == "break_stop_loss")
    assert ev.severity == "critical"
    assert ev.payload["current_price"] == 18.50
    assert ev.payload["stop_loss"] == 18.79
    # breach_pct = (18.79 - 18.50) / 18.79 ≈ 0.01543
    assert abs(ev.payload["breach_pct"] - (18.79 - 18.50) / 18.79) < 1e-9
    assert "跌破止损" in ev.message
    assert "601838" in ev.message


def test_break_stop_loss_does_not_fire_when_above():
    """current ≥ stop → break_stop_loss 不触发"""
    positions = [_pos(current=10.00, stop=9.50)]
    events = evaluate_alerts(positions, [], _cfg())
    types = [e.alert_type for e in events]
    assert "break_stop_loss" not in types


def test_break_ma60_triggers_critical():
    """current < ma_long → break_ma60 critical"""
    # ma60=10.50, current=10.05 → breach (10.50-10.05)/10.50 ≈ 0.0429
    positions = [_pos(symbol="600519", current=10.05, stop=9.50, ma_long=10.50)]
    events = evaluate_alerts(positions, [], _cfg())
    types = [e.alert_type for e in events]
    assert "break_ma60" in types
    ev = next(e for e in events if e.alert_type == "break_ma60")
    assert ev.severity == "critical"
    assert ev.payload["ma_long"] == 10.50
    assert abs(ev.payload["breach_pct"] - (10.50 - 10.05) / 10.50) < 1e-9
    assert "MA60" in ev.message
    assert "600519" in ev.message


def test_break_ma60_does_not_fire_when_above_ma():
    """current ≥ ma_long → break_ma60 不触发"""
    positions = [_pos(current=11.00, stop=9.50, ma_long=10.50)]
    events = evaluate_alerts(positions, [], _cfg())
    types = [e.alert_type for e in events]
    assert "break_ma60" not in types


def test_break_ma60_skipped_when_ma_long_none():
    """ma_long=None（数据不足）→ break_ma60 不触发，不抛错"""
    positions = [_pos(current=9.00, stop=9.50, ma_long=None)]
    events = evaluate_alerts(positions, [], _cfg())
    types = [e.alert_type for e in events]
    assert "break_ma60" not in types


def test_break_stop_loss_and_break_ma60_can_coexist():
    """跌破 stop 同时跌破 ma60 → 两个 alert 都出"""
    positions = [_pos(current=9.00, stop=9.50, ma_long=10.50)]
    events = evaluate_alerts(positions, [], _cfg())
    types = [e.alert_type for e in events]
    assert "break_stop_loss" in types
    assert "break_ma60" in types


def test_from_yaml_dict_defaults_poll_5min():
    """PR1: poll_interval 默认 5（从 15 改）"""
    cfg = IntradayConfig.from_yaml_dict({})
    assert cfg.poll_interval_minutes == 5


# ── PR2: daily_screen_breakout / watchlist ───────────────────────────

import tempfile
from datetime import date as _date, timedelta as _td
from pathlib import Path as _Path

from quant_system.intraday.core import (
    BreakoutCandidateQuote,
    BreakoutConfig,
    evaluate_breakout_alerts,
)
from quant_system.intraday.watchlist import (
    Watchlist,
    WatchlistCandidate,
    dump_watchlist,
    load_watchlist,
    is_watchlist_stale,
)


def _bcfg(**overrides) -> BreakoutConfig:
    defaults = dict(
        enabled=True,
        breakout_margin=0.005,
        vol_ratio_min=1.2,
        watchlist_max_age_days=5,
        strategies=["equity_factor"],
    )
    defaults.update(overrides)
    return BreakoutConfig(**defaults)


def _bq(symbol="601939", name="建设银行", current=10.30, ref_high=10.15,
        vr=1.5, entry=10.10, sl=9.50, tp=11.00, strategy="equity_factor",
        market="a_share", score=0.6) -> BreakoutCandidateQuote:
    return BreakoutCandidateQuote(
        symbol=symbol, name=name, strategy_name=strategy, market=market,
        current_price=current, reference_high=ref_high, volume_ratio=vr,
        entry_price_suggested=entry, stop_loss_suggested=sl,
        take_profit_suggested=tp, factor_score=score,
    )


def test_breakout_triggers_warning():
    """current > ref_high × (1.005) + vol ≥ 1.2 → daily_screen_breakout warning"""
    events = evaluate_breakout_alerts([_bq()], _bcfg())
    assert len(events) == 1
    ev = events[0]
    assert ev.alert_type == "daily_screen_breakout"
    assert ev.severity == "warning"
    assert ev.symbol == "601939"
    assert ev.strategy_name == "equity_factor"
    assert ev.payload["breakout_pct"] > 0
    assert ev.payload["volume_ratio"] == 1.5
    assert "突破 T 日 high" in ev.message
    assert "非自动下单" in ev.message


def test_breakout_below_threshold_does_not_trigger():
    """current ≤ ref_high × (1+margin) → 不触发"""
    # current 10.16, ref_high 10.15, margin 0.005 → threshold 10.20075
    events = evaluate_breakout_alerts([_bq(current=10.16)], _bcfg())
    assert events == []


def test_breakout_low_vol_ratio_does_not_trigger():
    """量比 < vol_ratio_min → 不触发"""
    events = evaluate_breakout_alerts([_bq(vr=1.0)], _bcfg())
    assert events == []


def test_breakout_none_vol_ratio_still_triggers():
    """量比缺失 (akshare 字段没拿到) → 降级保守发 alert (不挡)"""
    events = evaluate_breakout_alerts([_bq(vr=None)], _bcfg())
    assert len(events) == 1
    assert events[0].payload["volume_ratio"] is None


def test_breakout_disabled_when_cfg_false():
    """breakout.enabled=false → 即使条件满足也不发"""
    events = evaluate_breakout_alerts([_bq()], _bcfg(enabled=False))
    assert events == []


def test_breakout_strategies_filter_applies():
    """strategies 白名单不含 zhuang → zhuang 候选股被跳过"""
    qs = [
        _bq(symbol="601939", strategy="equity_factor"),
        _bq(symbol="600519", strategy="zhuang"),
    ]
    events = evaluate_breakout_alerts(qs, _bcfg())
    syms = [e.symbol for e in events]
    assert "601939" in syms
    assert "600519" not in syms


def test_breakout_zero_price_safe():
    """current_price ≤ 0 / ref_high ≤ 0 → 不抛错，跳过"""
    qs = [_bq(current=0.0), _bq(symbol="X", ref_high=0.0)]
    events = evaluate_breakout_alerts(qs, _bcfg())
    assert events == []


# ── watchlist roundtrip + stale ─────────────────────────────────────

def test_watchlist_dump_load_roundtrip():
    wl = Watchlist(
        asof_date="2026-06-09",
        strategy="equity_factor",
        market="a_share",
        candidates=[
            WatchlistCandidate(
                symbol="601939", name="建设银行",
                reference_high=10.15, reference_close=10.10,
                entry_price_suggested=10.10, stop_loss_suggested=9.50,
                take_profit_suggested=11.00, factor_score=0.625,
                reasons=["MA60 OK", "RSI 58"],
            ),
        ],
    )
    with tempfile.TemporaryDirectory() as td:
        p = _Path(td) / "wl.json"
        dump_watchlist(wl, p)
        assert p.exists()
        wl2 = load_watchlist(p)
        assert wl2 is not None
        assert wl2.asof_date == "2026-06-09"
        assert wl2.strategy == "equity_factor"
        assert len(wl2.candidates) == 1
        assert wl2.candidates[0].symbol == "601939"
        assert wl2.candidates[0].reasons == ["MA60 OK", "RSI 58"]


def test_watchlist_load_missing_file_returns_none():
    p = _Path("/nonexistent/watchlist.json")
    assert load_watchlist(p) is None


def test_watchlist_stale_when_old():
    wl = Watchlist(
        asof_date="2026-06-01", strategy="equity_factor", market="a_share",
    )
    today = _date(2026, 6, 9)
    assert is_watchlist_stale(wl, today, max_age_days=5) is True


def test_watchlist_not_stale_when_recent():
    wl = Watchlist(
        asof_date="2026-06-08", strategy="equity_factor", market="a_share",
    )
    today = _date(2026, 6, 9)
    assert is_watchlist_stale(wl, today, max_age_days=5) is False


def test_watchlist_stale_when_unparseable_date():
    wl = Watchlist(asof_date="garbage", strategy="x", market="y")
    today = _date(2026, 6, 9)
    assert is_watchlist_stale(wl, today, max_age_days=5) is True


def test_breakout_config_from_yaml():
    raw = {
        "enabled": True,
        "breakout_margin": 0.008,
        "vol_ratio_min": 1.5,
        "watchlist_max_age_days": 3,
        "strategies": ["equity_factor", "zhuang"],
    }
    cfg = BreakoutConfig.from_yaml_dict(raw)
    assert cfg.enabled is True
    assert cfg.breakout_margin == 0.008
    assert cfg.vol_ratio_min == 1.5
    assert cfg.watchlist_max_age_days == 3
    assert cfg.strategies == ["equity_factor", "zhuang"]


def test_breakout_config_defaults():
    cfg = BreakoutConfig.from_yaml_dict({})
    assert cfg.enabled is False
    assert cfg.breakout_margin == 0.005
    assert cfg.vol_ratio_min == 1.2
    assert cfg.watchlist_max_age_days == 5
    assert cfg.strategies == ["equity_factor"]
