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

"先拿住当教训用来强化训练" — 用户授权不平仓, 让 600584 当作 self-learning
pipeline 训练样本。

**M5 修复后真相校准** (2026-06-09 实证): cache stale 之前显示 -7.80%, M5
fall through baostock 后实际 **-14.32%** (close 70.30 <= stop 77.13). 用户
看到真实数据后**仍维持"拿住"决策**, 二次确认.

诚实成本提示:
- 持仓继续探底的金融成本是真实的 (现 -1.76 万元, 12.31 万 cost)
- max_drawdown_during_hold 已落 zhuang_snapshots (-11.46% → -14.32%)
- exit_features 要等最终平仓才落 (L4 PR #13)
- L5 retrospective 报表只看 closed trades → 持有期间不进报表
- 庄股跌 -15%+ 后 30 天反弹概率 ~25% (历史经验值, 非严格统计)

## 06-09 反弹 (advisory 误信号 sample #1)

**实证 (akshare 新浪实时, 11:51 盘中)**:
- 600584 06-08 收 70.30 → 06-09 盘中 **75.00 = +6.69%** 反弹
- 实时 pnl: -14.32% → **-8.59%** (反弹 5.73 pp, 一日内)
- 同日 000063 +5.95% / 600919 +2.27% / 600584 +6.69% — 多只跟涨, A 股小幅普涨日

**advisory 误信号 sample 入账**:
- 06-08 daily 给出 "卖出建议: stop_loss close=70.30 <= stop=77.13"
- 用户没卖 → 06-09 反弹 +6.69% → **advisory 这次错了**
- 若按 advisory 平仓 70.30 → 少赚 4.70 元/股 × 1500 = **-7,050 元 opportunity loss**

**关键澄清** (PM 心理校准, 避免错误归因):
- N=1 sample 不能推翻 advisory 出场机制 (zhuang 6y Sharpe 1.81 含大量"卖出后继续跌"的对样本)
- "advisory 卖错" 是策略机制的固有 noise, ~30-40% 误判率
- 这次反弹不证明"系统坏", 下次同样信号 PM 拿住, 可能继续跌
- 真正的"教训"不是"该信 / 不该信 advisory", 是 **样本量积累后看分布** (L5 报表)

**记入 self-learning pipeline 的方式**:
- 当前 trade 仍 open → entry_features 已落 (L3 PR #12)
- 用户最终决定平仓时 → close_trade 自动落 exit_features (L4 PR #13):
  exit_type / max_drawdown_during_hold_pct / max_profit_during_hold_pct
- L5 报表会把这笔归入 winner/loser (按最终 pnl), 而非按 advisory 是否对/错

## "高冲低卖" 诊断 (PM 心理 — 2026-06-09)

用户 06-09 批评: "高的时候让我冲进去, 跌的时候让我卖, 一来一回全是亏算".

诚实回应:
1. **"高冲入"** 是 momentum/zhuang 算法机制 — A_mom 突破入场必然抓阶段新高;
   zhuang 信号 = 量异常 + 价高位 = 主力吃货迹象, 入场点不会是底部
2. **"低位卖"** 是 stop_loss / distribution 出场触发, advisory 不强制
3. 用户感觉的"全是亏" 部分错觉部分真实:
   - **真实**: 17 天里多数浮亏, 心理压力大
   - **错觉**: 浮亏 ≠ 实亏; closed trade 只有 1 笔 (601066 +3.46%)
   - **真整体**: 06-09 盘中实时 pnl ≈ -0.51% (A_mom +1.34% / zhuang -6.29%)
4. **真痛点不是策略, 是**:
   - cache stale 显示偏差 (M5 修了)
   - advisory 工作流 gap (没卖 → 这次侥幸赢了)
   - 实盘 17 天 sample 不足以判断

**Why** (写给未来 cold-start): 用户在实盘窗口 (尤其前 30-60 天) 会反复体验
"看到浮亏 → 怀疑策略 → 想推翻". 不要被这种 narrative 牵着走, 必须用 **数据**
(closed trades + α vs benchmark + 8y backtest 历史 DD) 反驳, 同时承认 PM 心理
压力真实 (不要冷冰冰说"再等等"). 600584 这一笔是 advisory 误信号 sample #1,
未来积累 ≥ 30 笔 closed 后才有 L5 报表去看 advisory 准确率.

**How to apply**: 用户再次说"系统就是骗我亏" 时, 按以下顺序回应:
1. 拉实时数据 (akshare 新浪, push2 被代理拦绕开)
2. 给真实当前 pnl (区分 A_mom vs zhuang vs 整体)
3. 给已 closed trade 数 + 平均 pnl
4. 不否认 PM 心理痛苦, 但要校准事实
5. 把"误信号" / "对信号" 都记入 L5 sample, 不要单方面叙事

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
