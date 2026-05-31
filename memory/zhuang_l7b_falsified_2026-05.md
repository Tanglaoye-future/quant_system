---
name: zhuang-l7b-score-falsified-2026-05
description: L7-B 反向探索 — 放宽 accumulation_score_entry (70→67/65) 3y Sharpe 单调向下 (1.505→0.925→0.843)，win rate 从 51.7% 跌到 36.8%；与 L7-A 联合得到 "L1-E 是 sleeve 当前架构 sweet spot"
metadata:
  type: project
---

## 一句话结论

放宽 score 阈值确实增加 trades 数（58→114→169）和减少 idle 时间（71%→57.5%→52.9%）— **但放出来的低分机会全是低质量信号**，Sharpe 单调向下，win rate 直接跌穿 15pp。L7-B 证伪。

## 实验设置

- **驱动**: L7-A 揭示 cap 6 永不 binding (mean concurrent 0.5)，反向假设 — 把 score 阈值放宽看是否能在不显著掉 win rate 下用上闲置仓位
- **窗口**: 3y (2022-01-01 → 2024-12-31)
- **权重 (yaml)**: L6-A equal (0.20×5)
- **cap (yaml)**: position_max_count=6 (L7-A 证非瓶颈)
- **cases**: accumulation_score_entry ∈ {70 (control), 67, 65}，pos≥0.4 不变

## 结果（单调向下）

| score | Sharpe | Ret% | DD% | N | win% | pf | cMean | idle% |
|---|---|---|---|---|---|---|---|---|
| **70** (L1-E control) | **+1.505** | +25.37 | -2.63 | 58 | 51.7% | 3.24 | 0.5 | 71.0% |
| 67 | +0.925 | +16.70 | -3.86 | 114 | 36.8% | 2.45 | 1.14 | 57.5% |
| 65 | +0.843 | +15.87 | -4.71 | 169 | 36.7% | 2.19 | 1.81 | 52.9% |

## 单调劣化分析

| 指标 | 70 → 67 | 67 → 65 | 总劣化 (70→65) |
|---|---|---|---|
| Sharpe | -0.580 | -0.082 | **-0.662** |
| Win rate | -14.9pp | -0.1pp | **-15.0pp** |
| Profit factor | -0.79 | -0.26 | **-1.05** |
| DD | -1.23pp | -0.85pp | **-2.08pp** |
| Trades | +96.6% | +48.2% | +191% |

**机制**: 大部分 alpha 来自 score 70-100 区间。score 67-70 的"中等吃货分"机会 win rate ~37%（接近随机 + 庄股流动性弱被滑点磨蚀），加进来等于稀释了 score≥70 集群的高纯度收益。

## 双向证伪联合结论（L7-A + L7-B）

**L1-E 是 zhuang sleeve 在当前架构下的 efficient frontier**：
- L7-A: cap 已经过大，扩 cap 零边际效应
- L7-B: score 阈值已经在拐点，放宽 score 单调坏
- **未来 zhuang alpha 必须靠外部信号增量** — 不能再做入场参数 sweep
- 候选方向（按 ROI）：
  1. L9-A 加 fundamentals 因子做正向加权（不是 gate，避免 L2/L3 负转移）
  2. 新维度信号（盘后大宗 / 沪深通流入 / 龙虎榜机构席位）
  3. 出场端 L4 系列还有空间（已 combo4 落地，但能否再压 DD）

## 不要做（避免下次重蹈）

- 不要再 sweep accumulation_score_entry — 双向都已锁死最优
- 不要再 sweep entry_price_position_min 单独 — L1A 系列已试 0.3/0.4/0.5/0.66, L1-E 0.4 是 sweet spot
- 不要假设"更多 trades = 更多 alpha" — 庄股低分机会 win rate ~36-37% 接近反向

## 时间成本

- 工程: ~8 min（写 sweep 脚本加 concurrent_stats 工具）
- 计算: ~15 min（3 case 串行）
- 总: ~23 min

**Why:** L7-A 揭示 cap 不 binding 后, 自然假设是反方向（放宽 score）。L7-B 实测把这个最后的入场参数自由度也封死，明确告诉未来 session "zhuang sleeve 在 strategy 层已无 parameter sweep alpha"。
**How to apply:** 未来 zhuang 优化提案如果还在动 `accumulation_score_entry` / `entry_price_position_min` / `position_max_count`，直接 reject — 引用本 memory + [[zhuang_l7a_falsified_2026-05]] + [[zhuang_l1_l2_l3_experiments_2026-05]]。
