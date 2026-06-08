---
name: case-2026-06-08-600584-distribution
description: 实盘 zhuang 600584 长电科技 -14.32% case — distribution 信号 6-1 已触发, advisory 不自动平 + PM 没手工卖 + DuckDB cache stale 4 天 = "拿住等教训" 决策的真实成本; 工作流 3 重 gap 沉淀, 用户授权拿住做训练样本不平仓
metadata:
  type: project
---

# 600584 长电科技 case — 三重工作流 gap 暴露

## 时间线 (实证)

| 日期 | 事件 | close | pnl% | 距 stop |
|---|---|---|---|---|
| 5-29 entry | zhuang Phase-A 建仓 @82.05, atr=6.6, stop=77.13 | 82.05 | 0% | +6.4% |
| 6-1 (周一) | **首次跌穿 stop** (75.65 < 77.13) | 75.65 | -7.80% | **-1.9%** ⚠ 应触发 advisory exit |
| 6-2 | 继续跌, 触底 (盘中 72.65) | 75.35 | -8.17% | -2.3% |
| 6-3 | 反弹回 stop 上方 → advisory 状态消失 | 80.13 | -2.34% | +3.9% |
| 6-4 | 横盘 | 80.08 | -2.40% | +3.8% |
| 6-5 | **再次跌穿 stop** | 75.65 | -7.80% | -1.9% |
| 6-8 | distribution 信号触发 (turnover 9.40 > 6.0); **加速下跌** | 70.30 | **-14.32%** | **-8.86%** 💥 |

成本 1500 × 82.05 = 12.31 万 → 现 1500 × 70.30 = 10.55 万, 浮亏 **-1.76 万元**.

## 三重工作流 gap

### Gap 1: DuckDB cache freshness 没有自动 refresh
- DuckDB `daily_bars` 截止 2026-06-04 (4 天 stale, 实测 6-9)
- daily_zhuang 用 cache 6-4 close 80.08 → pnl 显示 -2.40% 而非真实 -14.32%
- 距 stop 显示 +3.82% 而非真实 -8.86%
- 8 天没人发现 600584 已经爆 stop **8.86%**

修法 ([[duckdb_cache_freshness]] M5): `cache_latest < end - skew_days` 强 fall through baostock refresh

### Gap 2: zhuang advisory 出场 + PM 没手工卖
- zhuang 设计 by design: exit 是 advisory 不自动平 (与 equity_factor 不同)
- 6y backtest Sharpe 1.81 基于 PM 干预出场
- 实盘 PM (用户) 没及时手工平, 损失从 advisory 触发时的 -7.80% → 持有到 -14.32%

不修法 (留 backlog): 改 zhuang advisory → auto-close 需要 8y 双窗口验证 Sharpe 不退化, alpha 改动

### Gap 3: daily 输出对"已跌穿"与"贴近"无视觉差异
- 改前: 距 -8.86% 与距 +0.8% 都显示 "⚠ 临界"
- PM 看 daily 看不出哪个紧急

修法 ([[zhuang_stop_breach_alert]] M4): 三级状态 normal / critical / breached, dist < 0 显示 "🔴 跌穿 X%" + 头部 banner

## 用户决策 (2026-06-09)

"先拿住当教训用来强化训练" — 用户授权不平仓, 让 600584 当作 self-learning pipeline 训练样本。

诚实成本提示:
- 持仓继续探底的金融成本是真实的, 与"学习价值"不挂钩
- max_drawdown_during_hold 已落 zhuang_snapshots (-11.46% → -14.32%)
- exit_features 要等最终平仓才落 (L4 PR #13)
- L5 retrospective 报表只看 closed trades → 持有期间不进报表

## 沉淀 (PM 未来决策)

**Why**: 这个 case 暴露了 deployment / observability / data freshness 三个 gap, 不是 alpha 失败. self-learning pipeline 的真"学习"应该是修这三个 gap, 而不是 sweep zhuang 参数.

**How to apply**: 未来用户报"持仓亏损 / 没及时平", 按这 3 个 gap 顺序检查:
1. cache 是否 fresh? `SELECT MAX(date) FROM daily_bars WHERE code=...`
2. 信号是否在 advisory 状态被忽视? `journal_snapshots.risk_flag = 'exit'` 但 trade 仍 open
3. 显示层是否区分了 breached vs critical?

## 关联

- [[duckdb_cache_freshness]] (M5) — Gap 1 修法
- [[zhuang_stop_breach_alert]] (M4) — Gap 3 修法
- Gap 2 (advisory → auto-close) — 留 backlog, 需双窗口验证
- [[self_learning_pipeline]] — L1-L5 pipeline 接收这个 case 的 exit_features (用户平仓后)
- [[session_2026_06_08_self_learning_pipeline]] — 总路线
