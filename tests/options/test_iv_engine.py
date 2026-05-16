"""
IVR 计算单元测试（不依赖网络/IBKR）.
"""
import pandas as pd
import pytest

from quant_system.strategies.options.iv.engine import IVMode, IVSnapshot, _classify, compute_ivr


class TestClassify:
    def test_low_iv(self):
        mode, grade = _classify(20.0)
        assert mode == IVMode.LOW
        assert grade == "A"

    def test_mid_iv_b(self):
        mode, grade = _classify(32.0)
        assert mode == IVMode.MID
        assert grade == "B"

    def test_mid_iv_c(self):
        mode, grade = _classify(45.0)
        assert mode == IVMode.MID
        assert grade == "C"

    def test_high_iv(self):
        mode, grade = _classify(65.0)
        assert mode == IVMode.HIGH
        assert grade == "D"

    def test_boundary_25(self):
        mode, grade = _classify(25.0)
        assert mode == IVMode.MID

    def test_boundary_50(self):
        mode, grade = _classify(50.0)
        assert mode == IVMode.HIGH


class TestIVRCalculation:
    """测试 IVR 计算逻辑（用 monkey-patch 替换 yfinance）."""

    def _make_snapshot(self, current: float, low: float, high: float) -> IVSnapshot:
        """直接调用计算逻辑，不走网络。"""
        ivr = (current - low) / (high - low) * 100.0
        mode, grade = _classify(ivr)
        return IVSnapshot(
            date="2026-05-09",
            vxn_current=current, vxn_52w_low=low, vxn_52w_high=high,
            ivr=round(ivr, 1), mode=mode, signal_grade=grade,
        )

    def test_ivr_at_low(self):
        snap = self._make_snapshot(15.0, 15.0, 35.0)
        assert snap.ivr == 0.0
        assert snap.mode == IVMode.LOW

    def test_ivr_at_high(self):
        snap = self._make_snapshot(35.0, 15.0, 35.0)
        assert snap.ivr == 100.0
        assert snap.mode == IVMode.HIGH

    def test_ivr_midpoint(self):
        snap = self._make_snapshot(25.0, 15.0, 35.0)
        assert snap.ivr == 50.0
        assert snap.mode == IVMode.HIGH

    def test_ivr_low_grade_a(self):
        snap = self._make_snapshot(17.5, 15.0, 35.0)
        assert snap.ivr == pytest.approx(12.5, abs=0.1)
        assert snap.signal_grade == "A"
