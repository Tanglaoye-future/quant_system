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

## 13 条已证伪路径（不要重做）

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
| zhuang L7-B | accumulation_score_entry 70→67/65 | 3y 单调下 1.505→0.925→0.843, win 51.7%→36.8% |
| zhuang L8 | fundamentals gate (ROE>0 + 营收>0) | winner/loser ROE>0 占比 73% vs 79% 反向, 误杀比 47% ≈ 随机 |
| equity L9-B | +ROIC 10% / +AR YoY 10% (HS300) | 4y 0.857 → 0.761 (ROIC) / 0.826 (AR) / 0.838 (联合), 三 case 全负 |

## 下个 session 的 backlog（按 ROI 排）

### 1. ~~L7-A/B: zhuang 入场参数 sweep~~ — **2026-05-31 双向证伪**

- L7-A: position_max_count 6/8/10 三 case 同分 Sharpe 1.505，cap 永不 binding ([[zhuang_l7a_falsified_2026-05]])
- L7-B: accumulation_score_entry 70→67/65 Sharpe 单调下 1.505→0.925→0.843，win rate -15pp ([[zhuang_l7b_falsified_2026-05]])
- **结构性结论**: L1-E (score=70 + pos=0.4) 是 zhuang sleeve 当前架构 sweet spot
- **未来 zhuang alpha 必须靠外部信号增量**（fundamentals / 新维度 / 出场端 L4 续作），strategy 层参数 sweep 不再做

### 2. ~~实盘月度 KPI 报告脚手架~~ — **2026-05-31 已落 Phase 1**

- `scripts/reporting/monthly_kpi_report.py` + `tests/reporting/test_monthly_kpi_report.py` (10 单测 pass)
- closed trades 聚合 6 sleeve + 告警阈值 + markdown 输出
- 详见 [[monthly_kpi_scaffold_2026-05]]
- **2026-07-01 第一次跑**: `./venv/bin/python scripts/reporting/monthly_kpi_report.py --month 2026-06 --aum-cny <true> --qqq-return <x> --gld-return <y>`
- Phase 2 (60d 滚动 ρ + MTD Sharpe) 待实盘 ≥60 天后补 (2026-09 后)

### 3. ~~L8: zhuang fundamentals quality gate~~ — **2026-05-31 软证伪**

- 58 笔 trades fundamentals 预检查: winner/loser ROE>0 占比 73% vs 79% 几乎反向
- 联合 gate (ROE>0 AND 营收>0) 误杀比 47% ≈ 随机
- 庄股 alpha 与 fundamentals 结构性正交（业绩低谷启动）
- 详见 [[zhuang_l8_fundamentals_falsified_2026-05]]
- **下个 zhuang 优化方向已收敛到**: L4 出场端续作 / L5 仓位 sizing / 资金流维度（北向流入、龙虎榜机构席位）；策略层参数 + fundamentals 通道全部封死

### 4. ~~L9-B: ROIC + 应收账款 YoY (HS300)~~ — **2026-05-31 4y 证伪**

- ROIC 10% → 4y Sharpe 0.857 → **0.761 (-0.096)** (与 ROE 重复)
- AR YoY 10% → 0.826 (-0.031) (大盘行业属性)
- 联合 5%+5% → 0.838 (-0.019)
- factors.py + 9 单测 + akshare 数据接入工程已落, 默认权重 0; 未来 small-cap universe 可重启
- 详见 [[equity_factor_l9b_falsified_2026-05]]
- **结构性结论**: L8D2 是 HS300 因子层 efficient set, 与 zhuang L1-E 同构

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
