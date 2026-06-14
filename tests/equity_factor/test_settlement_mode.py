"""settlement_mode (T+0 / T+1) 市场独立化测试.

Spec: docs/specs/market_settlement_t0_t1.md

覆盖：
  1. yaml 装配 — a_share=t+1; hk_share/us_share=t+0
  2. MarketContext 默认兜底 (a_share→t+1, 其他→t+0)
  3. MarketContext 非法 settlement_mode raises ValueError
  4. Backtester 默认 settlement_mode=="t+1" (向下兼容)
  5. Backtester 非法 settlement_mode raises ValueError
  6. T+1 模式下 Step 3 evaluate 跳过入场当日仓 (A 股语义)
  7. T+0 模式下 Step 3 evaluate 不跳过入场当日仓 (HK / US 语义)
"""
from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from quant_system.config import load_config
from quant_system.market import MarketContext, load_market_context
from quant_system.strategies.equity_factor.engine.backtest import Backtester
from quant_system.strategies.equity_factor.engine.strategy import (
    BuySignal, ExitSignal, Position,
)


# ---------------------------------------------------------------------------
# 1. yaml 装配 + MarketContext 兜底契约
# ---------------------------------------------------------------------------

class TestMarketContextSettlement:
    @pytest.fixture
    def cfg(self):
        return load_config()

    def test_a_share_yaml_t1(self, cfg):
        ctx = load_market_context(cfg, "a_share")
        assert ctx.settlement_mode == "t+1"

    def test_hk_share_yaml_t0(self, cfg):
        ctx = load_market_context(cfg, "hk_share")
        assert ctx.settlement_mode == "t+0"

    def test_us_share_yaml_t0(self, cfg):
        ctx = load_market_context(cfg, "us_share")
        assert ctx.settlement_mode == "t+0"

    def test_dataclass_default_is_t1(self):
        # 不传 settlement_mode 时默认 t+1（兼容旧代码直接构造 MarketContext）
        ctx = MarketContext(name="a_share", universe_filter="a_share",
                            industry_concentration=True)
        assert ctx.settlement_mode == "t+1"

    def test_load_market_context_unknown_market_default_t0(self):
        # 自定义 cfg：没有 settlement_mode 字段, 非 a_share 兜底 t+0
        fake_cfg = SimpleNamespace(get=lambda *a, **kw: {} if a[0] == "markets" else None)
        ctx = load_market_context(fake_cfg, "hk_share")
        assert ctx.settlement_mode == "t+0"

    def test_load_market_context_unknown_market_a_share_default_t1(self):
        fake_cfg = SimpleNamespace(get=lambda *a, **kw: {} if a[0] == "markets" else None)
        ctx = load_market_context(fake_cfg, "a_share")
        assert ctx.settlement_mode == "t+1"

    def test_load_market_context_invalid_settlement_raises(self):
        # 假装某市场 yaml 写了 settlement_mode: t+2
        fake_cfg = SimpleNamespace(
            get=lambda *a, **kw: {"settlement_mode": "t+2"} if a[0] == "markets" else None,
        )
        with pytest.raises(ValueError, match="settlement_mode 非法"):
            load_market_context(fake_cfg, "hk_share")


# ---------------------------------------------------------------------------
# 2. Backtester 构造期参数校验
# ---------------------------------------------------------------------------

class TestBacktesterSettlementInit:
    def test_default_settlement_is_t1(self):
        bt = Backtester(loader=MagicMock())
        assert bt.settlement_mode == "t+1"

    def test_explicit_t0_accepted(self):
        bt = Backtester(loader=MagicMock(), settlement_mode="t+0")
        assert bt.settlement_mode == "t+0"

    def test_explicit_t1_accepted(self):
        bt = Backtester(loader=MagicMock(), settlement_mode="t+1")
        assert bt.settlement_mode == "t+1"

    def test_case_insensitive(self):
        bt = Backtester(loader=MagicMock(), settlement_mode="T+0")
        assert bt.settlement_mode == "t+0"

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="settlement_mode 非法"):
            Backtester(loader=MagicMock(), settlement_mode="t+3")


# ---------------------------------------------------------------------------
# 3. Step 3 evaluate 行为差异（核心 settlement 语义）
# ---------------------------------------------------------------------------

def _make_loader_with_simple_universe(n_days: int = 32):
    """构造 minimal loader：n_days (>=30) 交易日 + 1 只股 + 基准.

    Backtester 校验交易日 >= 30, 取 n_days=32 留余量.
    第 0 天 screen 触发, 第 1 天 D+1 open 入场, entry_date=day1.
    Step 3 evaluate(pos, day1):
      - T+1: 跳过 (entry_date == day1)
      - T+0: 调用一次
    后续每日都被 evaluate.
    """
    loader = MagicMock()
    start_dt = datetime(2026, 6, 1).date()
    # 简化：直接用日历日（基准只用作日期索引；周末/节假日不影响逻辑）
    days = [(start_dt + pd.Timedelta(days=i)).isoformat() for i in range(n_days)]

    # 基准（用作交易日历）
    bench_df = pd.DataFrame({
        "date": days,
        "open": [100.0] * n_days,
        "high": [101.0] * n_days,
        "low": [99.0] * n_days,
        "close": [100.0] * n_days,
    })
    loader.get_index_daily = MagicMock(return_value=bench_df)

    # 个股 OHLC（恒定价 10.0，避免 stop_loss=9.0 / take_profit=12.0 触发出场）
    stock_df = pd.DataFrame({
        "date": days,
        "open": [10.0] * n_days,
        "high": [10.5] * n_days,
        "low": [9.5] * n_days,
        "close": [10.0] * n_days,
    })
    loader.get_daily = MagicMock(return_value=stock_df)
    return loader, days


class _SignalOnceStrategy:
    """day0 screen() 返回 1 个 signal；之后 screen 返回空.

    每次 evaluate 被调用就累加 calls；用以验证 Step 3 是否在入场当日触发评估。
    """
    name = "test_strategy"

    def __init__(self):
        self.evaluate_calls: list[tuple[str, str]] = []  # (date, symbol)
        self.screen_called_days: list[str] = []
        self.m4_cfg = None
        self.market_ctx = None

    SIGNAL_DAY = "2026-06-01"

    def screen(self, asof):
        self.screen_called_days.append(asof.isoformat())
        if asof.isoformat() == self.SIGNAL_DAY:
            return [BuySignal(
                symbol="TEST",
                market="hk_share",
                score=1.0,
                entry_price=10.0,
                stop_loss=9.0,
                take_profit=12.0,
            )]
        return []

    def evaluate(self, position: Position, asof):
        self.evaluate_calls.append((asof.isoformat(), position.symbol))
        # 一律 HOLD（不触发出场），仅用以验证调用 vs 跳过
        return ExitSignal(action="HOLD")


def _run_minimal_backtest(settlement_mode: str):
    loader, days = _make_loader_with_simple_universe()
    bt = Backtester(
        loader=loader,
        initial_capital=100_000.0,
        max_positions=1,
        single_position_pct=0.5,
        commission=0.0,
        stamp_tax=0.0,
        slippage=0.0,
        cash_buffer_pct=0.0,
        settlement_mode=settlement_mode,
    )
    strat = _SignalOnceStrategy()
    bt.run(strat, start=days[0], end=days[-1], market="hk_share",
           benchmark_symbol="HSCHK100", verbose=False)
    return strat


class TestStepThreeBehaviour:
    """T+0 vs T+1 在 Step 3 evaluate 调用次数上的可观察差异.

    序列：
      day0 (2026-06-01): screen 触发, pending_buy 入队
      day1 (2026-06-02): D+1 open 入场, entry_date=day1
                        Step 3 evaluate(pos, day1):
                          - T+1: 跳过 (entry_date == day1)
                          - T+0: 调用一次
      day2 (2026-06-03): Step 3 evaluate(pos, day2) — 两模式都调用
      day3 (2026-06-04): Step 3 evaluate(pos, day3) — 两模式都调用 (末日强平前)
    """

    ENTRY_DAY = "2026-06-02"  # signal day0=06-01 → D+1 open 入场 = 06-02

    def test_t0_evaluates_on_entry_day(self):
        strat = _run_minimal_backtest(settlement_mode="t+0")
        eval_dates = [d for d, _ in strat.evaluate_calls]
        assert self.ENTRY_DAY in eval_dates, (
            f"T+0 入场当日 evaluate 必须触发；实际 evaluate 日期: {eval_dates}"
        )

    def test_t1_skips_entry_day(self):
        strat = _run_minimal_backtest(settlement_mode="t+1")
        eval_dates = [d for d, _ in strat.evaluate_calls]
        assert self.ENTRY_DAY not in eval_dates, (
            f"T+1 入场当日 evaluate 必须跳过；实际 evaluate 日期: {eval_dates}"
        )

    def test_t0_evaluates_more_than_t1(self):
        """T+0 evaluate 调用次数 = T+1 + 1 (多出入场当日一次)."""
        t0 = _run_minimal_backtest(settlement_mode="t+0")
        t1 = _run_minimal_backtest(settlement_mode="t+1")
        assert len(t0.evaluate_calls) == len(t1.evaluate_calls) + 1, (
            f"T+0 应比 T+1 多 1 次 evaluate；实际 t0={len(t0.evaluate_calls)} "
            f"t1={len(t1.evaluate_calls)}"
        )
