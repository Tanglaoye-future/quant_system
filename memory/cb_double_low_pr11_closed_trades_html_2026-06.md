---
name: cb-double-low-pr11-closed-trades-html-2026-06
description: PR11 — CB closed_trades 沉淀 (cb_exit_taxonomy + close_cb_trade wrapper + Journal.update_exit_features 公共 API) + standalone HTML 报告 CB section 渲染; advisory_only 期空 closed 显示 placeholder, 实盘出场后自动出 cb_exit_type/pnl_yuan 供 PR12 self_learning 分桶
metadata:
  type: project
---

# PR11 — CB closed_trades 沉淀 + HTML 报告 CB section

**日期**: 2026-06-17
**前置**: [[cb-double-low-pr8-journal-portfolio-2026-06]] schema + [[cb-double-low-pr9-rebalance-signal-2026-06]] signal + [[cb-double-low-pr10-intraday-risk-2026-06]] 实时风控
**Why**: 北极星支柱 4 (closed trade retrospective) 闭环最后一块 — closed_trades 沉淀 schema + 出场原因分类, 供 PR12 self_learning_pipeline winner-vs-loser 分桶.

## 关键设计

### Closed trade 走 journal_trades exit_date IS NOT NULL (不新建 cb_closed_trades 表)

延续 PR8 决策: CB 不开独立 ledger, 复用 `journal_trades` (strategy='cb_double_low' + market='cb_a' + exit_features JSONB).

PR8 时承诺的"CB 特有 entry_features JSONB"在 PR11 对称扩展到 **exit_features JSONB** — CB 特有 5 字段 (cb_exit_type / exit_reason_raw / exit_price / pnl_yuan / 保留 equity-flavor) 全部进 JSONB, schema 零 migration.

### CB exit_taxonomy 与 equity 平行 (不共享 layer 枚举)

equity layer (STOP_TRAIL/STOP_TREND/TAKE_PROFIT/OVERBOUGHT/TIME_STOP/REGIME) 都不对应 CB. CB 独立 layer:
| CB layer | reason 来源 | 语义 |
|---|---|---|
| SCORE_EXIT | score_over_180 / dual_low_too_high | 慢出场, 估值贵 (PR12 看大概率 winner) |
| STOP_LOSS | stop_loss / stop_loss_85 | 债底击穿, 信用风险 (PR12 看 loser) |
| FORCE_REDEEM | redeem_announced / cb_redeem_imminent | 强赎 ~100 元出场, mixed |
| REBALANCE | out_of_top_band / rank_drop | rank 漂移月度换仓 (PR12 看 neutral) |
| DELISTED | out_of_universe | 退市/被砍 filter (outlier) |
| OTHER | manual / unknown | 兜底 |

equity_factor.timing.exit_taxonomy.exit_layer_from_reason 不接 CB reason (全 OTHER). PR12 self_learning 分桶按 cb_exit_type, 不读 equity exit_type 字段.

### close_cb_trade 走 "journal.close_trade + update_exit_features 浅合并 patch"

- journal.close_trade() 内部已经算 pnl/pnl_pct/hold_days + 写 equity-flavor exit_features (exit_type/hold_days_bucket/max_dd/max_profit/asof). CB sleeve 沿用全部计算 (pnl 单位元, CB 按张 × 净价).
- close_cb_trade() 在之上 update_exit_features 浅合并补 5 字段, 不重写 equity 字段.

新加 **公共 API** `Journal.update_exit_features(trade_id, patch: dict)` (浅合并 dict). 仅 CB 调用, equity 行为零变化 (PR8 Backstop #5 兼容). PR12 self_learning backfill 也能复用.

### HTML report builder CB section (PR11 bonus)

`rebuild_html_report` 已迁前端 dashboard (Phase 3 single-pane noop). PR11 加 CB section 仅供 standalone `python -m quant_system.report.builder` 生成 (PM 手生成 PR 报告 / 邮件发送场景). 实盘主入口仍是 React frontend dashboard (PR7 已加 CB branch).

CB section 含:
- 顶部 mode badge (rebalance / maintenance) + target_pct + universe coverage + HOLD/SELL/BUY 计数 + 强赎临近
- entries_top top 5 表 (BUY 候选 + ⚠强赎临近 flag)
- 当月 closed trades 表 (cb_exit_type / exit_reason / pnl_pct), advisory_only 期空显示 placeholder

## 文件清单

| 文件 | 内容 |
|---|---|
| `cb_double_low/journal/exit_taxonomy.py` | cb_exit_layer_from_reason() — 6 layer 枚举 + dispatch |
| `cb_double_low/journal/__init__.py` | 加 close_cb_trade / list_closed_cb_trades helper |
| `equity_factor/journal/journal.py` | 加 update_exit_features(trade_id, patch) 公共 API |
| `report/builder.py` | 加 _render_cb_section(cb) + render() 加 cb 参数 + main() load("quant_cb") |
| `tests/cb_double_low/test_exit_taxonomy.py` | 20 case: 6 layer × 多 reason synonyms + edge case (case insensitive / None safe) |
| `tests/cb_double_low/test_close_trade.py` | 8 case: 4 layer 集成 / open→close 转移 / market filter / 浅合并 / 错 trade_id raise |
| `tests/cb_double_low/test_html_section.py` | 5 case: 有数据 / missing 空 / 空 entries / 旧 schema 兼容 / warn_redeem 标 |
| `memory/cb_double_low_pr11_closed_trades_html_2026-06.md` | 本文件 |

## 验收

| 命令 | 结果 |
|---|---|
| `pytest tests/cb_double_low/test_exit_taxonomy.py test_close_trade.py test_html_section.py -v` | **33/33 PASS** |
| `pytest tests/cb_double_low/ tests/db/ tests/equity_factor/test_journal.py tests/intraday/ tests/reporting/ -q` | **249/249 PASS** 全 CB + db + equity_journal + intraday + reporting 无回归 |
| `python -m quant_system.report.builder --date 2026-06-17` | 生成 `report/strategy_report_2026-06-17.html`, CB section 真实渲染 (mode=maintenance badge / 金埔/通合/洁美 top 5 / 本月暂无 closed) |

## 北极星支柱进度

| 支柱 | 状态 |
|---|---|
| 1 债性条款选标的 | ✅ (PR4) |
| 2 risk-parity 豁免 | ✅ (北极星扩展) |
| 3 实时风控 | ✅ schema (PR8) + daily signal (PR9) + 实时告警 (PR10) 三连闭环 |
| 3 日内做 T+0 (CB) | n/a (risk-parity 豁免) |
| **4 retrospective** | ✅ schema (PR8) + closed_trades 沉淀 (PR11) + 出场分类 (PR11) → **PR12 self_learning_pipeline 工作就绪** |

CB sleeve 已在 4 根支柱上全部接通 (支柱 3 比 equity 还多 1 项: CB 不做 T+0 不算缺位).

## advisory_only 期 UX (现在 → 9 月)

- 现在: closed_trades 为空, HTML section 显示 "本月暂无 closed trades" placeholder
- 7/1: PM 月初首次 rebalance, 录 20 笔 open
- 8/1 (或更早 若强赎/止损): 首笔 close_cb_trade 调用 → exit_features 含 cb_exit_type + pnl_yuan
- 9/30 累计 ~30 笔 closed → **PR12 self_learning_pipeline 首跑** → winner-vs-loser 分布报告 → PM 决定 v7 配比 Option 2 (CB 10%) 升级 / 维持 5% / 归档

## 不在 PR11 范围

- self_learning_pipeline CB 分支 (PR12): winner-vs-loser 分桶 + 报告生成. PR11 已铺好 cb_exit_type 字段, PR12 直接消费.
- React frontend CB section 增强 (PR7 落地有基础, PR11 用 standalone HTML 补 PM 手生成路径)
- close_cb_trade CLI (像 close_zhuang_manual.py): PM 7/1 后再开 CLI, 当前 advisory_only 期不急
- portfolio_unrealized_floor / peak_drawdown CB 分支: PR12+ (需要 spot 全市场算 mv)

## "≥ 90 天 + ≥ 30 笔不撬" backstop 兼容性

PR11 **未撬任何 yaml 参数** (n_entry / exit_threshold / stop_loss / sizing / weight 全部不动). 新增 cb_exit_taxonomy 是 schema 层不算撬阈值. Journal.update_exit_features 是新 API 不改既有 close_trade.

## 关联
- [[cb-double-low-pr8-journal-portfolio-2026-06]] schema 决策 (exit_features JSONB 复用)
- [[cb-double-low-pr9-rebalance-signal-2026-06]] daily signal (rebalance.mode / hold/sell/buy)
- [[cb-double-low-pr10-intraday-risk-2026-06]] 实时风控 (与 CB section 强赎临近指标关联)
- [[project-north-star]] 支柱 4 闭环
- [[session_2026_06_08_self_learning_pipeline]] PR12 base pipeline (将复用)
