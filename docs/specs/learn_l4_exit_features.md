# Spec — L4: exit_features 采集 (equity + zhuang)

L4 of [[self_learning_pipeline]]. Backstop 1-5 全适用。

## 设计要点

不同于 L2/L3（外部组装 dict 传入），L4 选择 **close_trade 内部自动采集**：

理由:
- close_trade 调用方（RiskMonitor / daily_zhuang exit advisory / 各类 cleanup
  路径）极多, 给每个调用方加 5 行 build_features 代码不现实
- Journal own snapshots 表, 内部查 trade_id → snapshots 算 max DD/profit
  自然
- exit_type 用现成 `exit_layer_from_reason` (`timing/exit_taxonomy.py:19`),
  从 exit_reason 字符串解析 — 零新计算 (Backstop #5)
- close_trade API 不变 → 既有调用方零改动

## exit_features dict 契约

```python
{
    "exit_type": str,              # equity: exit_layer_from_reason(reason) →
                                   # STOP_TRAIL / STOP_TREND / TAKE_PROFIT /
                                   # TAKE_PROFIT_PARTIAL / OVERBOUGHT / TIME_STOP /
                                   # REGIME / FORCED_CLOSE / OTHER
                                   # zhuang: 自家解析 (distribution / momentum_stop /
                                   # trailing_stop / take_profit / time_stop / OTHER)
    "hold_days_bucket": str,       # "0-5" / "6-20" / "21-60" / "60+"
    "max_drawdown_during_hold_pct": float,  # min(snapshots.unrealized_pnl_pct), nullable
    "max_profit_during_hold_pct": float,    # max(snapshots.unrealized_pnl_pct), nullable
    "asof": str,                   # exit_date "YYYY-MM-DD"
}
```

NaN → None。fail-soft: 任何异常仍正常 close_trade, 仅 exit_features 留 None。

## Backstop #5 严守

- 仅 1 个新解析函数: zhuang `_zhuang_exit_layer(reason)` 极简 prefix match
  (与 equity exit_layer_from_reason 同款风格, 不引入新分类逻辑)
- max DD/profit 从已有 snapshots 表 (journal_snapshots / zhuang_snapshots)
  unrealized_pnl_pct 列 min/max — 零新计算
- hold_days_bucket 是已算 hold_days 的桶化, 不引入新指标

## Backstop #1 守墙

- exit_type 子类完全沿用 timing.exit_taxonomy 的 9 个 layer (LAYER_*),
  不引入新分类
- zhuang exit_layer 用 5 个已知 prefix (distribution / momentum_stop /
  trailing_stop / take_profit / time_stop), 来自 zhuang/signals/exit.py 已有
  reason 文案

## 改动范围

| 文件 | 改动 |
|---|---|
| `src/quant_system/strategies/equity_factor/journal/journal.py` | close_trade 内部 fail-soft 算 + 写 exit_features (用现成 exit_layer_from_reason) |
| `src/quant_system/strategies/zhuang/journal/journal.py` | 同款; 加 module-level `_zhuang_exit_layer` 极简 prefix match |
| `tests/equity_factor/test_journal.py` | +2 case (close_trade 后 exit_features 含 5 字段 + max DD/profit 计算正确) |
| `tests/zhuang/test_journal.py` | +2 case (同款 + zhuang distribution 子类正确) |

## 验收

- `pytest tests/` 不回归 (base 298 → L4 后 ≥ 302)
- close_trade API 签名不变, 既有调用方零改动
- close_trade 调用后 trade.exit_features 含 5 字段
- fail-soft: 无 snapshots / 异常 时 exit_features 仍写入 (max DD/profit = None)

## 不做（明文）

- 不改 close_trade API（不加 exit_features 参数 — 内部采集更干净）
- 不引入新 exit_type 分类（沿用 exit_taxonomy + zhuang 5 prefix）
- 不接入 mean_reversion exit（A_mr by design 不自动平仓）
- 不接入 options exit（持仓 v2 PR3 schema 不同）
- 不写 retrospective 报表（L5）

## 关联

- [[self_learning_pipeline]] — 总路线
- [[learn_l2_equity_entry_features]] / [[learn_l3_zhuang_entry_features]] — entry 同构 PR
- `exit_taxonomy.py` — equity exit_type 9 类来源
- `zhuang/signals/exit.py` — zhuang exit reason 5 prefix 来源
