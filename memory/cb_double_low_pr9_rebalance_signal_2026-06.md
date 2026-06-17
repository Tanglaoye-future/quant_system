---
name: cb-double-low-pr9-rebalance-signal-2026-06
description: PR9 — CB daily 接通 journal.list_open 反查 current_holdings + 输出 BUY/SELL/HOLD 三栏 + rebalance/maintenance mode 判定; 不重做策略层 diff (复用 PR4 compute_target_portfolio 已有的 kept/exited/entered)
metadata:
  type: project
---

# PR9 — CB 月度 rebalance signal 接通

**日期**: 2026-06-17
**前置**: [[cb-double-low-pr8-journal-portfolio-2026-06]] schema 接通
**Why**: PR8 接通 schema 后, daily_cb 仍然 cold start (current_holdings=[]) — 等于 schema 通了但闭环没走通. PR9 把 daily_cb 反查 journal_trades, 输出"BUY/SELL/HOLD diff + 月初/平日 mode"等可执行 advisory.

## 关键洞察 — 不重做策略层

PR4 的 `compute_target_portfolio` 已经返回 `kept` / `exited` / `entered` 三栏, 等价 HOLD / SELL / BUY. PR9 范围退化为**纯报告层接通**:

| PR9 改动 | 文件 |
|---|---|
| `list_open_cb_holdings(journal) -> [bond_code]` helper | `cb_double_low/journal/__init__.py` (新增 1 函数) |
| `is_rebalance_day(date) -> bool` (启发式 day<=5) | `cb_double_low/engine/rebalance.py` (新文件) |
| `build_rebalance_payload(out, ranked, redeem_active, is_rebalance) -> {mode, hold, sell, buy, diff_summary}` | 同上 |
| daily_cb.py 接通 Journal → compute_target_portfolio → 三栏打印 + JSON 扩展 | `scripts/daily/daily_cb.py` |

## mode 判定 — 启发式 day<=5

- A 股月初第一个 trading day 通常在 1-3 号, 跨春节/国庆可能延到 5-8 号
- 精确判定需 trading calendar → PR9 简化为 `today.day <= 5` 启发式
- advisory only 系统 PM 看 mode 标签自己拍板, 工具不必替 PM 决策
- PR10+ 接 intraday_risk_check 时可顺手升级精确判定

## SELL urgency 三档

- **urgent=True (无论 mode 立即执行)**: `redeem_announced` / `stop_loss` / 在 redeem_active 集合内
- **urgent=False (rebalance day 执行, maintenance 期可推迟)**: `out_of_top_band` / `dual_low_too_high` / `out_of_universe`

## BUY deferred 标记

- `is_rebalance=True` → `deferred=False` 立即执行
- `is_rebalance=False` → `deferred=True` 等下个月初再买
- 与 SELL urgent 形成对称: maintenance 期出场不等, 入场等

## DB fail-soft 行为

journal.list_open() 抛异常 → 控制台 `⚠ journal 反查失败, 回退 current_holdings=[]` + 走 cold start. 不挂 daily. 与 PR8 portfolio_history dual-write 同模式.

## JSON payload 新字段

```jsonc
{
  // ... PR7/PR8 既有 fields ...
  "current_holdings": ["113008", "127090", ...],
  "rebalance": {
    "mode": "rebalance" | "maintenance",
    "hold": [{bond_code, bond_name, dual_low_score, close, conversion_premium_rate, weight}],
    "sell": [{bond_code, reason, urgent}],
    "buy":  [{bond_code, bond_name, ..., deferred}],
    "diff_summary": {n_hold, n_sell, n_sell_urgent, n_buy, n_buy_deferred}
  }
}
```

## 验收

| 命令 | 结果 |
|---|---|
| `pytest tests/cb_double_low/test_rebalance.py -v` | **12/12 PASS** |
| `pytest tests/cb_double_low/ tests/db/ tests/equity_factor/test_journal.py -q` | **89/89 PASS** 无回归 |
| `python scripts/daily/daily_cb.py --top 5` | 控制台输出 mode + diff_summary + BUY/SELL/HOLD 三栏 + JSON payload 含 rebalance 字段 |

## advisory_only 期 PR9 的实际 UX

- 今天跑 daily: current_holdings=[] (PM 未下单) → out['entered'] = top 20 cold start
- 控制台显示 `mode=maintenance HOLD=0 SELL=0 BUY=20 (deferred 20)` (今天 17 号, 非 rebalance window)
- PM 等到 7 月 1 号, daily 会自动出 `mode=rebalance BUY=20 (deferred 0)` 提示立即执行
- PM 月初手动下单 + 录 journal_trades 20 笔 → 7 月 2 号 daily 看到 current_holdings=20, mode=rebalance, HOLD/SELL/BUY 真 diff

## 与北极星支柱对齐

| 支柱 | 状态 |
|---|---|
| 1 债性条款 | ✅ (PR4) |
| 2 risk-parity 豁免 | ✅ (北极星 2026-06-15 扩展) |
| **3 实时风控 schema** | ⏳ → PR8 接通 schema, PR9 接通 rebalance signal 输出; PR10 接 intraday_risk_check 实时告警 |
| 4 retrospective | ⏳ → PR11/PR12 待做 |

## 不在 PR9 范围

- 实时风控告警（intraday_risk_check, 强赎 ≤30d / close<85 / score>180 推 Telegram）— PR10
- closed_trades 沉淀 + 前端 CBSleeveCard — PR11
- self_learning_pipeline retrospective — PR12
- trading calendar 精确判定 month-first-trading-day — 启发式够用, 延后
- SELL 项不在 advisory top N 时 wider lookup (PR9 已 graceful degrade, code+reason 给 PM 够看)

## "≥ 90 天 + ≥ 30 笔不撬" backstop 兼容性

PR9 **未撬任何参数** (n_entry / exit_threshold / stop_loss / min_premium / sizing / weight 全部不动). 仅在 daily 层接通策略层已有的 diff 输出 + 加 mode 提示. 与 [[cb-double-low-pr7-yaml-daily-2026-06]] backstop 不冲突.

## 关联
- [[cb-double-low-pr8-journal-portfolio-2026-06]] schema 前置
- [[cb-double-low-pr7-yaml-daily-2026-06]] daily 入口 + advisory_only 决策
- [[project-north-star]] 支柱 3 schema 接通 + signal 输出
- [[session-2026-06-16-cb-pr1-7-oneshot]] PR4 已有 compute_target_portfolio 的 kept/exited/entered 是 PR9 直接复用源
