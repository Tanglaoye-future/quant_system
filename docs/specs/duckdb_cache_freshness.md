# Spec — DuckDB cache freshness check（M5）

## 背景（root cause）

实测 06-09 (周二): DuckDB `daily_bars` 表 600584 最新数据是 **06-04**, 已落后 4 个交易日 (周二 / 周三 / 周四 / 周五均无数据)。

实盘后果（实证）:
- daily_zhuang 06-08 显示 600584 close = **80.08 (6-4 cache 数据)**
- baostock 真实 06-08 close = **70.30 (-14.32%)**
- 距 stop 显示 "+3.82%" vs 真实 "-8.86%"
- distribution 信号触发但 turnover 用 6-4 (12.69)，6-8 真实 9.40 仍 > 6.0 OK
- pnl 报表 / portfolio_history / α 报表 (M2) **全部用过时价格** → 严重误判

Root cause: `ZhuangDataLoader.get_daily` (loader.py:341) / `EquityFactor DataLoader.get_daily` 优先级:
```
1. DuckDB store.has_code() 命中 → 直接返 cache  ← 不检查 cache 覆盖范围
2. CSV fresh check
3. baostock 远程
```

`has_code()` 一旦命中就用 cache, **永不 fall through 到 baostock refresh**。除非手工跑 prefetch script。

## 改动范围

| 文件 | 改动 |
|---|---|
| `src/quant_system/data/duckdb_store.py` | 加 `latest_date(market, code)` 方法返 cache 最新日期 (无数据返 None) |
| `src/quant_system/strategies/zhuang/data/loader.py` | `get_daily` 在 DuckDB hit path 前加 freshness check; cache `latest_date < end - skew_days` 时 fall through baostock |
| `src/quant_system/strategies/equity_factor/data/loader.py` | 同款 freshness check |
| `tests/data/test_duckdb_store_freshness.py` | 4 case: latest_date 正确性 / cache 新走 cache / cache 旧 fall through / cache 缺失 fall through |

## 设计

### freshness 阈值: `cache_stale_skew_days = 3`

- A 股周末 + 节假日, cache 偶尔会比 `end` 早 1-2 个交易日 (正常)
- 但 cache 早 ≥3 个交易日 → 强 fall through baostock
- 这是经验值: A 股两个连续假期之间最多 7-10 天, 但实盘 daily 每天跑 → 落后 3 天即异常

`skew_days` 可通过 loader 构造参数传入, 不动 yaml。

### 不破坏现有行为

- `refresh_days` 仍生效 (CSV cache freshness)
- baostock 拉到的新数据继续写 DuckDB (insert_daily)
- 仅"读 cache 前判断够不够新"是新增逻辑

### 不做

- 不强制每次 daily 跑都重拉 baostock (性能不可接受)
- 不动 backtest 路径 (回测用历史数据, cache freshness 无意义; 仅 hot-path daily 受影响)
- 不动 DuckDB 写入路径 (insert_daily 不变)

## Backstop 严守

- **#1** 不改 alpha 决策 (entry_signal / exit_signal 算法不动)
- **#5** 0 新计算 — 只是把 "用过时数据" 改成 "用真实数据"

## 验收

- pytest tests/ 不回归 (base 332 after M4, 但 M5 base 是 main 325)
- daily 重跑 dry-run: 600584 显示真实 6-8 close 70.30 (而非 cache 80.08)
- 既有 DuckDB cache (cache 新的情况) 性能零下降 (latest_date 是 fast index scan)

## 关联

- 06-08/09 conversation: 用户报 "持仓亏损", 真因是 cache stale 显示偏小亏损
- [[learn_l5_retrospective_report]] — α 报表用错价格的 root cause
- [[zhuang_stop_breach_alert]] (M4) — breach banner 等待 cache 修复才能正确显示
