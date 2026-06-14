---
name: v5-grid-hk-t0-recal-2026-06
description: 2026-06-14 — v5 portfolio grid 用 HK_mom T+0 新 baseline 重跑双窗口；Top1 配比与 T+1 完全一致 (HK 35-40 / A_mom 10-15 / A_mr 10-15 / zhuang 10-15 / QQQ 10 / GLD 15), Sharpe 改善被组合层稀释到 8y +0.010 / 4y +0.087；v5 grid 共识不需因 T+0 调整, HK_mom 25→35-40% 仍是唯一待落 PM 决策
metadata:
  type: project
---

# v5 grid HK T+0 重校准（2026-06-14）

## 一句话

[[hk_t0_recalibration_2026-06]] 把 HK_mom sleeve Sharpe 8y +0.065 / 4y +0.059 后，重跑 v5 6-asset grid 双窗口：**Top1 配比与 T+1 baseline 完全 identical**，portfolio Sharpe 提升 8y +0.010 / 4y +0.087（被组合层稀释）。**v5 efficient frontier 形状不被 HK T+0 改写**；唯一待落 yaml 改动是 HK 25→35-40%，这与 T+1 grid 推荐一致（[[v5_t1_recalibration_2026-06]] 双窗口共识），属 PM 决策。

## 单资产 8y T+0 sleeve Sharpe

| 资产 | T+0 (8y) | T+1 (8y) | Δ | T+0 (4y) | T+1 (4y) | Δ |
|---|---|---|---|---|---|---|
| **HK_mom** | **+0.644** | +0.579 | **+0.065** | **+1.149** | +1.090 | **+0.059** |
| A_mom (T+1) | +0.528 | 同 | 0 | +0.802 | 同 | 0 |
| A_mr (T+1) | +0.265 | 同 | 0 | -0.021 | 同 | 0 |
| zhuang (T+1) | +0.304 | 同 | 0 | +0.204 | 同 | 0 |
| QQQ | +0.920 | 同 | 0 | +1.057 | 同 | 0 |
| GLD | +1.092 | 同 | 0 | +1.342 | 同 | 0 |

## Grid 双窗口 Top1 (step=5%, max=40%, 27,237 组合)

### 8y (2020-01-02 ~ 2026-04-30, n=1428)

| 来源 | Sharpe | Ann | DD | Ret | 配比 (HK/Am/Amr/zh/QQQ/GLD) |
|---|---|---|---|---|---|
| T+1 baseline ([[v5_t1_recalibration_2026-06]]) | +1.879 | +10.30% | -5.67% | +80.8% | 35/10/15/15/10/15 |
| **T+0 new (本)** | **+1.889** | +10.52% | -5.67% | +80.8% | **35/10/15/15/10/15** |
| Δ | **+0.010** | +0.22pp | 0 | 0 | **完全相同** |

### 4y (2022-04-30 ~ 2026-04-29, n=909)

| 来源 | Sharpe | Ann | DD | Ret | 配比 |
|---|---|---|---|---|---|
| T+1 baseline | +2.326 | +13.93% | -3.68% | — | 40/15/10/10/10/15 |
| **T+0 new (本)** | **+2.413** | +14.61% | -3.68% | +68.2% | **40/15/10/10/10/15** |
| Δ | **+0.087** | +0.68pp | 0 | — | **完全相同** |

### v5 实盘 baseline (HK20 / A_mom20 / A_mr10 / zhuang20 / QQQ15 / GLD15)

| 窗口 | T+1 Sharpe (旧) | T+0 Sharpe (新) | Δ |
|---|---|---|---|
| 8y | +1.74 | +1.740 | ≈0 |
| 4y | — | (重跑 dependency) | — |

HK 在 v5 实盘只占 20%，sleeve +0.065 Sharpe 被稀释 → 实盘 baseline 几乎不变。

## sleeve→portfolio 放大率

- **8y**: HK +0.065 sleeve × ~0.15 ≈ +0.010 portfolio ✓（与 [[zhuang_l6a_weights_2026-05]] ≈0.45× 同模式，本次更弱因 HK_mom vol 8.81% 大于 zhuang 3.94%）
- **4y**: HK +0.059 sleeve → +0.087 portfolio（放大率 1.47×，非线性 — 4y 窗口 HK 占 40%+ 权重对 frontier 边界更敏感）

## 关键结论

1. **v5 grid efficient frontier 形状不变**：T+0 vs T+1 双窗口 Top1 配比完全 identical, 说明 HK T+0 sleeve 改善是 marginal effect 不撬 frontier 拓扑
2. **HK_mom 25→35-40% 是唯一未落 yaml 改动**：T+1 / T+0 双窗口都共识 HK 顶 max_weight cap 40%（4y）或 35%（8y），属 PM 决策（Backstop #4）
3. **不需要重写 [[v5_efficient_frontier_2026-05]] / [[v5_t1_recalibration_2026-06]]**：grid 共识不被 T+0 改写
4. **A1' 饱和结论需补充审视**：原 [[a1prime_southbound_gate_falsified_2026-06]] 是 T+1 baseline 下 1.080→1.022 (-0.058)；T+0 下 baseline ~1.149 (4y)，gate 是否仍 falsify 不在本 PR 范围

## PM 决策待办（未自动改 yaml — Backstop #4）

| 选项 | 描述 | 8y 期望 Sharpe | 4y 期望 Sharpe |
|---|---|---|---|
| **A** v5 不动 (HK 20%) | 实盘 baseline | +1.74 | ~ |
| **B** HK 25→35% (v5 grid 8y 最优) | grid 推 | +1.89 | +2.30 |
| **C** HK 25→40% (v5 grid 4y 最优) | grid 推 | +1.88 | +2.41 |
| **D** 全套 grid 最优 (调 zhuang 砍 / GLD 增) | grid full | +1.89 | +2.41 |

任何 yaml 调整另走 AskUserQuestion 通道；本 memory 仅给数据。

## 5 条 Backstop 检查

- **#1 17 条证伪墙**：本 memory 是 T+0 grid 重校准，不撬墙 ✓
- **#2 双窗口同向 PASS**：grid 8y / 4y Top1 配比完全一致 ✓
- **#3 实盘 < 30 笔不撬 frontier**：实盘 baseline 不变，本 memory 只给 grid 数据 ✓
- **#4 PM 决策权**：列 ABCD 不自动改 yaml ✓
- **#5 采集 vs alpha 分离**：N/A ✓

## 关联

- [[hk_t0_recalibration_2026-06]] — HK sleeve T+0 +0.06 Sharpe (PR #31)
- [[v5_t1_recalibration_2026-06]] — v5 T+1 grid 前次推荐 (HK 顶 40%) — 本次确认
- [[v5_efficient_frontier_2026-05]] — v5 efficient frontier 原版 (T+0 zhuang 假设, supersede)
- [[a1prime_southbound_gate_falsified_2026-06]] — A1' 饱和待补审 T+0 baseline 下结论
- `data/backtest/portfolio_p1_V5_HK_T0_4Y.{md,json}` + `_8Y.{md,json}` — 双窗口 grid 产物
- `data/backtest/_hk_t1_baseline_backup/` — T+1 HK_mom equity 备份

**Why:** T+0 改动落到 HK sleeve 后必须做组合层 grid 校准, 确认是否撬 v5 efficient frontier; 答案是不撬，配比形状不变, 改善被组合层稀释到 marginal (+0.010 portfolio Sharpe). v5 仍是 efficient frontier (T+0 / T+1 双 baseline 下).
**How to apply:** 未来类似 sleeve 层校准（如 v5 T+1 zhuang 重校准、未来真做空 leverage 落地）后, 走同样模板: (1) 备份旧 equity (2) 重跑 sleeve backtest (3) 重跑组合 grid 双窗口 (4) 列 PM ABCD 选项不改 yaml.
