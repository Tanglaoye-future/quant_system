"""CB 双低 sleeve 出场原因分层 (PR11, 2026-06-17).

与 equity_factor.timing.exit_taxonomy 平行 — equity 出场体系 (trailing_stop / break_ma /
take_profit / overbought / time_stop / regime) 不对应 CB 的出场原因.

CB 出场原因映射 (源: cb_double_low/engine/strategy.py evaluate_holdings):
  - score_over_180 / dual_low_too_high  → SCORE_EXIT     (慢出场, 估值贵)
  - stop_loss / stop_loss_close         → STOP_LOSS      (债底击穿, 信用风险)
  - redeem_announced / force_redeem     → FORCE_REDEEM   (强赎执行)
  - out_of_top_band                     → REBALANCE      (rank 漂移月度换仓)
  - out_of_universe                     → DELISTED       (退市/被砍出 filter)
  - 其他 / manual                       → OTHER

self_learning_pipeline (PR12) winner-vs-loser 分桶用本 layer 字段:
  - SCORE_EXIT 通常是 winner (吃完 alpha 撤退)
  - STOP_LOSS 通常是 loser (债底失守)
  - FORCE_REDEEM 是 mixed (强赎 ≈ 100 元出场, 盈亏取决于持仓成本)
  - REBALANCE 是 neutral (常规换仓)
  - DELISTED 是 outlier (筛 filter)
"""
from __future__ import annotations

CB_LAYER_SCORE_EXIT = "SCORE_EXIT"
CB_LAYER_STOP_LOSS = "STOP_LOSS"
CB_LAYER_FORCE_REDEEM = "FORCE_REDEEM"
CB_LAYER_REBALANCE = "REBALANCE"
CB_LAYER_DELISTED = "DELISTED"
CB_LAYER_OTHER = "OTHER"


def cb_exit_layer_from_reason(reason: str) -> str:
    """由 evaluate_holdings / close_cb_trade 的 exit_reason 映射到 CB layer."""
    r = (reason or "").strip().lower()
    if r in ("score_over_180", "dual_low_too_high", "score_exit"):
        return CB_LAYER_SCORE_EXIT
    if r in ("stop_loss", "stop_loss_close", "stop_loss_85") or r.startswith("stop_loss"):
        return CB_LAYER_STOP_LOSS
    if r in ("redeem_announced", "force_redeem", "cb_redeem_imminent") or "redeem" in r:
        return CB_LAYER_FORCE_REDEEM
    if r in ("out_of_top_band", "rebalance", "rank_drop"):
        return CB_LAYER_REBALANCE
    if r in ("out_of_universe", "delisted"):
        return CB_LAYER_DELISTED
    return CB_LAYER_OTHER
