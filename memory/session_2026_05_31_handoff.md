---
name: session-2026-05-31-handoff
description: 2026-05-30~31 两天 session 总账 + 下个 session 的 actionable backlog；9 条优化路径证伪 + L6-A 落 yaml；下阶段实盘窗口 + L7-A position_max_count 是最高 ROI 待做
metadata:
  type: project
---

## 当前状态 (2026-05-31 收工)

- **v5 部署不变** (HK25/A_mom10/A_mr10/zhuang40/QQQ5/GLD10) — 已被 9 条路径全证伪证明是 efficient frontier
- **L6-A 落 yaml**: zhuang accumulation_weights 全 0.20 (commit 77ea9b6)
- **实盘 3 月窗口开启** (2026-05-30 起) — KPI checklist 见 [[v5_efficient_frontier_2026-05]]
- 4 个 commit：1c4e247 / dfcbac9 / 0584dd8 / 77ea9b6
- 7 个新 memory: a_mr_rebuild / a_mr_v2_falsified / hk_ah_premium_research / v6_regime_overlay / v5_efficient_frontier / zhuang_l6a_weights / 本文件

## 10 条已证伪路径（不要重做）

| 类别 | 路径 | 证伪结论 |
|---|---|---|
| A_mr strategy | v1 SwingReversion | 4y Sharpe -0.27 |
| A_mr strategy | v2 (buffer+slope+grace) sweep | plateau -0.27~-0.34 |
| 组合层重配 | v6 砍 A_mr | 组合 -0.10 + 2022 反向 |
| 组合层动态 | v6 regime overlay | -0.089 + 2025-26 反弹 -0.40 |
| 新资产 | +IBIT 5/10% | -0.28 / -0.87 |
| 新资产 | +TLT 5/10% | -0.13 / -0.37 |
| 新资产 | +CSI1000 5/10% | -0.10 / -0.34 |
| HK overlay | AH 溢价 (微研究) | alpha 不稳定 (1/5 负 4 弱正) |
| zhuang weights | strong-volume / strong-conso (过拟合) | 单维放大 < equal |
| zhuang L7-A | position_max_count 6→8/10 | 3y 三 case 同分 / cap 永不 binding (mean concurrent 0.5) |

## 下个 session 的 backlog（按 ROI 排）

### 1. ~~L7-A: zhuang position_max_count~~ — **2026-05-31 已证伪**

- 3y 三 case (6/8/10) 完全同分 Sharpe 1.505 / 58 trades
- mean concurrent 0.5 仓位 / 打满 cap 仅 0.5% 交易日
- 详见 [[zhuang_l7a_falsified_2026-05]]
- **反向洞察**: 未来 zhuang sleeve 优化先看 trades.csv 的 concurrent 分布；瓶颈在入场层而非仓位上限

### 2. 实盘月度 KPI 报告（2026-06-30 节点）

- **触发**: 实盘运行 1 个月后第一次 KPI 检查
- **数据源**: journal (Postgres) + report.builder
- **报告模板**: 见 [[v5_efficient_frontier_2026-05]] 末尾"3 月实盘验证 KPI checklist"
- **关键 KPI**:
  - 各账户 MTD 收益 vs 回测同期方向（偏离 ±5pp 触发诊断）
  - 跨账户 60d 滚动 ρ（< 0.30 为正常）
  - 组合月收益 < -2% 立即诊断
- **工程量**: 写 monthly_report.py 脚本读 journal + 出 markdown
- **预期总时间**: 1 个 session

### 3. L7-B: zhuang fundamentals quality gate（中等 ROI，谨慎）

- **假设**: 入场加 ROE > 0 + 营收增速 > 0 过滤业绩差股
- **风险**: [[zhuang_l1_l2_l3_experiments_2026-05]] L2/L3 (信号 overlay) 已证负转移 — 庄股本来就业绩烂，fundamentals gate 可能砍掉好笔
- **执行前**: 先做小样本测试（5-10 只历史 winner trades 看是否有 ROE < 0 但真赚钱的 — 如有，gate 会误杀）
- **工程量**: 中等（需接 baostock fundamentals + cache）
- **预期**: 不确定（可能 +0 ~ +0.05 sleeve Sharpe）
- **预期总时间**: 1-2 个 session

### 4. fundamentals 升级 (L9-A 因子加 ROIC / 应收增速)

- **现状**: L9-A 8y Sharpe 0.363（边缘 PASS），单策略空间还有
- **加因子候选**: ROIC（资本回报率）/ 应收账款增速（造假信号）/ 经营性现金流质量
- **数据**: A 股 baostock + akshare; HK 不支持（[[hk_optimization_2026-05]] 价值因子反 alpha 不做）
- **工程量**: 大（需扩 factors.py + 数据接入 + asof 截断 + 单测）
- **预期**: +0.05-0.10 L9-A sleeve Sharpe，组合层 +0.02-0.04（按本 session 实测放大率 0.45×）
- **预期总时间**: 2-3 个 session

### 5. HK 真做空 leverage（高 ROI 但高风险）

- **现状**: HK overlay 是 synthetic short（架空对冲，不是真仓位）
- **目标**: 接交易所融券 / hsi 期货 API 做真双边 hedge
- **预期**: alpha 放大 1.5-2×（路线 D from [[hk_optimization_2026-05]]）
- **风险**: 实盘资金 + 合约管理 + 杠杆，PM 须明确批准
- **工程量**: 3-5 天
- **预期总时间**: 多 session
- **执行前必读**: [[hk_optimization_2026-05]] 路线 D + 实盘资金决策

## Cold-start 给新 session 的最重要 3 条

1. **不要再试组合层重配 / regime overlay / 新资产**: 9 条路径已证 v5 是 efficient frontier
2. **A_mr 不要再优化**: solo Sharpe -0.27 是结构性上限，价值在 noise diversification 不在 alpha
3. **sleeve→组合放大率 ~0.45×**: 任何 sleeve 优化预期 Sharpe 改进必须 ≥ 0.05 才能在组合层显著（不被 v5 vol 稀释）

## 不要做（避免下个 session 重蹈覆辙）

- 不要砍 A_mr — diversification value > standalone value
- 不要 sleeve sweep 不双窗口验证就落 yaml — strong-conso 在 3y 赢但 6y 反转过拟合
- 不要把"sleeve Sharpe +0.1 = 组合 +0.05"当公式 — 本 session 实测放大率 0.45×
- 不要在沙箱里 4-worker 并发跑 backtest sweep — yaml + output dir 全局共享会 race
- 不要假设 PM 视角的"应该砍弱腿" — 数据 grid 验证之前别落决策（v6 砍 A_mr 被反向证伪）

**Why:** 收工时把 9 条证伪路径 + 4 个 commit + 7 个新 memory 浓缩成下个 session 的 cold-start 入口，避免新 session 重做证伪实验或重新推导效率前沿。
**How to apply:** 新 session 启动后先读本文件 → 选 L7-A 推进（最高 ROI 待做）→ 完成后 commit；不在 backlog 列表里的方向先 AskUserQuestion 确认必要性。
