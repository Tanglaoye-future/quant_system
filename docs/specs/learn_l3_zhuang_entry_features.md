# Spec — L3: zhuang entry_features 采集

L3 of [[self_learning_pipeline]]. Backstop 1-5 全适用。同款于 L2 (A_mom/HK_mom),
独立 PR — zhuang ledger 与 equity 完全隔离。

## 目标

让 `daily_zhuang.py` 自动建仓时 snapshot 结构化 entry 特征到
`zhuang_trades.entry_features` JSONB (L1 已建列)。

## Backstop #5 (采集 ≠ 新计算) 严守

zhuang 路径已有 `accumulation_score_detail(df)` 函数 (`signals/accumulation.py:194`),
返回 **5 维分量** + 5 个 score (0-100)：
- ma_convergence
- volume_asymmetry
- price_consolidation
- turnover_decline
- vp_divergence

daily_zhuang scan 段已经在 candidates 输出里用了它 — 复用即可，**零新计算**。

ATR / phase / market_trend / position_pct 都是 main() 路径已算的标量。

## entry_features dict 契约

```python
{
    # 5 维 accumulation 分量 (零新计算, 复用 accumulation_score_detail)
    "accumulation_ma_convergence": float,
    "accumulation_volume_asymmetry": float,
    "accumulation_price_consolidation": float,
    "accumulation_turnover_decline": float,
    "accumulation_vp_divergence": float,
    "accumulation_total": float,        # = sig.accumulation_score
    # 入场附属
    "phase": str,                       # "A" / "A+" / "B" / sig.phase
    "atr_at_entry": float,
    "entry_price": float,
    "position_pct": float,              # tiered sizing 实际仓位 (3%/5%/8% 等)
    # 市场层 context
    "market": str,                      # "a_share" / "hk_share" (L3 暂只 a_share)
    "market_trend_on": bool,            # CSI500 趋势门
    "asof": str,                        # "YYYY-MM-DD"
    # L3 不接入, 留 None 占位
    "market_cap_band": None,            # universe loader 当前 cap 区间未传到 daily 路径
    "industry_sw1": None,               # akshare 申万一级需新接入
}
```

NaN/Inf → None (JSONB 友好)。fail-soft: 异常返回 None, 不阻断 open_trade。

## 改动范围

| 文件 | 改动 |
|---|---|
| `src/quant_system/strategies/zhuang/journal/journal.py` | TradeOpen 加 `entry_features` 字段; open_trade 写入; _trade_row 暴露 entry/exit features |
| `scripts/daily/daily_zhuang.py` | 加 helper `_build_zhuang_entry_features(df, sig, atr_val, position_pct, market, asof, market_trend, acc_weights)`; new_trades 循环里调用并传给 TradeOpen |
| `tests/zhuang/test_journal.py` | +2 case (round-trip + 默认 NULL) |
| `tests/zhuang/test_daily_entry_features.py` | 新 fixture-style helper 契约测试 (2-3 case) |

## 验收

- `pytest tests/` 不回归 (base 293 → L3 后 ≥ 296)
- 既有 daily 路径行为零变化（不传 entry_features → DB NULL）
- 手动验：本地 daily_zhuang 跑一次, zhuang_trades 新行 entry_features 含 5 分量

## 不做（明文）

- 不接入 `market_cap_band` (loader filtered_universe 当前不带 cap, 需新链路传递)
- 不接入 `industry_sw1` (申万行业需 akshare 新数据, 留 L3.1)
- 不动 `signals/accumulation.py` / `signals/entry.py` (alpha 路径)
- 不接入 exit_features (L4)
- 不写 retrospective 报表 (L5)
- 不接入 zhuang.json / 前端展示 (L1 数据通道已具备, 前端在 L5 报表后再 expose)

## 关联

- [[self_learning_pipeline]] — 总路线
- [[learn_l2_equity_entry_features]] — equity 同款, 本 PR zhuang 对照实施
- `accumulation_score_detail` (`zhuang/signals/accumulation.py:194`) — 5 分量来源
