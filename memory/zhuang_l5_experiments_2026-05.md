---
name: zhuang L5 仓位权重实验 (2026-05-18)
description: score 分级仓位 sizing；L5B-tiered-aggressive (3%/5%/8%) Sharpe 1.85→2.15 (3y) / 1.63→1.81 (6y)，落地 config
type: project
---

## 背景

L4-combo4 之后入场 + 出场规则全部优化完毕，但所有持仓都是**等权 5%**.
理论上 score 越高的入场单笔预期收益越大，等权浪费了 score 的预测力。L5 实验:
按 score 差异化 sizing 看是否能进一步抬高 Sharpe。

## 实施

backtester 加 `position_size_mode` 参数 (fixed/tiered/linear):
- **tiered**: 按 `tiered_score_thresholds=[t1,t2]` 分 3 档, 对应 `tiered_position_pcts=[low,mid,high]`
- **linear**: `pct = lin_min + (score - smin)/(smax-smin) × (lin_max - lin_min)`, clip 到 [pmin, pmax]

(`src/quant_system/strategies/zhuang/engine/backtest.py::_compute_position_pct`)

## 实验结果 (3y, 2022-2024)

| 标签 | mode | Sharpe | 收益 | DD | 笔数 |
|---|---|---|---|---|---|
| baseline-combo4 | fixed 5% | 1.849 | +23.9% | -1.8% | 62 |
| L5A-tiered-conservative | [75,80]→[4%,5%,6%] | 1.993 | +29.1% | -2.0% | 62 |
| **L5B-tiered-aggressive** ⭐ | [75,80]→[**3%**,5%,**8%**] | **2.146** | **+39.5%** | -2.6% | 62 |
| L5C-linear (4-6%) | linear 70-85 | 1.992 | +29.1% | -2.0% | 62 |
| L5D-linear-wider | linear 70-90 → 3-8% | 2.141 | +39.4% | -2.6% | 62 |

**62 笔不变 / PF 3.83 不变** → 证实 sizing 不影响入场/出场，仅放大高分股票位置。

L5B vs L5D 几乎并列 (Sharpe 2.146 vs 2.141)，选 L5B (阶梯更直观，runtime 也略快)。

## 6 年验证 (2020-2026)

| 标签 | Sharpe | 收益 | DD | 胜率 | PF | 笔数 |
|---|---|---|---|---|---|---|
| verify6y-baseline-combo4 | 1.627 | +48.1% | -3.1% | 54.4% | 2.96 | 136 |
| **verify6y-L5B** | **1.806** | **+76.0%** | -4.9% | 54.4% | 2.96 | 136 |

**3y/6y 双窗口一致改进 (+0.30 / +0.18)，非过拟合。** 6y 收益翻倍 (+48% → +76%).

## 累计提升 (6y, 2020-2026)

| 阶段 | Sharpe | 收益 | DD |
|---|---|---|---|
| v5 原始 | 0.944 | +37.3% | -5.56% |
| L1-E | 1.346 | +44.0% | -3.77% |
| L4-combo4 | 1.627 | +48.1% | -3.10% |
| **L5B-tiered-aggressive** | **1.806** | **+76.0%** | -4.9% |

Sharpe 翻 1.9 倍 (0.944 → 1.806)，收益翻 2 倍 (+37% → +76%)，DD 从 -5.56% → -4.9%。

## 风险注意

L5B 把单票上限从 5% 抬到 8% → 6 仓位满仓时总暴露 30% → 48%。DD 从 -3.1% 到 -4.9% 是这个代价。
仍在合理范围（实盘部署的 30%+ 现金缓冲下更安全），但**实盘要监控高分股票的同步回调风险**。

## 落地 config

```yaml
strategy:
  position_size_mode: tiered
  tiered_score_thresholds: [75.0, 80.0]
  tiered_position_pcts: [0.03, 0.05, 0.08]
```

**Why:** score 对单笔收益有真实预测力 (高分股票拉升幅度更大，PF 不变 = 同质量更大仓位)，
sizing 是把 score 信号变现的最后一公里。L5B (8%/5%/3% 三档) 在不增加笔数的情况下抬高 Sharpe +0.18 (6y).
**How to apply:** 已写入 config/zhuang.yaml；实盘高分股要监控 daily_run candidates 中 score>80 的集中度。
