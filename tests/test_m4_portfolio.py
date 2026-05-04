"""M4 组合重排：行业上限与风险预算。"""
from __future__ import annotations

from dataclasses import dataclass

from quant_system.bottomup.portfolio import M4Config, m4_prioritize_signals
from quant_system.engine.strategy import BuySignal


@dataclass
class _MockLoader:
    mapping: dict[str, str]

    def get_a_share_industry_map(self) -> dict[str, str]:
        return self.mapping


def _sig(sym: str, ep: float = 10.0, sl: float = 9.0) -> BuySignal:
    return BuySignal(
        symbol=sym, market="a_share", score=1.0,
        entry_price=ep, stop_loss=sl, take_profit=11.0, reasons={},
    )


def test_m4_disabled_returns_original_order():
    sigs = [_sig("000001"), _sig("000002")]
    out = m4_prioritize_signals(
        sigs, {}, [], 1, _MockLoader({}), "a_share", "2026-01-01", M4Config(m4_enabled=False),
    )
    assert out == sigs


def test_industry_cap_promotes_diverse_first():
    loader = _MockLoader({"A": "银行", "B": "银行", "C": "钢铁", "D": "钢铁"})
    sigs = [_sig("A"), _sig("B"), _sig("C")]
    cfg = M4Config(m4_enabled=True, m4_max_same_industry=1, m4_new_risk_budget_frac=0.0)
    out = m4_prioritize_signals(sigs, {}, [], 2, loader, "a_share", "2026-01-01", cfg)
    assert out[0].symbol == "A"
    assert {out[0].symbol, out[1].symbol} == {"A", "C"}


def test_risk_budget_reorders_when_third_exceeds_cumulative():
    loader = _MockLoader({})
    sigs = [_sig("A", 100, 90), _sig("B", 100, 90), _sig("C", 100, 90)]
    cfg = M4Config(m4_enabled=True, m4_max_same_industry=0, m4_new_risk_budget_frac=0.25)
    out = m4_prioritize_signals(sigs, {}, [], 3, loader, "a_share", "2026-01-01", cfg)
    assert out[0].symbol == "A"
    assert out[1].symbol == "B"
    assert out[2].symbol == "C"
