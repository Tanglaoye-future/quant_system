# Spec — L2: A_mom + HK_mom entry_features 采集

L2 of [[self_learning_pipeline]] roadmap. Backstop 1-5 全适用。

## 目标

让 `daily_equity.py` 在「自动开仓」步骤把 entry 时已算出的结构化特征
snapshot 到 `journal_trades.entry_features` JSONB（L1 已建列）。

## 严格 Backstop 实施

### Backstop #5 (采集 ≠ 新计算) — 实施方式
- **零修改 `signals.py`** — 不动 alpha 决策路径
- 在 `daily_equity.py` 自动开仓段（new_trades 循环内）, 对将开仓的 code
  **重新 `loader.get_daily` + `enrich`**, 从 today row 抽 numeric 字段
- enrich 是已有函数 (`timing.enrich` / hk 同款), 不引入新计算
- 每次自动开仓 ≤ 6 次重 enrich, 性能可忽略
- 失败时 entry_features = None (fail-soft), 不阻断开仓 (Backstop #5 严守: 采集
  失败永不影响 alpha 路径)

### Backstop #1 (17 条证伪硬墙) — 实施方式
- 采集字段限定在 timing.enrich 已计算的列: rsi / vol_ratio / ma_short /
  ma_long / atr / close / 20d high-low band
- 不引入新因子 / 新指标
- sector_sw1 留 None 占位 (akshare 申万行业需新数据访问, 不在 L2 范围)

## 改动范围

| 文件 | 改动 |
|---|---|
| `src/quant_system/strategies/equity_factor/journal/journal.py` | TradeOpen dataclass 加 `entry_features: Optional[dict] = None`; open_trade 写入 JournalTrade.entry_features |
| `src/quant_system/strategies/equity_factor/journal/__init__.py` | (如需) re-export |
| `scripts/daily/daily_equity.py` | 新增 helper `_build_entry_features_for_code(loader, market, code, asof, strategy)`; new_trades 循环里调用并传入 TradeOpen |
| `tests/equity_factor/test_journal.py` | 加 1 case: open_trade 传 entry_features dict → DB round-trip + 默认 None |
| `tests/equity_factor/test_daily_entry_features.py` | 新 fixture-style test: mock loader 返价格 df, 调 `_build_entry_features_for_code` 验返回 dict 结构 |

## entry_features dict 契约

```python
{
    # 数值化的 timing 信号 (从 today row 直读)
    "rsi": float,              # today["rsi"]
    "vol_ratio": float,        # today["volume"] / today["vol_ma"]
    "ma_short": float,         # today["ma_short"]
    "ma_long": float,          # today["ma_long"]
    "ma_short_above_long": bool,
    "atr": float,              # today["atr"]
    "close": float,            # = entry_price
    # 价格位置 (20d 区间)
    "dist_to_20d_high_pct": float,   # (close - 20d high) / 20d high; >=0 = 创新高
    "price_position_20d": float,     # (close - 20d low) / (20d high - 20d low); [0,1]
    # context
    "strategy": str,           # "equity_momentum" / "equity_hk_momentum"
    "market": str,             # "a_share" / "hk_share"
    "asof": str,               # "YYYY-MM-DD"
    # L2 不接入, 留 None 占位 (后续 PR / L5 报表时补)
    "sector_sw1": None,
    "zscore_within_universe": float,  # = entry_score (已有 hit.score)
}
```

NaN safe: 任何字段算出 NaN → 转 None (JSONB 不能存 NaN)。

## 验收

- `pytest tests/` 不回归 (base 288 → L2 后 ≥ 290)
- 既有 daily 路径行为零变化（entry_features 字段默认 None 时 daily 输出与 base
  完全一致；启用时 DB 多写一列 dict 不影响 reports/JSON）
- `verify_dualwrite` 全 OK
- 手动验：本地 daily 跑一次, journal_trades 最新 entry 行 entry_features 含 dict
  完整字段, NaN 字段为 None

## 不做（明文）

- 不接入 sector_sw1（需要 akshare 申万一级数据, 留未来 L2.1）
- 不动 `signals.py` 任何决策路径
- 不接入 mean_reversion 路径（A_mr by design 不自动开仓, L2 不覆盖）
- 不接入 zhuang（L3 单独）
- 不接入 exit_features（L4 单独）

## 关联

- [[self_learning_pipeline]] — 总路线
- [[feedback_harness_first_pr_split]] — 一 PR 一逻辑单元
