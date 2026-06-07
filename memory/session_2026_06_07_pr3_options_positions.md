---
name: session-2026-06-07-pr3-options-positions
description: PR3 of 持仓 v2 harness — options BCS spread 独立表 + IBKR leg→spread 聚合 + 前端 OptionsPositionTable + 16 case 测试；复用 PR2 失败 agent 的备份
metadata:
  type: project
---

# 2026-06-07 Session — PR3 持仓 v2 harness: options BCS 持仓字段对齐

接续 [[session_2026_06_07_pr2_max_drawdown]]。spec `docs/specs/position_v2_harness.md` §4。

## 范围

options BCS spread 字段与 stock 持仓完全不同（双 leg / debit / max_p / max_l / DTE），独立表 + 独立前端组件 + IBKR 单 leg → BCS spread 聚合 + breach_alerts（DTE<7 / loss>50%）。

## 改动落地（branch `pr3/options-positions-schema`）

| 文件 | 单元 |
|---|---|
| `src/quant_system/db/models.py` | `OptionsPosition` ORM（5-tuple UC + JSONB breach_alerts） |
| `src/quant_system/db/__init__.py` | export `OptionsPosition` |
| `alembic/versions/d2e3f4a5b6c7_add_options_positions.py` | DDL migration (head = d2e3f4a5b6c7) |
| `src/quant_system/db/ingest.py` | `upsert_options_position` + `maybe_upsert_options_position`（5-tuple UPSERT） |
| `src/quant_system/strategies/options/engine/monitor.py` | `compute_breach_alerts` + `aggregate_bull_call_spreads`（IBKR raw → spread JSON） |
| `scripts/daily/daily_options.py` | `_write_report_json` 加 `spreads` 参数 + IBKR 拉 raw → aggregate → 写表 |
| `scripts/daily/verify_dualwrite.py` | options kind pop `spreads`（独立表，不入 strategy_runs.metrics） |
| `frontend/src/types/index.ts` | `OptionsSpread` type + `OptionsData.spreads` |
| `frontend/src/components/OptionsPositionTable.tsx` | 新组件（strikes / DTE / debit / pnl / alerts） |
| `frontend/src/components/StrategyCard.tsx` | options block 集成持仓表 |
| `tests/options/test_options_positions.py` | 16 case（UPSERT 3 + breach 5 + aggregator 8） |

## 关键设计决策

### 独立 options_positions 表
spread schema 与 stock positions 5+ 字段差异（双 strike、expiry、debit、max_p/l、DTE）。不复用 positions 表的 payload JSONB 兜底，单独表读写一目了然。

### BCS 聚合在 monitor 层做
`aggregate_bull_call_spreads(positions, asof, spread_quote_lookup=None)`：
- 同 expiry 按 Call leg 配对：低 strike long + 高 strike short
- debit_paid = (long_avg - short_avg) / 100 per share
- max_profit = (short - long - debit) × 100
- max_loss = debit × 100
- 可选 `spread_quote_lookup` callable 返当前 spread mid → 算 current_value + pnl_pct
- breach_alerts = compute_breach_alerts(DTE, pnl_pct)
纯函数 + 可注入 quote_lookup → 测试不需要真 IBKR。

### verify_dualwrite pop spreads
spreads 入独立表 options_positions 不入 strategy_runs.metrics。verify 直接 pop 避免假阳；表内一致性靠契约测试覆盖。TODO 留 PR3+：JSON.spreads vs DB 表行直接 join 校验。

### IBKR 失败兜底
daily_options 内 try/except 包裹 aggregate；失败只打印不阻塞主路径（quote 拉不到 spread mid 为 None，pnl_pct=None 也合法）。

## 复用 PR2 失败 agent 备份

PR2 session 时 spawn 的 agent worktree 隔离失败，agent 工作落在主仓被 revert，备份在 `/tmp/agent-work-pr3/`。PR3 串行重做时审核备份 + 手术式 cherry-pick：

- 直接采纳：`models.py` OptionsPosition class / `__init__.py` export / `ingest.py` upsert+maybe / migration / `options/engine/monitor.py` aggregate+breach / `OptionsPositionTable.tsx`（含 Tailwind 配色） / `daily_options.py` `_write_report_json` 加 spreads / verify_dualwrite options pop
- 修补：agent 没接 StrategyCard.tsx（PR3 集成补齐）
- 新写：agent 没写测试 → 16 case 全新写（spec §4.7 7 case + 9 额外的 aggregator 覆盖）

## 验证门（全绿）

- `pytest tests/options/test_options_positions.py` → 16/16 PASS
- `pytest tests/` → 252/252 PASS（PR2 时 236 + PR3 16）
- `alembic heads` → 单 head `d2e3f4a5b6c7`，linear
- AST parse 7 改动 .py OK
- `cd frontend && npx tsc --noEmit` → 0 错误
- 默认 OFF（QUANT_PG_DUALWRITE 关 / 无 IBKR 连接）spreads=[] 写 JSON 不影响 verify

## 推迟 / TODO

- JSON.spreads vs DB join 校验留 PR3+（注释在 verify_dualwrite 内）
- HK options（HSI BCS）spread_type 当前硬 "BCS"，HK 实施时区分
- agent 备份目录 `/tmp/agent-work-pr3/` 可清理

## 关联

- [[session_2026_06_07_pr2_max_drawdown]] — PR2 + agent worktree 隔离 lesson
- [[session_2026_06_07_pr1_portfolio_history]] — PR1（同 ingest.py 模式）
- `docs/specs/position_v2_harness.md` §4 — 验收契约
- [[options_decouple_2026-05]] — options 包 strategies/+markets/ 拆分基础
