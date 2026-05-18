---
name: DuckDB 数据层迁移 2026-05
description: 统一日线数据从 CSV/parquet 分散缓存迁移到单文件 DuckDB，loader 改 DB-first + 灾备 fallback
type: project
---

## 动机

迁移前数据散在 3 处：
- `data/prices/{code}_daily.csv` — zhuang A 股全市场 (3270 文件, 291MB)
- `data/cache/daily_{market}_{code}.parquet` — equity_factor (303 文件, A/HK/US)
- `data/hk_prices/{code}.csv`, `data/us_prices/{ticker}.csv` — equity_factor 原始 (51+101 文件)

问题：
1. 跨股票查询必须遍历所有文件（"找 2026-05 turnover>2 的股票"无法做）
2. 冷启动加载慢（zhuang 3270 CSV 首次 4min）
3. 多种 schema 重复（CSV 与 parquet 列略有差异）

## 设计

**单表 daily_bars**：

```sql
CREATE TABLE daily_bars (
    market  VARCHAR NOT NULL,    -- 'a_share' | 'hk_share' | 'us_share'
    code    VARCHAR NOT NULL,
    date    DATE NOT NULL,
    open    DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
    volume  DOUBLE,
    turnover_rate DOUBLE,        -- nullable (仅 zhuang/BaoStock 数据源有)
    PRIMARY KEY (market, code, date)
)
```

文件位置：`data/quant.duckdb`（gitignored）

## API

`quant_system.data.DuckDBStore`：
- `insert_daily(market, code, df, replace=True)` — 单股票写入
- `bulk_insert_daily(market, df, replace)` — 批量写入（多 code 在一个 df 里）
- `get_daily(market, code, start, end) -> DataFrame` — 单股票切片
- `has_code(market, code) -> bool`
- `list_codes(market)`, `stats()`

进程级单例：`get_default_store(db_path)`。

## Loader 改造

两个 loader 都改为 **DuckDB-first → CSV/parquet fallback → 远程拉取** 三级路径：

| Loader | 文件 | DuckDB 命中返回 | Fallback |
|---|---|---|---|
| `ZhuangDataLoader.get_daily` | `src/.../zhuang/data/loader.py` | date=datetime64, 含 turnover_rate | `data/prices/*.csv` → BaoStock |
| `equity_factor.DataLoader.get_daily` | `src/.../equity_factor/data/loader.py` | date 字符串（下游兼容）, 不含 turnover_rate | parquet 缓存 → akshare |

equity_factor 仅 `price_adjust='qfq'` 时启用 DuckDB（其他 adjust 模式走原 parquet 避免混淆）。

新拉取的数据 **同时**写入 DuckDB + CSV/parquet，DB 永远跟得上灾备数据。

## 迁移结果

`scripts/migration/import_to_duckdb.py --rebuild` 一次性导入，**8 秒** 完成：

| Market | rows | codes | date range |
|---|---|---|---|
| a_share | 4,570,086 | 3,273 | 2018-01-02 → 2026-05-15 |
| hk_share | 87,723 | 51 | 2018-01-02 → 2026-05-04 |
| us_share | 190,219 | 100 | 2018-01-02 → 2026-05-04 |

文件 `data/quant.duckdb` 约 100MB（vs 原 ~303MB CSV+parquet）。

## 验证

zhuang L1-E + L4-combo4 在 DuckDB 路径下完美复现：
- Sharpe **1.8492** (3y window) = 之前 combo4 结果 1.849
- 62 笔 / 收益 +23.86% / DD -1.83% / 胜率 51.6% / PF 3.83

全部 56 单元测试通过。

## 性能

- 单股票查询：~100ms（含 DB open）→ 后续 sub-ms
- 全量加载 3270 股票 px_cache：4s (OS 页缓存热) — 与 CSV 相当
- 跨股票分析查询：**新能力**，SQL 一行可做

## 文件清单

新增：
- `src/quant_system/data/__init__.py`
- `src/quant_system/data/duckdb_store.py`
- `scripts/migration/import_to_duckdb.py`

修改：
- `src/quant_system/strategies/zhuang/data/loader.py` — DB-first
- `src/quant_system/strategies/equity_factor/data/loader.py` — DB-first
- `pyproject.toml` — 加 duckdb / baostock 依赖
- `.gitignore` — `data/quant.duckdb`

**Why:** 解锁跨股票分析能力（factor IC / sector rotation 后续可基于 SQL），同时统一三个子策略数据层。CSV/parquet 保留作灾备，零中断。
**How to apply:** 后续新策略加载 daily 数据直接走 `quant_system.data.DuckDBStore`；定期跑 `scripts/migration/import_to_duckdb.py` 同步新增 CSV（或在数据拉取时同时写两份）。
