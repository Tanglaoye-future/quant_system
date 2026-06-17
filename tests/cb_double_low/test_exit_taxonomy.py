"""PR11 — CB 双低 sleeve exit_taxonomy 单测 (2026-06-17).

CB 出场原因 → CB layer 映射. PR12 self_learning_pipeline winner-vs-loser 分桶按 layer 切片.
"""
from __future__ import annotations

import pytest

from quant_system.strategies.cb_double_low.journal.exit_taxonomy import (
    CB_LAYER_DELISTED,
    CB_LAYER_FORCE_REDEEM,
    CB_LAYER_OTHER,
    CB_LAYER_REBALANCE,
    CB_LAYER_SCORE_EXIT,
    CB_LAYER_STOP_LOSS,
    cb_exit_layer_from_reason,
)


@pytest.mark.parametrize("reason,expected", [
    # SCORE_EXIT — 慢出场, 估值贵
    ("score_over_180", CB_LAYER_SCORE_EXIT),
    ("dual_low_too_high", CB_LAYER_SCORE_EXIT),
    ("score_exit", CB_LAYER_SCORE_EXIT),
    # STOP_LOSS — 债底击穿
    ("stop_loss", CB_LAYER_STOP_LOSS),
    ("stop_loss_close", CB_LAYER_STOP_LOSS),
    ("stop_loss_85", CB_LAYER_STOP_LOSS),
    # FORCE_REDEEM — 强赎
    ("redeem_announced", CB_LAYER_FORCE_REDEEM),
    ("force_redeem", CB_LAYER_FORCE_REDEEM),
    ("cb_redeem_imminent", CB_LAYER_FORCE_REDEEM),
    ("forced_redeem_announced", CB_LAYER_FORCE_REDEEM),  # contains 'redeem'
    # REBALANCE — rank 漂移
    ("out_of_top_band", CB_LAYER_REBALANCE),
    ("rebalance", CB_LAYER_REBALANCE),
    ("rank_drop", CB_LAYER_REBALANCE),
    # DELISTED — 退市/被砍 filter
    ("out_of_universe", CB_LAYER_DELISTED),
    ("delisted", CB_LAYER_DELISTED),
    # OTHER fallback
    ("manual", CB_LAYER_OTHER),
    ("unknown_reason", CB_LAYER_OTHER),
    ("", CB_LAYER_OTHER),
])
def test_classify_cb_exit_reasons(reason: str, expected: str):
    assert cb_exit_layer_from_reason(reason) == expected


def test_case_insensitive_and_whitespace():
    assert cb_exit_layer_from_reason("  STOP_LOSS  ") == CB_LAYER_STOP_LOSS
    assert cb_exit_layer_from_reason("SCORE_OVER_180") == CB_LAYER_SCORE_EXIT


def test_none_safe():
    assert cb_exit_layer_from_reason(None) == CB_LAYER_OTHER  # type: ignore
