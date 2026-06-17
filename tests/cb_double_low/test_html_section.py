"""PR11 — CB HTML report section 渲染单测 (2026-06-17).

不验证 HTML 完整结构, 只验证:
  - cb=None / _missing → section 为空
  - 有 cb 数据 → section 含 CB-specific 关键字符串 (mode / target_pct / HOLD/SELL/BUY)
  - 空 closed (advisory_only) → 显示 "本月暂无 closed trades"
  - 异常输入不挂 (fail-soft)
"""
from __future__ import annotations

import pytest

from quant_system.report.builder import _render_cb_section


def _sample_cb_payload() -> dict:
    """模拟 quant_cb.json (PR9 schema)."""
    return {
        "date": "2026-06-17",
        "asof_panel": "2026-06-17",
        "strategy": "cb_double_low",
        "market": "a_share",
        "advisory_only": True,
        "config": {
            "n_entry": 20,
            "exit_dual_low_threshold": 180.0,
            "stop_loss_close": 85.0,
            "min_conversion_premium": -5.0,
            "target_pct": 0.05,
            "source": "A_mom",
        },
        "universe": {"total": 1013, "active": 945, "panel_coverage": 3,
                     "panel_coverage_pct": 0.003},
        "entries_top": [
            {"rank": 1, "bond_code": "123198", "bond_name": "金埔转债",
             "close": 109.93, "conversion_premium_rate": -3.49,
             "dual_low_score": 106.44, "warn_redeem_near": False},
            {"rank": 2, "bond_code": "123271", "bond_name": "通合转债",
             "close": 157.30, "conversion_premium_rate": 47.85,
             "dual_low_score": 205.15, "warn_redeem_near": False},
        ],
        "warn_redeem_near": [],
        "current_holdings": [],
        "rebalance": {
            "mode": "maintenance",
            "hold": [], "sell": [], "buy": [],
            "diff_summary": {"n_hold": 0, "n_sell": 0, "n_sell_urgent": 0,
                             "n_buy": 2, "n_buy_deferred": 2},
        },
    }


def test_render_cb_section_with_data():
    html = _render_cb_section(_sample_cb_payload())
    # 关键字符串都在
    assert "cb_double_low" in html
    assert "maintenance" in html
    assert "5%" in html  # target_pct
    assert "A_mom" in html  # source
    assert "金埔转债" in html  # entries_top
    assert "123198" in html
    assert "0 / 0 / 2" in html  # HOLD / SELL / BUY
    # advisory_only 期 closed 表为空
    assert "本月暂无 closed trades" in html
    # 4 支柱 status 注释
    assert "支柱 3" in html


def test_render_cb_section_missing_returns_empty():
    assert _render_cb_section({"_missing": True, "system": "quant_cb"}) == ""


def test_render_cb_section_with_empty_entries():
    """panel 数据滞后 / 无候选 → 显示 placeholder 而非空表."""
    payload = _sample_cb_payload()
    payload["entries_top"] = []
    html = _render_cb_section(payload)
    assert "暂无候选" in html


def test_render_cb_section_no_rebalance_field():
    """旧 quant_cb.json (PR7/PR8 期, 没有 rebalance 字段) 也能渲染."""
    payload = _sample_cb_payload()
    payload.pop("rebalance", None)
    html = _render_cb_section(payload)
    # mode 退化 — 没 rebalance 时 mode='—'
    assert "—" in html
    assert "金埔转债" in html  # entries_top 仍渲染


def test_render_cb_section_with_warn_redeem():
    """强赎临近债 → warn count 显示 + entries_top 标 '⚠强赎临近'."""
    payload = _sample_cb_payload()
    payload["warn_redeem_near"] = ["123198"]
    payload["entries_top"][0]["warn_redeem_near"] = True
    html = _render_cb_section(payload)
    assert "⚠强赎临近" in html
