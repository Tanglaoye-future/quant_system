---
name: session-2026-06-07-pr1-portfolio-history
description: PR1 of 持仓 v2 harness — portfolio_history 表 + UPSERT 写入路径 + 7 个契约测试；max_drawdown peak DD 的纯基建，不计算 DD
metadata:
  type: project
---

# 2026-06-07 Session — PR1 持仓 v2 harness: portfolio_history 基建

接续 [[feedback_harness_first_pr_split]] 新规则下的第一个 PR。spec 见 `docs/specs/position_v2_harness.md`。

## 范围（spec §2）

仅基建 —— 建 `portfolio_history` 表 + daily 收尾 UPSERT 一行。**不**计算 peak DD（PR2 做），**不**暴露到 JSON / 前端 / verify_dualwrite。

## 改动落地（branch `pr1/portfolio-history-schema`，未推 origin）

| 文件 | 单元 |
|---|---|
| `src/quant_system/db/models.py` | `PortfolioHistory` ORM（asof + strategy_name + market 三元唯一） |
| `src/quant_system/db/__init__.py` | export `PortfolioHistory` |
| `alembic/versions/c1d2e3f4a5b6_add_portfolio_history.py` | DDL migration (head = c1d2e3f4a5b6) |
| `src/quant_system/db/ingest.py` | `upsert_portfolio_history` + `maybe_upsert_portfolio_history` |
| `scripts/daily/daily_equity.py:457` | daily 收尾挂入（不影响 JSON 跑批） |
| `scripts/daily/daily_zhuang.py:461` | daily 收尾挂入 |
| `tests/db/test_portfolio_history.py` | 7 case UPSERT 契约测试 |

## 关键设计决策

### UPSERT not append
同 (asof, strategy_name, market) 重跑覆盖。用户日内手动 dashboard 多次跑 daily 不堆历史；spec §2.2 明文。

### env QUANT_PG_DUALWRITE 控制 + 失败 silent
与 `maybe_ingest_*` 同款：DB 不可达只 logger.warning，JSON 仍为准。

### 表与 strategy_runs 解耦
不挂 FK 到 strategy_runs（zhuang/equity 各自 ledger 独立），由 (asof+name+market) 三元组自然 join。PR2 query 时直接按 strategy_name + market 跑 lookback 窗口。

### 空仓也落一行
`test_upsert_zero_positions_allowed` 强制 — PR2 peak DD 序列要连续，缺日会算错 peak。

## 验证门（全绿）

- `pytest tests/db/test_portfolio_history.py` → 7/7 PASS
- `pytest tests/` → 227/227 PASS（原 191 + zhuang 33 + 本 PR 7 + 其它）
- `alembic heads` → 单 head `c1d2e3f4a5b6`，linear
- 4 个 py 文件 ast.parse OK
- import sanity：`PortfolioHistory` 9 字段 + UC 命中

## 故意不做的事

- peak DD 计算 / PortfolioRisk 字段扩展 → PR2
- JSON 暴露 / 前端 column / verify_dualwrite pop → PR2
- options 不接（spread schema 不同，PR3 单独表）
- yaml 阈值 → PR2 一并接

## 推迟 / TODO

- PR2 ready 后第一次实盘跑会写入第 1 行；前 0 历史不回填（60d 自然累积）
- PR3 / PR4 / PR5 并行可启动（不依赖 PR2）

## 关联

- [[feedback_harness_first_pr_split]] — 本 PR 是新方法论的第一个产物
- `docs/specs/position_v2_harness.md` — PR0 spec（本 PR 比对源）
- [[session_2026_06_06_zhuang_risk_parity]] — v1 截止快照（safety margin + portfolio_alerts 全链路上线）
- [[db_decouple_phase0_2026-05]] — PG 双写架构基础
