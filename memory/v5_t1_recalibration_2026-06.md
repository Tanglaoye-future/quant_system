---
name: v5-t1-recalibration-2026-06
description: 2026-06-10 — T+1 zhuang 入场切换后 v5 efficient frontier 重校准；v5 静态 8y Sharpe 2.231→1.801 (Δ-0.43)，4y 2.751→2.105 (Δ-0.65)；grid 真最优 zhuang 砍到 10-15% + HK 顶到 35-40%；v5 不再是 efficient frontier，但 zhuang sleeve 仍贡献正 Sharpe
metadata:
  type: project
---

# v5 T+1 重校准（2026-06-10）

## 触发

commit 7f34bf8 把 zhuang 回测从 T+0 close 入场切到 T+1 开盘价（与实盘 daily_zhuang pending_entries 模型对齐）。原 [[v5_efficient_frontier_2026-05]] 2.231 Sharpe 基于不可执行的 T+0 假设，必须重校准。

## 单资产 Sharpe 双窗口 (T+0 → T+1)

| 资产 | 8y T+0 | 8y T+1 | Δ | 4y T+0 | 4y T+1 | Δ |
|---|---|---|---|---|---|---|
| zhuang solo | +1.348 | **+0.304** | -1.044 | +1.559 | **+0.204** | -1.355 |
| HK_mom | +1.170 | +1.170 | 0 (不变) | +1.660 | +1.660 | 0 |
| A_mom | +0.528 | +0.528 | 0 | +0.802 | +0.802 | 0 |
| A_mr | +0.265 | +0.265 | 0 | -0.021 | -0.021 | 0 |
| QQQ | +0.920 | +0.920 | 0 | +1.057 | +1.057 | 0 |
| GLD | +1.092 | +1.092 | 0 | +1.342 | +1.342 | 0 |

注: zhuang 全窗口（2018-2026）8y Sharpe -0.35（commit 7f34bf8 数字）；本表 8y 窗口 = 2020-01-02 起（受 zhuang 数据起点限制），2018-2019 段拖累在外。

## v5 静态 (HK25/A_mom10/A_mr10/zhuang40/QQQ5/GLD10)

| 窗口 | T+0 Sharpe | T+1 Sharpe | Δ | T+0 DD | T+1 DD | T+1 Ann |
|---|---|---|---|---|---|---|
| 8y | +2.231 | **+1.801** | **-0.430** | -2.71% | -4.39% | +7.20% |
| 4y | +2.751 | **+2.105** | **-0.646** | -2.71% | -3.95% | +8.94% |

v5 配比里 zhuang 40% 配比 = 单 sleeve 拖累放大约 0.40。

## Grid 真最优解（27,237 组合，step 5%, max 40%）

### 8y 窗口 (2020-01-02 ~ 2026-04-29, n=1441)

Top by Sharpe：**HK35 / A_mom10 / A_mr15 / zhuang15 / QQQ10 / GLD15** → Sharpe **+1.879** / Ann +10.30% / DD -5.67%
- v5 静态 8y T+1 = 1.801, 与最优 Δ = +0.078（v5 仍接近但不是 efficient frontier）

### 4y 窗口 (2022-04-30 ~ 2026-04-29, n=909)

Top by Sharpe：**HK40 / A_mom15 / A_mr10 / zhuang10 / QQQ10 / GLD15** → Sharpe **+2.326** / Ann +13.93% / DD -3.68%
- v5 静态 4y T+1 = 2.105, 与最优 Δ = +0.221

### 双窗口共识 (Backstop #2 同向 PASS)

| 资产 | v5 旧 | 8y 最优 | 4y 最优 | 共识区间 |
|---|---|---|---|---|
| HK_mom | 25% | 35% | 40% | **35-40%** (顶 max_weight cap) |
| A_mom | 10% | 10% | 15% | 10-15% |
| A_mr | 10% | 15% | 10% | 10-15% |
| **zhuang** | **40%** | **15%** | **10%** | **10-15%** ↓↓ |
| QQQ | 5% | 10% | 10% | 10% |
| GLD | 10% | 15% | 15% | 15% |

## 关键洞察

1. **zhuang sleeve 仍贡献正 Sharpe**（2020+ 窗口 0.20-0.30），不是负值（commit 8y -0.35 是含 2018-2019 段；2020+ 转正）。砍到 0 不是数据支持的决策。
2. **HK_mom 应从 25% 升到 max_weight cap 40%**：T+0 时代 zhuang 40% 是 HK 的上位替代，T+1 后 HK 单 Sharpe 1.17 vs zhuang 0.30 自然反转。
3. **A_mr 持续噪音级（4y 单 Sharpe -0.02）**，靠负相关 hedge 价值保留，与 [[a_mr_v2_falsified_2026-05]] 结论一致。
4. **v5 仍超过 2.0 Sharpe**（8y 1.80 / 4y 2.10），扣除 slippage + 摩擦后实盘期望 1.0-1.5 仍站得住。

## zhuang 处置选项（PM 决策，不自动改 yaml）

| 选项 | 描述 | 双窗口 v5* Sharpe | DD | 备注 |
|---|---|---|---|---|
| **A** 维持 40% | v5 不动 | 8y 1.80 / 4y 2.10 | -4.4/-4.0 | 假设原始信念不变 |
| **B** 降到 25% (HK 升到 40%) | grid 共识 | ~8y 1.85 / 4y 2.20 | ~-5/-4 | 需重跑确认 |
| **C** 降到 10-15% (grid 最优) | 双窗口最优 | 8y 1.88 / 4y 2.33 | -5.7/-3.7 | DD 略升 |
| **D** 砍到 0 | 极致纪律 | 待算 | 待算 | 不被数据支持（zhuang 单 Sharpe 仍正） |
| **E** advisory-only | 不自动建仓 PM 手动判每笔 | 等同 D 回测 | 同 D | 与 capitulation 证伪经验同源 ([[capitulation_strategy_falsified_2026-06]]) |

## 5 条 Backstop 检查 (Backstop #1-#5)

- **#1 17 条证伪墙**：这是 T+1 执行层校准，不是新 alpha 路径 ✓
- **#2 双窗口同向 PASS**：grid 最优 8y+4y 双窗口都把 zhuang 砍到 10-15%，方向一致 ✓
- **#3 实盘 < 30 笔不撬 frontier**：本次重校准基于 8y 回测，未撬实盘小样本 ✓
- **#4 PM 决策权**：本 memory 列选项不自动改 yaml；任何 yaml 调整另走 AskUserQuestion ✓
- **#5 采集 vs alpha 分离**：N/A（不涉及 self-learning） ✓

## 实盘后果（待决）

zhuang sleeve 当前实盘 3 仓（包含 600584 -14.32% wash advisory，[[case_2026_06_08_600584_distribution]]）。
- 若选 A/B/C：现有持仓继续按 yaml 退出规则跑
- 若选 D：需 PM 决定是否手动清仓 / 转 advisory 等仓
- 若选 E：daily_zhuang 暂停自动建仓 + 现有仓继续跑

## 不要做

- 不要因为 zhuang 单 Sharpe 跌就立刻 0 化 sleeve — 双窗口仍正
- 不要因为 grid 最优 Sharpe 比 v5 高 0.08 就立刻改 yaml — 实盘 30+ 笔再说（Backstop #3）
- 不要在 zhuang strategy 层再投工程 ([[zhuang_l7a_falsified_2026-05]] / [[zhuang_l7b_falsified_2026-05]] / [[zhuang_l8_fundamentals_falsified_2026-05]] 三连证伪)

## 产物

- `data/backtest/zhuang_a_share_2018-01-01_2026-05-25/equity_curve.csv` — 新 T+1
- `data/backtest/zhuang_a_share_2018-01-01_2026-05-25/equity_curve_t0_old.csv` — 旧 T+0 备份
- `data/backtest/portfolio_p1_V5_T1_RECAL_8Y.{md,json}` — 8y grid
- `data/backtest/portfolio_p1_V5_T1_RECAL_4Y.{md,json}` — 4y grid
- 本 memory

## 关联

- [[v5_efficient_frontier_2026-05]] — 旧 2.231 efficient frontier (已被 T+1 supersede)
- [[case_2026_06_08_600584_distribution]] — zhuang sleeve 实盘 wash sample #1
- [[session_2026_06_08_self_learning_pipeline]] — 5 条 backstop 来源
- [[zhuang_overlay_combo4_2026-05]] — zhuang 单资产 Sharpe 2.35 的 T+0 假设来源（现已 supersede）
- [[a_mr_v2_falsified_2026-05]] — A_mr noise diversification 不是 alpha 同款结论
- [[feedback_harness_first_pr_split]] — 任何 yaml 改动走 spec-first 独立 PR

**Why**: T+1 切换让 v5 旧 efficient frontier 数据基础（2.231 Sharpe）失效。校准结论：v5 仍可用（1.80/2.10 双窗口）但不再最优；最优解把 zhuang 砍到 10-15% + HK 顶到 40%。任何 yaml 改动需 PM 选 + 双窗口同向回测 + AskUserQuestion 通道（Backstop #2+#4）。

**How to apply**: 未来类似"执行层模型变更"（如 IBKR slippage 参数化、HK T+0 改 T+2 结算）触发的重校准，按本 memory 模板：(1) 旧 baseline 留 _t0_old 备份 (2) 双窗口 grid (3) 共识列权重对比 (4) PM 选项 (5) 不自动改 yaml。
