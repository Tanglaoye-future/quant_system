"""SwingReversionStrategy 单测.

入场行为：
  - 过去 N 日 RSI 触底 (≤ rsi_dip_max) + 今日 RSI ≥ rsi_bounce_min_today
    + 今日 RSI ≥ 窗口最低 + rsi_bounce_pts + close > MA200 + 量 ≥ MA20
  - 任一不满足 → no hit

出场行为：
  - close ≤ stop_loss → atr_stop
  - close ≥ take_profit → atr_target
  - RSI ≥ rsi_exit_min → rsi_overbought
  - close < MA200 → break_ma
  - hold_days ≥ max_hold_days → time_stop
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import pytest

from quant_system.market import MarketContext
from quant_system.strategies.equity_factor.engine.strategy import (
    Position,
    SwingReversionConfig,
    SwingReversionStrategy,
)


# ---------- 测试用的轻量 loader stub ----------

@dataclass
class _StubLoader:
    """伪 DataLoader：只实现 SwingReversionStrategy 用到的两个接口."""
    df_by_code: dict[str, pd.DataFrame]

    def get_daily(self, market: str, code: str, start: str, end: str) -> pd.DataFrame:
        df = self.df_by_code.get(code)
        if df is None:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        m = (df["date"] >= start) & (df["date"] <= end)
        return df[m].reset_index(drop=True)


# ---------- 构造价格序列：长基线让 MA200/ATR 稳态，最后段控制 dip/bounce ----------

def _make_price_series(
    n: int = 260,
    base: float = 100.0,
    dip_close: Optional[float] = None,        # 倒数第 5 根的 close（控制 RSI 触底深度）
    bounce_close: Optional[float] = None,     # 最后一根的 close（控制 bounce）
    vol: int = 1_000_000,
    end_vol: Optional[int] = None,
) -> pd.DataFrame:
    rng = pd.date_range("2023-01-01", periods=n, freq="B")
    # 缓慢上行 + 噪音让 RSI 算得出来（纯单调上升 avg_loss=0 → RSI=NaN）
    rs = np.random.RandomState(42)
    drift = np.linspace(0.0, 2.0, n)
    noise = rs.normal(0.0, 0.4, n)
    close = base + drift + noise
    # 注入 dip：倒数第 5 根强回调
    if dip_close is not None:
        close[-5] = dip_close
        close[-4] = dip_close + 0.3
        close[-3] = dip_close + 0.6
        close[-2] = dip_close + 1.0
    if bounce_close is not None:
        close[-1] = bounce_close
    df = pd.DataFrame({
        "date": rng.strftime("%Y-%m-%d"),
        "open": close,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": [vol] * n,
    })
    if end_vol is not None:
        df.loc[df.index[-1], "volume"] = end_vol
    return df


# ---------- screen 入场测试 ----------

def _build_strategy(df: pd.DataFrame, cfg: Optional[SwingReversionConfig] = None) -> SwingReversionStrategy:
    loader = _StubLoader({"000001": df})
    ctx = MarketContext(name="a_share", universe_filter=None, industry_concentration=False)
    return SwingReversionStrategy(
        loader=loader, market="a_share",
        universe_codes=["000001"],
        cfg=cfg or SwingReversionConfig(),
        history_start="2023-01-01",
        market_ctx=ctx,
    )


def test_screen_no_dip_no_signal():
    """无回调 → 无 dip → 不发信号"""
    df = _make_price_series(dip_close=None, bounce_close=None)
    strat = _build_strategy(df)
    hits = strat.screen(date(2024, 12, 30))
    assert hits == []


def test_screen_dip_and_bounce_emits_signal():
    """RSI 显著 dip + 今日反弹 → 发信号 + 含 stop_loss / take_profit"""
    df = _make_price_series(base=100.0, dip_close=90.0, bounce_close=105.0)
    cfg = SwingReversionConfig(rsi_dip_max=40.0, rsi_bounce_min_today=50.0, rsi_bounce_pts=2.0)
    strat = _build_strategy(df, cfg)
    hits = strat.screen(date(2099, 12, 31))
    assert len(hits) == 1
    sig = hits[0]
    assert sig.symbol == "000001"
    assert sig.entry_price > 0
    assert sig.stop_loss is not None and sig.stop_loss < sig.entry_price
    assert sig.take_profit is not None and sig.take_profit > sig.entry_price
    assert "swing-rev" in sig.reasons["timing"]


def test_screen_under_ma200_blocked():
    """close ≤ MA200 → 长期趋势门挡住"""
    n = 260
    close = np.full(n, 100.0)
    close[-30:] = np.linspace(95.0, 70.0, 30)  # 一路向下，最后 close 远低于 MA
    df = pd.DataFrame({
        "date": pd.date_range("2023-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
        "open": close, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": [1_000_000] * n,
    })
    strat = _build_strategy(df)
    hits = strat.screen(date(2099, 12, 31))
    assert hits == []


def test_screen_volume_gate_blocks():
    """今日量 < MA20 → 量能门挡住"""
    df = _make_price_series(base=100.0, dip_close=85.0, bounce_close=92.0,
                            vol=1_000_000, end_vol=200_000)
    cfg = SwingReversionConfig(rsi_dip_max=40.0, rsi_bounce_min_today=40.0,
                               rsi_bounce_pts=2.0, vol_mult=1.0)
    strat = _build_strategy(df, cfg)
    hits = strat.screen(date(2099, 12, 31))
    assert hits == []


# ---------- evaluate 出场测试 ----------

def _position(entry_price: float, entry_date: date, stop: float, target: float) -> Position:
    return Position(
        symbol="000001", market="a_share",
        entry_date=entry_date, entry_price=entry_price,
        size=100, stop_loss=stop, take_profit=target,
    )


def test_evaluate_atr_target_hit():
    """close ≥ take_profit → atr_target 出场"""
    df = _make_price_series(base=100.0, dip_close=85.0, bounce_close=120.0)
    strat = _build_strategy(df)
    pos = _position(entry_price=92.0, entry_date=date(2024, 11, 1), stop=88.0, target=110.0)
    res = strat.evaluate(date(2099, 12, 31), pos) if False else strat.evaluate(pos, date(2099, 12, 31))
    assert res.action == "EXIT"
    assert res.reason.startswith("atr_target")


def test_evaluate_atr_stop_hit():
    """close ≤ stop_loss → atr_stop 出场"""
    df = _make_price_series(base=100.0, dip_close=85.0, bounce_close=80.0)
    strat = _build_strategy(df)
    pos = _position(entry_price=92.0, entry_date=date(2024, 11, 1), stop=85.0, target=110.0)
    res = strat.evaluate(pos, date(2099, 12, 31))
    assert res.action == "EXIT"
    assert res.reason.startswith("atr_stop")


def test_evaluate_time_stop_hit():
    """持有 ≥ max_hold_days → time_stop（close 需 > MA200 + < target + RSI < exit_min 避开其他出场）"""
    # close 维持 105（> MA200 ≈101），RSI 不到 70，target 给到 130 不命中，stop=85 不命中 → 只剩 time_stop
    df = _make_price_series(base=100.0, dip_close=90.0, bounce_close=105.0)
    cfg = SwingReversionConfig(max_hold_days=10)
    strat = _build_strategy(df, cfg)
    pos = _position(entry_price=104.0, entry_date=date(2024, 11, 1), stop=85.0, target=130.0)
    res = strat.evaluate(pos, date(2099, 12, 31))
    assert res.action == "EXIT"
    assert res.reason.startswith("time_stop")


# ---------- v2: MA200 buffer + 斜率 + grace period ----------

def test_v2_ma_buffer_blocks_thin_bounce():
    """v2: bounce_close 略高于 MA200 (e.g. close 102, MA 101) 但 buffer=3% 要求 close>104 → 挡住"""
    df = _make_price_series(base=100.0, dip_close=90.0, bounce_close=102.0)
    # v1: buffer=0 应该过 (close 102 > MA 101)；v2: buffer=0.03 要求 > 101*1.03=104 → 挡住
    cfg_v1 = SwingReversionConfig(
        rsi_dip_max=40.0, rsi_bounce_min_today=45.0, rsi_bounce_pts=2.0,
        ma_long_buffer_pct=0.0,
    )
    cfg_v2 = SwingReversionConfig(
        rsi_dip_max=40.0, rsi_bounce_min_today=45.0, rsi_bounce_pts=2.0,
        ma_long_buffer_pct=0.03,
    )
    strat_v1 = _build_strategy(df, cfg_v1)
    strat_v2 = _build_strategy(df, cfg_v2)
    hits_v1 = strat_v1.screen(date(2099, 12, 31))
    hits_v2 = strat_v2.screen(date(2099, 12, 31))
    # v1 应该有信号；v2 应该被 buffer 挡住
    assert len(hits_v1) == 1, f"v1 baseline 应该有信号，实际 {len(hits_v1)}"
    assert len(hits_v2) == 0, f"v2 buffer=0.03 应该挡住贴 MA200 的弱反弹"


def test_v2_ma_slope_blocks_downtrend():
    """v2: MA200 在下降 (vs 20d ago) → 斜率门挡住"""
    # 构造一个 MA200 下降的序列：前段高、后段持续下行
    n = 260
    rs = np.random.RandomState(42)
    close = np.full(n, 0.0)
    close[:130] = 110.0 + rs.normal(0, 0.5, 130)
    close[130:] = np.linspace(110.0, 95.0, n - 130) + rs.normal(0, 0.5, n - 130)
    # 末段注入 dip + bounce
    close[-5] = 88.0
    close[-4] = 89.0
    close[-3] = 90.0
    close[-2] = 91.0
    close[-1] = 100.0  # bounce 上去，但 MA200 在下行
    df = pd.DataFrame({
        "date": pd.date_range("2023-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
        "open": close, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": [1_000_000] * n,
    })
    cfg = SwingReversionConfig(
        rsi_dip_max=40.0, rsi_bounce_min_today=40.0, rsi_bounce_pts=2.0,
        ma_long_buffer_pct=0.0,
        ma_long_slope_enabled=True, ma_long_slope_lookback=20,
    )
    strat = _build_strategy(df, cfg)
    hits = strat.screen(date(2099, 12, 31))
    assert hits == [], "MA200 下行应该被斜率门挡住"


def test_v2_break_ma_grace_holds_single_day_dip():
    """v2: grace_days=3 时单日 close<MA 不出场 (HOLD)"""
    # 构造序列：close 一直 > MA，仅最后一天 close < MA
    n = 260
    base = 100.0
    rs = np.random.RandomState(42)
    close = base + np.linspace(0, 5, n) + rs.normal(0, 0.3, n)
    # 单日下穿：最后 1 天 close 远低于 MA
    close[-1] = 95.0  # MA200 大约 102；单日跌 5%，但前一天还 > MA
    df = pd.DataFrame({
        "date": pd.date_range("2023-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
        "open": close, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": [1_000_000] * n,
    })
    cfg = SwingReversionConfig(break_ma_grace_days=3)
    strat = _build_strategy(df, cfg)
    pos = _position(entry_price=100.0, entry_date=date(2024, 11, 1), stop=80.0, target=130.0)
    res = strat.evaluate(pos, date(2099, 12, 31))
    # 单日 break 不应触发 EXIT — 应该是 HOLD 或 time_stop (取决于持有天数)
    # 但不应该是 break_ma
    assert not res.reason.startswith("break_ma"), \
        f"grace=3 单日下穿不应砍，实际 reason={res.reason}"
