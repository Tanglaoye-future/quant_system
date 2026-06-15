"""持仓中日内做 T 信号 — 24 case 契约测试 (spec docs/specs/intraday_t_execution_a_share.md §7).

PR1 (本文件): tests 全部红灯 (TSignalConfig / TSignalEvent / evaluate_t_signals
未实现, ImportError).
PR2 (next): intraday/core.py 实现 evaluate_t_signals + intraday/vwap.py 新增
  → 24/24 全绿.

不变量验证 (spec §14):
- qty_ratio ∈ [0.2, 0.7]
- break_stop_loss 触发后 T 全面禁用
- BUY 必须当日已有 SELL
- strategy 白名单: equity_factor 三市场; zhuang / mean_reversion / HK / US skip
- enabled=False → 0 event
"""
from __future__ import annotations

from datetime import datetime, time

import pytest

from quant_system.intraday.core import (
    PositionSnapshot,
    TSignalConfig,
    TSignalEvent,
    evaluate_t_signals,
)


# ── fixtures ──────────────────────────────────────────────────────────

def _cfg(**overrides) -> TSignalConfig:
    defaults = dict(
        enabled=True,
        strategies=["equity_factor"],
        markets=["a_share"],
        trading_start=time(9, 30),
        trading_lunch_start=time(11, 30),
        trading_lunch_end=time(13, 0),
        trading_end=time(15, 0),
        skip_first_minutes=5,
        # 价格网格
        sell_unrealized_pct_min=0.05,
        buy_unrealized_pct_min=0.02,
        no_t_unrealized_pct_max=-0.03,
        qty_ratio_base=0.5,
        # VWAP
        vwap_enabled=True,
        vwap_sell_premium_pct=0.02,
        vwap_buy_discount_pct=0.015,
        vwap_qty_ratio_boost=0.2,
        # 量价
        vol_price_enabled=True,
        vol_price_sell_suppress_change_pct=0.04,
        vol_price_sell_suppress_vol_ratio=2.0,
        vol_price_sell_suppress_factor=0.7,
        vol_price_buy_boost_change_pct=-0.02,
        vol_price_buy_boost_vol_ratio=0.7,
        vol_price_buy_boost_factor=1.3,
        # clamp
        qty_ratio_min=0.2,
        qty_ratio_max=0.7,
        # 频率
        max_sells_per_day=1,
        max_buys_per_day=1,
    )
    defaults.update(overrides)
    return TSignalConfig(**defaults)


def _pos(symbol="601939", strategy="equity_factor", market="a_share",
         entry=10.0, current=10.60, stop=9.50, tp=11.0,
         vwap_today=None, day_change_pct=None,
         volume_ratio=None) -> PositionSnapshot:
    return PositionSnapshot(
        strategy_name=strategy, symbol=symbol, market=market,
        entry_price=entry, current_price=current,
        stop_loss=stop, take_profit=tp,
        vwap_today=vwap_today,
        day_change_pct=day_change_pct,
        volume_ratio=volume_ratio,
    )


def _asof_normal_trading():
    """正常交易时段, 远离开盘 / 午休 / 收盘的安全时间点."""
    return datetime(2026, 6, 15, 10, 30)  # 周一上午 10:30


# ── §7 价格网格 base layer ────────────────────────────────────────────

def test_t_signal_grid_sell_basic():
    """浮盈 +6%（无 VWAP / 无量价数据） → 1 SELL event, qty=0.5"""
    positions = [_pos(entry=10.0, current=10.60)]
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today={})
    assert len(events) == 1
    ev = events[0]
    assert ev.side == "SELL"
    assert ev.qty_ratio == pytest.approx(0.5, abs=1e-6)
    assert ev.symbol == "601939"
    assert "grid" in ev.reason.lower()


def test_t_signal_grid_no_sell_below_threshold():
    """浮盈 +4.9%（< 5% 阈值） → 0 event"""
    positions = [_pos(entry=10.0, current=10.49)]
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today={})
    assert events == []


def test_t_signal_grid_buy_requires_prior_sell():
    """浮盈 +3.5%, 当日无 SELL → 0 event (BUY 必须有前置 SELL)"""
    positions = [_pos(entry=10.0, current=10.35)]
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today={})
    assert events == []


def test_t_signal_grid_buy_after_sell():
    """浮盈 +3.5%, sent_today 含 t_signal_sell → 1 BUY event, qty=0.5"""
    positions = [_pos(entry=10.0, current=10.35)]
    sent = {("601939", "a_share"): ["t_signal_sell"]}
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today=sent)
    assert len(events) == 1
    ev = events[0]
    assert ev.side == "BUY"
    assert ev.qty_ratio == pytest.approx(0.5, abs=1e-6)


def test_t_signal_no_t_in_loss_zone():
    """浮亏 -3.5%（≤ -3%）→ 0 event"""
    positions = [_pos(entry=10.0, current=9.65)]
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today={})
    assert events == []


def test_t_signal_break_stop_disables():
    """浮盈 +6%, sent_today 含 break_stop_loss → 0 event (止损路径优先)"""
    positions = [_pos(entry=10.0, current=10.60)]
    sent = {("601939", "a_share"): ["break_stop_loss"]}
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today=sent)
    assert events == []


# ── §7 白名单过滤 ────────────────────────────────────────────────────

def test_t_signal_zhuang_strategy_skipped():
    """strategy_name='zhuang' → 0 event (zhuang 弃用)"""
    positions = [_pos(strategy="zhuang", entry=10.0, current=10.60)]
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today={})
    assert events == []


def test_t_signal_a_mr_strategy_skipped():
    """strategy_name='mean_reversion' → 0 event (A_mr by design 不做 T)"""
    positions = [_pos(strategy="mean_reversion", entry=10.0, current=10.60)]
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today={})
    assert events == []


def test_t_signal_non_a_share_skipped():
    """market='hk_share' → 0 event (PR1 only A 股)"""
    positions = [_pos(market="hk_share", entry=10.0, current=10.60)]
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today={})
    assert events == []


# ── §7 交易时段过滤 ────────────────────────────────────────────────

def test_t_signal_outside_trading_hours_skipped():
    """asof 12:00（午休段）→ 0 event"""
    positions = [_pos(entry=10.0, current=10.60)]
    asof = datetime(2026, 6, 15, 12, 0)
    events = evaluate_t_signals(positions, _cfg(), asof, sent_today={})
    assert events == []


def test_t_signal_first_5_min_skipped():
    """asof 09:33（开盘前 5 分钟内, skip_first_minutes=5）→ 0 event"""
    positions = [_pos(entry=10.0, current=10.60)]
    asof = datetime(2026, 6, 15, 9, 33)
    events = evaluate_t_signals(positions, _cfg(), asof, sent_today={})
    assert events == []


# ── §7 VWAP 偏离 boost ───────────────────────────────────────────────

def test_t_signal_vwap_premium_boost_sell():
    """SELL + 价 > VWAP × 1.02 → qty 0.5 + 0.2 = 0.7"""
    # entry=10, current=10.60 (浮盈 +6%); vwap=10.30; premium = 10.60/10.30 - 1 ≈ 0.029
    positions = [_pos(entry=10.0, current=10.60, vwap_today=10.30)]
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today={})
    assert len(events) == 1
    ev = events[0]
    assert ev.side == "SELL"
    assert ev.qty_ratio == pytest.approx(0.7, abs=1e-6)


def test_t_signal_vwap_discount_boost_buy():
    """BUY + 价 < VWAP × 0.985 → qty 0.5 + 0.2 = 0.7"""
    # entry=10, current=10.35 (浮盈 +3.5%); vwap=10.55; discount = 1 - 10.35/10.55 ≈ 0.019 > 0.015
    positions = [_pos(entry=10.0, current=10.35, vwap_today=10.55)]
    sent = {("601939", "a_share"): ["t_signal_sell"]}
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today=sent)
    assert len(events) == 1
    ev = events[0]
    assert ev.side == "BUY"
    assert ev.qty_ratio == pytest.approx(0.7, abs=1e-6)


def test_t_signal_vwap_missing_data_fail_soft():
    """SELL + vwap_today=None → qty 维持 base 0.5 (不报错不 boost)"""
    positions = [_pos(entry=10.0, current=10.60, vwap_today=None)]
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today={})
    assert len(events) == 1
    assert events[0].qty_ratio == pytest.approx(0.5, abs=1e-6)


# ── §7 量价 anti-distribution ────────────────────────────────────────

def test_t_signal_vol_price_suppress_sell():
    """SELL + day_change +5% + vol_ratio 2.5 → qty 0.5 × 0.7 = 0.35"""
    positions = [_pos(entry=10.0, current=10.60,
                      day_change_pct=0.05, volume_ratio=2.5)]
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today={})
    assert len(events) == 1
    ev = events[0]
    assert ev.side == "SELL"
    assert ev.qty_ratio == pytest.approx(0.35, abs=1e-6)


def test_t_signal_vol_price_boost_buy():
    """BUY (有前置 SELL) + day_change -3% + vol_ratio 0.5 → qty 0.5 × 1.3 = 0.65"""
    positions = [_pos(entry=10.0, current=10.35,
                      day_change_pct=-0.03, volume_ratio=0.5)]
    sent = {("601939", "a_share"): ["t_signal_sell"]}
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today=sent)
    assert len(events) == 1
    ev = events[0]
    assert ev.side == "BUY"
    assert ev.qty_ratio == pytest.approx(0.65, abs=1e-6)


def test_t_signal_vol_price_missing_data_fail_soft():
    """day_change=None vol_ratio=None → qty 不调整 (base 0.5)"""
    positions = [_pos(entry=10.0, current=10.60,
                      day_change_pct=None, volume_ratio=None)]
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today={})
    assert len(events) == 1
    assert events[0].qty_ratio == pytest.approx(0.5, abs=1e-6)


# ── §7 qty clamp 不变量 ─────────────────────────────────────────────

def test_t_signal_qty_clamp_min():
    """SELL + VWAP penalty + vol_price suppress 极端 → qty clamp 到 min 0.2

    base 0.5; vwap 在 -2% (没 boost, 因为 SELL 时只对 premium 加 boost);
    vol_price suppress ×0.7 → 0.35; 但我们用更极端的 factor 让它降到 0.2 以下
    """
    cfg = _cfg(vol_price_sell_suppress_factor=0.3)  # 0.5 × 0.3 = 0.15 < 0.2
    positions = [_pos(entry=10.0, current=10.60,
                      day_change_pct=0.05, volume_ratio=2.5)]
    events = evaluate_t_signals(positions, cfg, _asof_normal_trading(), sent_today={})
    assert len(events) == 1
    assert events[0].qty_ratio == pytest.approx(0.2, abs=1e-6)


def test_t_signal_qty_clamp_max():
    """BUY + VWAP boost + vol_price boost → qty 计算 (0.5+0.2)×1.3 = 0.91, clamp 到 max 0.7"""
    positions = [_pos(entry=10.0, current=10.35,
                      vwap_today=10.55,            # discount, BUY boost +0.2
                      day_change_pct=-0.03, volume_ratio=0.5)]  # ×1.3
    sent = {("601939", "a_share"): ["t_signal_sell"]}
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today=sent)
    assert len(events) == 1
    assert events[0].qty_ratio == pytest.approx(0.7, abs=1e-6)


# ── §7 频率上限 dedup ───────────────────────────────────────────────

def test_t_signal_dedup_max_1_sell_per_day():
    """sent_today 含 t_signal_sell + 浮盈 +7% → 0 event (同日 SELL 上限 1)"""
    positions = [_pos(entry=10.0, current=10.70)]
    sent = {("601939", "a_share"): ["t_signal_sell"]}
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today=sent)
    # 注意: 这里测的是"已发 SELL 后, 浮盈再涨 7% 不再发 SELL"
    # 但浮盈 +7% > +5% 是 SELL 区间, 不在 BUY 区间, 所以也不会触发 BUY
    sells = [e for e in events if e.side == "SELL"]
    assert sells == []


def test_t_signal_dedup_max_1_buy_per_day():
    """sent_today 含 t_signal_sell + t_signal_buy + 浮盈 +3% → 0 event (同日 BUY 上限 1)"""
    positions = [_pos(entry=10.0, current=10.30)]
    sent = {("601939", "a_share"): ["t_signal_sell", "t_signal_buy"]}
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today=sent)
    assert events == []


# ── §7 confidence 标签 ──────────────────────────────────────────────

def test_t_signal_confidence_high_all_three_align():
    """3 层同向 boost (grid SELL + VWAP premium + vol_price normal) → confidence='high'

    定义: 三层都触发或同向 → high; 两层 → medium; 仅 grid → low.
    SELL 同向 = grid 触发 SELL + VWAP premium 在 SELL 侧 + vol_price 未抑制 (即 normal).
    实现可能选择不同的定义; 此处测的是 "VWAP boost 且 vol_price 未抑制" → high.
    """
    positions = [_pos(entry=10.0, current=10.60,
                      vwap_today=10.30,            # premium > +2%
                      day_change_pct=0.01, volume_ratio=1.0)]  # 不触发 suppress
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today={})
    assert len(events) == 1
    assert events[0].confidence == "high"


def test_t_signal_confidence_medium_two_align():
    """grid + 1 boost layer → confidence='medium'"""
    # SELL + VWAP boost + vol_price 缺失数据
    positions = [_pos(entry=10.0, current=10.60,
                      vwap_today=10.30,
                      day_change_pct=None, volume_ratio=None)]
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today={})
    assert len(events) == 1
    assert events[0].confidence == "medium"


def test_t_signal_confidence_low_one_align():
    """仅 grid base → confidence='low'"""
    # SELL + 无 vwap + 无量价
    positions = [_pos(entry=10.0, current=10.60,
                      vwap_today=None,
                      day_change_pct=None, volume_ratio=None)]
    events = evaluate_t_signals(positions, _cfg(), _asof_normal_trading(), sent_today={})
    assert len(events) == 1
    assert events[0].confidence == "low"


# ── §7 yaml disabled 噤声 ──────────────────────────────────────────

def test_t_signal_disabled_yaml_noop():
    """cfg.enabled=False → 0 event 不报错"""
    cfg = _cfg(enabled=False)
    positions = [_pos(entry=10.0, current=10.60)]
    events = evaluate_t_signals(positions, cfg, _asof_normal_trading(), sent_today={})
    assert events == []
