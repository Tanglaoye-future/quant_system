---
name: cb-double-low-pr8-journal-portfolio-2026-06
description: PR8 — CB 双低 sleeve 接通 journal_trades + portfolio_history (Postgres 共享表族), 不新建 cb_trades 表, advisory_only 期空持仓也写 portfolio_history 建立净值曲线 baseline; strategy_runs 维持 PR7 决策不入 DB
metadata:
  type: project
---

# PR8 — CB 双低 journal + portfolio_history 双写

**日期**: 2026-06-17
**前置**: [[cb-double-low-pr7-yaml-daily-2026-06]] advisory_only 落地; PM 决策 "做 CB PR8 闭环 + ETF probe 支线"
**驱动**: 用户审计 "可转债策略只有推荐, 没有买入卖出和持仓" — 违反"回测好必须能在真实实盘环境跑通"的项目硬约束 (北极星支柱 3+4 占位 ⏳)

## 关键决策 — 复用 journal_trades 共享表, 不开 cb_trades 独立表

### 决策来源
- `journal_trades` 早就有 `strategy` 列 (`b2c3d4e5f6a7_add_journal_strategy_col.py`) + `entry_features` / `exit_features` JSONB (`a6b7c8d9e0f1_add_features_jsonb.py`)
- `RiskMonitor` 已按 `(market, strategy)` filter 评估 (`equity_factor/risk/monitor.py:147` 注释明写"避免串台 + 误自动平仓")
- `zhuang_trades` 独立 ledger 是历史遗留 (当年 strategy 列还没加), 不该作为新策略的模板
- `portfolio_history` 早就是 `(asof, strategy_name, market)` UNIQUE 的统一表

### CB 在 journal_trades 中的命名空间
- `strategy = 'cb_double_low'`
- `market = 'cb_a'` (区分 equity 的 a_share / hk_share / us_share)
- `symbol = bond_code` (6 位数字, 复用 String(32) 字段)
- `entry_price` / `entry_size` = CB 净价 / 持仓张数 (CB 面值 100, 按张交易)
- `stop_loss_price = 85.0` (yaml stop_loss_close), `take_profit_price = None` (CB 出场是 score/强赎, 不是固定 TP)
- CB 特有指标 (dual_low_score / conversion_premium / scale / rating / years_to_maturity / last_trading_date) → `entry_features` JSONB
- alembic 零 migration

## 实施清单 (4 文件 1 测试目录)

| 文件 | 内容 |
|---|---|
| `src/quant_system/strategies/cb_double_low/journal/__init__.py` | 薄 facade re-export `Journal` + `TradeOpen` + `CB_STRATEGY` / `CB_MARKET` 常量 + `build_cb_entry_features` / `build_cb_trade_open` helper |
| `scripts/daily/daily_cb.py` | 末尾加 `maybe_upsert_portfolio_history(asof, 'cb_double_low', 'cb_a', n=0, ...)` — advisory_only 期空持仓也写, 净值曲线连续 |
| `config/cb_double_low.yaml` | 北极星 cross-check 注释更新: 支柱 3 ⏳→ PR8 接通 schema + PR10 接 intraday_risk_check |
| `tests/cb_double_low/test_journal.py` | 6 case: features 字段完整性 / optionals None / trade_open 映射 / open+list / **strategy filter 隔离 equity** / close 算 pnl |
| `tests/cb_double_low/test_portfolio_history.py` | 4 case: 空 sleeve UPSERT / 同日重跑幂等 / 与 equity_factor 同日共存 / 多日曲线 |

## 关键反例 — 我中途差点撬了 PR7 的"advisory 不入 DB"决策

第一版 PR8 草稿里我加了 `ingest_cb` + `maybe_ingest_cb` 写 `strategy_runs` + `signals`. 在 grep `report/registry/resolver.py:510-514` 时发现注释:
> CB_ADVISORY_MERGE 2026-06-16: advisory_only 策略 (e.g. cb_double_low) 不入 DB, 但确实在跑 + 产 JSON. DB 不含的 key 用 filesystem 兜底, 避免前端 has_data=False.

PR7 当时刻意决策 advisory 不入 strategy_runs (避免与真信号混淆), 前端走 filesystem 兜底. 我自作主张加 ingest_cb 等于撬这个决策, 立刻回滚.

**教训**: 既有 PR 落地的反向决策 (有的是显式注释) 在 grep 时必须留意, 不只看"我能加什么"也要看"前任为什么没加".

## portfolio_history 为什么可以入 (与 strategy_runs 不同)
- `strategy_runs` 语义是"daily 跑批结果 + 信号" — advisory 等价于推荐, 不是真持仓, 不应混入信号源
- `portfolio_history` 语义是"组合层每日净值 / 持仓汇总" — 空持仓 (n=0/mv=0) 也是有意义的"今天 CB sleeve 还未建仓" baseline, PR9 月初 rebalance 接通后续真值, **曲线连续, 时序无空洞**

## 验收

| 命令 | 结果 |
|---|---|
| `pytest tests/cb_double_low/test_journal.py tests/cb_double_low/test_portfolio_history.py -v` | **10/10 PASS** |
| `pytest tests/cb_double_low/ tests/db/ tests/equity_factor/test_journal.py -q` | **77/77 PASS** (全 CB + db + equity journal 无回归) |
| `python scripts/daily/daily_cb.py --top 5` | DB 不可达时 `maybe_*` fail-soft logger.warning, JSON 仍为准 (与 daily_equity 同模式) |

## 北极星支柱对齐度更新

| 子策略 | 支柱 3 风控 schema | 支柱 4 retrospective |
|---|---|---|
| cb_double_low | ⏳→ **PR8 schema 接通** (journal_trades + portfolio_history), PR10 接 intraday_risk_check | ⏳→ PR11 closed_trades + PR12 self_learning_pipeline 待做 |

## 不在 PR8 范围 (PR9+)
- 月度 rebalance signal 自动 diff (BUY/SELL/HOLD) — PR9
- 实时风控 CB 分支接 intraday_risk_check — PR10
- closed_trades 沉淀 + 前端 CBSleeveCard — PR11
- self_learning_pipeline CB 分支 — PR12

## "≥ 90 天 + ≥ 30 笔不撬" backstop 兼容性

PR8 **未撬任何参数** (n_entry / exit_threshold / stop_loss / min_premium / sizing / weight 全部不动). 仅补支柱 3 schema 工程缺位, 与 [[cb-double-low-pr7-yaml-daily-2026-06]] backstop 不冲突.

## 关联
- [[project-north-star]] 4 支柱 (支柱 3 schema 部分接通)
- [[cb-double-low-pr7-yaml-daily-2026-06]] 前置 + advisory_only 决策来源
- [[session-2026-06-16-cb-pr1-7-oneshot]] 末尾"PR8 候选"清单
- [[feedback_harness_first_pr_split]] 方法论 (单 PR 单职能)
