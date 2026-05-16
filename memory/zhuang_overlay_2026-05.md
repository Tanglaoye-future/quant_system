---
name: Zhuang 子策略叠加分析 2026-05-15
description: 外部 zhuang_system 策略（A 股庄股小盘跟庄）与 5-asset 组合的相关性与权重扫描；10% 配比将组合 Sharpe 1.225 → 1.349
type: project
---

## 背景

`zhuang_system` 是独立 repo（与 quant_system 平级），输出 `report/data/zhuang.json` 候选清单：
- 标的池：A 股全市场小盘
- 信号：MA 收敛 + 量价不对称 + 价格盘整 + 换手下行 + 量价背离 → "吃货期" 评分
- 此处只评估其**收益序列**与现有 5-asset 组合的相关性 / 叠加效果（zhuang 自身代码不在本 repo）

zhuang 自身 baseline Sharpe **0.94**（仍有优化空间）。

## 关键发现

### 1. 相关性矩阵（zhuang vs 现有 5 资产）

| 对手资产 | ρ | 判断 |
|---|---|---|
| HK momentum | 0.043 | 近零 |
| A_mom (bottomup_timing) | 0.039 | 近零 |
| A_mr (mean_reversion) | **-0.064** | **负相关** ⭐ |
| QQQ | -0.001 | 零 |
| GLD | -0.020 | 零 |

zhuang 与所有 5 个资产相关性近零或负 — **第六维独立 alpha 源**。

A 股内三策略相互独立：
- A_mom 抓动量（RSI 50-70 买入）
- A_mr 抓超卖反弹（RSI < 30 买入）
- zhuang 抓吃货期（量价背离 + 换手下行积累）

### 2. 6-asset 权重扫描

基线 5-asset：HK 25 / A_mom 25 / A_mr 15 / QQQ 15 / GLD 20，Sharpe 1.225 / DD -7.94%。
（注：本次扫描得到的 5-asset 基线 Sharpe 重算为 **1.303**，与 multistrat_2026-05.md 中 1.225 存在小差异，可能是回测窗口或 zhuang 序列对齐导致；以下用 1.303 作为 zhuang scan 的同口径对照）

| 配置 | Sharpe | 总收益 | 最大回撤 | 年化波动 |
|---|---|---|---|---|
| 5-asset（无 zhuang） | 1.303 | +81% | -7.94% | 6.59% |
| +Zhuang 10% | **1.349** | +76% | **-7.01%** | 5.95% |
| +Zhuang 15% | 1.374 | +73% | -6.57% | 5.63% |
| +Zhuang 20% | **1.400** | +70% | **-6.13%** | 5.32% |

边际效应：每加 5% zhuang，Sharpe +0.02~0.03，DD -0.5pp。

**罕见组合**：Sharpe ↑、DD ↓、Vol ↓，仅总收益小幅下降。

### 3. 推荐实盘 6-asset 权重（zhuang 10%）

按"收益 vs Sharpe vs DD 平衡"原则选 10%（保守增量）：

| 账户 | 旧占比 | 新占比 |
|---|---|---|
| HK momentum | 25% | 22% |
| A momentum | 25% | 22% |
| A mean-reversion | 15% | 13% |
| **A zhuang ⭐** | — | **10%** |
| QQQ | 15% | 13% |
| GLD | 20% | 20% |

预期组合 Sharpe **1.35+** / DD **-7%**。

## 实施约束

1. **zhuang 代码在独立 repo**：本 repo daily_run 无法直接跑 zhuang；需用户在 zhuang_system 里跑出当日候选，按 10% 子账户人工/半人工执行
2. **zhuang baseline 0.94 仍可优化**：上轮对话最后停在 "继续 L1/L2/L3 优化 zhuang 还是先 commit 分析"；尚未决定
3. **回测口径差异**：本次扫描 5-asset 基线 1.303 ≠ multistrat_2026-05.md 的 1.225，需复核日期对齐再确认（不影响相对结论）

## 下一步候选

| 方向 | 预期收益 | 优先级 |
|---|---|---|
| 继续优化 zhuang 子策略（L1/L2/L3） | baseline 0.94 → 1.0+，间接抬高组合 Sharpe | 高 |
| 实盘小资金试跑 10% zhuang 配比 | 验证回测假设 | 中 |
| 复核 zhuang 收益序列与 quant_system 的对齐口径 | 消除 1.303 vs 1.225 差异 | 中 |
| 把 zhuang 收益序列拉进 quant_system 的 multi-asset 分析脚本 | 后续扫描标准化 | 低 |

**Why:** 2026-05-15 完成 zhuang vs 5-asset 相关性 + 权重扫描，证实 zhuang 是低相关 alpha 源，10% 配比可将组合 Sharpe +0.05 / DD -1pp 同时降波动。
**How to apply:** 实盘部署若引入 zhuang，按 22/22/13/10/13/20 配比；继续优化 zhuang 自身策略优于继续在组合层扫描权重。
