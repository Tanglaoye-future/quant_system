---
name: portfolio-p1-p2-weights-capacity-2026-05
description: 2026-05-27~28 组合层优化 — P1 6-asset 权重 grid search (当前 1.86 → 最优 2.22 Sharpe) + P2 zhuang capacity 压测 (40% 配比在 ≤30M AUM 成立)
metadata:
  type: project
---

## 背景

L9-A 落地后转向组合层（[[equity_factor_l9_partial_regime_2026-05]] 结论：单策略迭代撞墙，边际研究价值在 portfolio level）。两步：P1 权重重算 + P2 zhuang capacity 验证。

## P1: 6-asset 权重 grid search

脚本 `scripts/portfolio/run_p1_weight_grid_search.py`。读 6 资产 daily equity → 5% step / 单资产 cap 40% / sum=1 grid（27,237 组合）→ 多目标 top。

**窗口受 zhuang 起点限制 = 2020-01-03 → 2026-04-29（1441 天 ~5.7y）**。zhuang 数据 2020 才有，无法做满 8y。

### 单资产 metrics (2020-2026, L9-A era)

| 资产 | Sharpe | 年化 | DD | 年化波动 | 备注 |
|---|---|---|---|---|---|
| HK_mom | 1.170 | +10.97% | -8.96% | 9.38% | 第二强 + 流动性最好 |
| A_mom (L9-A) | 0.528 | +5.46% | -14.74% | 10.33% | L8D2 era 是 0.446 |
| A_mr | 0.250 | +2.06% | -10.84% | 8.22% | solo 弱但 hedge 价值 |
| zhuang | 1.348 | +4.77% | -3.38% | 3.54% | **钻石**：高 Sharpe 极低 DD/vol |
| QQQ | 0.920 | +23.47% | -35.12% | 25.50% | 高收益高 vol |
| GLD | 1.092 | +20.37% | -22.00% | 18.66% | 强周期 alpha |

注：zhuang daily-return 年化 Sharpe 1.34，但其 metrics.csv 自报 0.74 —— 差异来自 zhuang 大量空仓（91 笔 × 4.6 天 ≈ 420/1545 天在场），naive sqrt(252) 年化虚高。**做相对比较（retention %）时无碍，做绝对 Sharpe 解读时要打折**。

### 相关性（全部 <0.20，教科书级多元化）

最大 |ρ| 是 A_mom↔A_mr **-0.152~-0.196**（A 股内部对冲）。QQQ↔GLD +0.168。zhuang 与所有资产 ≈0。

### 当前 vs 最优权重

| | HK | A_mom | A_mr | zhuang | QQQ | GLD | Sharpe | Ann | DD |
|---|---|---|---|---|---|---|---|---|---|
| **当前 deployment v4** | 20 | 20 | 10 | 20 | 15 | 15 | **1.86** | +11.0% | -6.1% |
| **L9-A Top Sharpe** ⭐ | 25 | 10 | 10 | **40** | 5 | 10 | **2.22** | +8.6% | -2.7% |
| L8D2 Top Sharpe (对照) | 25 | 5 | 15 | 40 | 5 | 10 | 2.19 | +8.4% | -2.6% |
| Top Annual Ret | 20 | 0 | 0 | 0 | 40 | 40 | 1.44 | +19.7% | -19.2% |
| Min DD | 25 | 5 | 20 | 40 | 5 | 5 | 2.12 | +7.5% | -2.3% |

**核心结论**：
1. **重权重 Sharpe 提升 +0.36（1.86→2.22，+19%）** — 比 L9-A 单策略 +0.086 大 4 倍，验证"边际价值在组合层"
2. **A_mom 当前 20% 过配，最优 10%**（L9-A 把它从 5%→10% slot 抬升，这是 L9-A 真实组合价值）
3. **A_mr 被低估**：solo 0.25 平庸，但 -0.15 负相关 hedge → 配 10-15%
4. **QQQ 当前 15% 过配，最优 5%**（25.5% vol 拖 Sharpe）
5. **zhuang 40% cap binding** — grid 想给更多 → 必须 capacity 验证（= P2）
6. 最优解非常稳健：top-10 全围绕 HK 20-30 / A_mom 5-15 / A_mr 10-20 / zhuang 35-40 / QQQ 5 / GLD 10 中心

产物：`data/backtest/portfolio_p1_L8D2.md` / `portfolio_p1_L9A.md` (+.json)

## P2: zhuang capacity 压测

脚本 `scripts/portfolio/run_p2_zhuang_capacity.py`。Almgren 平方根冲击律：impact = 0.5 × σ_daily × sqrt(参与率)，参与率 = 仓位市值 / 20日ADV，entry+exit 双边各扣。

**关键发现：zhuang universe 实际 ADV 中位 200M RMB**（50亿-2000亿市值中小盘，不是仙股），capacity 比直觉好很多。σ_daily 中位 2.6%，单仓中位 6.6%。

### zhuang @ 40% 权重 capacity tier

| 总 AUM | sleeve | 净 Sharpe | 保留 | breach | 最大参与率 | 判定 |
|---|---|---|---|---|---|---|
| ≤10M | ≤4M | 1.31 | ≥97.7% | 0 | <10% | 完全免费 |
| **30M** | 12M | 1.288 | **96.0%** | 1 | 27.9% | ✅ 舒适 |
| 100M | 40M | 1.244 | 92.8% | 3 | 92.9% | ⚠️ 需拆单监控 |
| 300M | 120M | 1.173 | 87.5% | 11 | 278% | ❌ 压回 20-25% |
| 1000M | 400M | 1.033 | 77.0% | 32 | 928% | ❌ 不可行 |

**capacity 结论**：
- **总 AUM ≤ 30M RMB → 40% zhuang 完全现实**（保留 96%，≤1 笔拆单）
- 30-100M → 可行但 3 笔 breach 要拆 2-3 天执行
- >100M → zhuang 必须压回 20-25%，grid 的 40% 是空中楼阁

deployment_plan 是个人多账户配置，大概率在 1-30M RMB 区间 → **40% zhuang 落地无障碍**。

产物：`data/backtest/zhuang_capacity_p2.md` (+.json)

### 压测模型的诚实局限

1. **Y=0.5 是假设**：A 股小盘股在压力市冲击可能更高
2. **91 笔样本薄**：breach 分析被最差单只标的主导
3. **ADV 用历史实现成交量**：DD 期间量能枯竭，实际冲击会 spike（模型未捕捉）
4. **zhuang 6y 窗口**（2020 起），未含 2018-19；P1 全组合也受此限

## P1+: 跨区间稳健性检验（落 v5 前的最后一道关）

脚本 `scripts/portfolio/run_p1plus_robustness.py`（import P1 脚本的 load+grid 函数）。

### [1] 固定权重 v4 vs v5 跨 5 个市场段

| 市场段 | v4 Sharpe/DD | v5 Sharpe/DD | ΔSharpe |
|---|---|---|---|
| 2020 疫情 | +1.463/-5.96% | +1.082/-2.29% | -0.381 |
| 2021 牛/顶 | +1.586/-2.90% | +2.042/-2.58% | +0.455 |
| **2022 熊** | **-0.621/-5.81%** | **+0.466/-2.29%** | **+1.087** |
| 2023-24 震荡 | +3.048/-3.18% | +2.871/-2.68% | -0.177 |
| 2025-26 反弹 | +2.683/-4.18% | +3.273/-2.50% | +0.590 |
| 全窗口 | +1.861/-6.07% | +2.222/-2.68% | +0.360 |

**决定性发现**：2022 熊市 v4 是 **-0.621（亏损年）**，v5 是 **+0.466（盈利年）**。高 zhuang 配比把亏损年翻成盈利。v5 在**每个**市场段 DD 都更小。v5 只在 2020/2023-24 beta 强反弹段少赚（绝对 Sharpe 仍 >1.0/>2.8）。

### [2] 各段各自 grid 最优（过拟合检验）

| 段 | 最优 Sharpe | HK/A_mom/A_mr/zhuang/QQQ/GLD |
|---|---|---|
| 2020 | 1.938 | 0/5/30/**40**/10/15 |
| 2021 | 2.886 | 30/0/15/**40**/15/0 |
| 2022 | 1.965 | 40/5/30/**25**/0/0 |
| 2023-24 | 3.275 | 20/15/0/**40**/15/10 |
| 2025-26 | 3.418 | 40/0/5/**40**/5/10 |
| 全窗口 | 2.222 | 25/10/10/**40**/5/10 |

**zhuang 40% 是 5 段里 4 段的共同最优**（仅 2022 要 25%，但 v5 固定 40% 在 2022 仍 +0.466 远胜 v4）→ 非过拟合。HK/A_mr regime-dependent 漂移大，但全窗口最优落在各段质心。

### [3] cap sensitivity

| cap | Sharpe | zhuang |
|---|---|---|
| 40% | 2.222 | 40% |
| 50% | 2.274 | 50% |
| 60%+ | 2.282 | 55% (plateau) |

解 cap zhuang 想到 55% 封顶；40→55 只 +0.06 Sharpe（40% 已捕获理论上限 98%）。55% 撞 P2 capacity + 集中度铁律 → **40% 是正确实操 cap**。

产物：`data/backtest/portfolio_p1plus_robustness.md` (+.json)

## 落地：v5（2026-05-28）

[[deployment_plan_2026-05]] 已更新到 v5：**HK 25 / A_mom 10 / A_mr 10 / zhuang 40 / QQQ 5 / GLD 10**。

- **trade-off 标注**：v5 防守倾斜，beta 强反弹段少赚；若判断持续大牛市可回调 QQQ/GLD
- **capacity 前提**：40% zhuang 仅 ≤30M AUM 无障碍；>100M 压回 20-25% 给 HK

## 后续候选（用户未指）

- **P3**：A_mr / Options BCS 量化基线（仍是数据黑洞）
- **P4**：A_mr 优化（solo 0.25 但有 hedge 价值，提到 0.4-0.5 组合还能上台阶）
- **实盘验证**：v5 跑 3 个月后用真实 daily return 对照回测 2.22 Sharpe

**Why**: 用户要"从量化对冲基金视角优化策略"；分析显示组合层重权重 (+0.36 Sharpe) 远比单策略迭代 (+0.086) 高效，且 zhuang capacity 在个人 AUM 下不构成约束。
**How to apply**: 下次涉及组合权重 / 配资 / zhuang 占比 / capacity 讨论，先读本 memory + [[deployment_plan_2026-05]]；落新权重前确认用户实际 AUM 区间（<30M 则 40% zhuang OK，>100M 必须压回）。grid search / capacity 脚本可复用 `scripts/portfolio/run_p1_*.py` / `run_p2_*.py`。
