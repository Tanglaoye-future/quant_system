"""M4 of zhuang_stop_breach_alert — 三级状态识别契约测试.

实盘 06-08 600584 case 教训: dist < 0 (已跌穿) 与 dist < 1% (临界) 必须
显示为完全不同的告警级别, 防 PM 8 天没注意到 stop loss 被穿掉。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SPEC_PATH = Path(__file__).resolve().parents[2] / "scripts" / "daily" / "daily_zhuang.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("_dz_stop_breach_test", SPEC_PATH)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_dz_stop_breach_test"] = m
    spec.loader.exec_module(m)
    return m


# ── 三级状态识别 ──────────────────────────────────────────────────────────────

def test_stop_state_breached_negative_dist(mod):
    """dist < 0 → breached (600584 实盘 case: -8.86%)."""
    assert mod.stop_state(-0.0886) == "breached"
    assert mod.stop_state(-0.001) == "breached"  # 边界: 跌穿一点点
    assert mod.stop_state(-0.5) == "breached"


def test_stop_state_critical_under_1_percent(mod):
    """0 <= dist < critical_margin → critical."""
    assert mod.stop_state(0.0) == "critical"  # 边界: 刚到 stop (未跌穿)
    assert mod.stop_state(0.005) == "critical"
    assert mod.stop_state(0.0099) == "critical"


def test_stop_state_normal_above_margin(mod):
    assert mod.stop_state(0.01) == "normal"    # 边界: 恰好等于 margin
    assert mod.stop_state(0.034) == "normal"   # 600655 实盘
    assert mod.stop_state(0.50) == "normal"


def test_stop_state_unknown_when_none(mod):
    """data 缺失 (无行情/停牌) → unknown 不抛."""
    assert mod.stop_state(None) == "unknown"


def test_stop_state_custom_margin(mod):
    """允许调用方传不同 critical_margin (与 daily 配置一致)."""
    assert mod.stop_state(0.015, critical_margin=0.02) == "critical"
    assert mod.stop_state(0.025, critical_margin=0.02) == "normal"


# ── 600584 case regression ────────────────────────────────────────────────────

def test_real_case_600584_breached_896_pct(mod):
    """实盘 06-08 600584 case: dist = -8.86% 必须识别为 breached."""
    assert mod.stop_state(-0.0886) == "breached"


def test_real_case_600655_normal(mod):
    """600655 实盘 dist +3.4% 仍 normal."""
    assert mod.stop_state(0.034) == "normal"
