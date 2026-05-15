---
name: 多策略叠加 + Vol targeting 实验记录 2026-05-15
description: A 股 mean-reversion 子策略 + 杠杆 / vol targeting 分析。结论：multi-strat 加 0.027 Sharpe，杠杆只放大收益不改 Sharpe
type: project
---

## 关键发现

### 1. Mean-reversion 子策略实现（commit 后续）

`MeanReversionStrategy` 类（`quant_system/engine/strategy.py`）：
- 入场：RSI(14) < 30 + close > MA200 + volume >= MA20
- 出场：RSI > 55 / 持有 > 10 日 / 5% 止损 / MA200 跌破
- 注册名：`mean_reversion`，CLI `--strategy mean_reversion`

A 股 8 年 solo 回测：
- Sharpe **0.06** / FAIL
- 总收益 +19% (8 年) / 仅匹配 HS300 同期 +17.6%
- 但胜率 **53.6%** + 盈亏比 **2.01** — 信号本身有效，触发太少（112 笔）

### 2. 多策略组合关键证据

A_mom (bottomup_timing) vs A_mr (mean_reversion) **相关性 -0.172**（负相关！）。

| 单纯 A_mom + A_mr 组合 | Sharpe | DD |
|---|---|---|
| 70 mom + 30 mr | **0.559** | -9.72% |
| 80 mom + 20 mr | 0.544 | -11.78% |
| 95 mom + 5 mr | 0.515 | -14.88% |
| **A_mom solo** | **0.505** | -15.96% |

mean-reversion 即便 solo Sharpe 仅 0.16，加入组合 **每个权重档位都提升 A 股部分的 Sharpe**。

### 3. 5-asset 最优组合（含 mean-reversion）

| 配置 | Sharpe | 总收益 | DD | 波动 |
|---|---|---|---|---|
| 前 4-asset 35/30/15/20 | 1.198 | +108.9% | -8.88% | 6.65% |
| **新 5-asset 25/25/15/15/20** | **1.225** ⭐ | +102.0% | **-7.94%** ⭐ | **6.11%** ⭐ |

权重：HK 25% + A_mom 25% + A_mr 15% + QQQ 15% + GLD 20%

**罕见组合**：Sharpe ↑、DD ↓、Vol ↓，仅总收益略减 6.9pp。

### 4. Vol targeting 测试结果（leverage 分析）

对最优 5-asset 组合应用动态 vol targeting（rolling 60d std → 缩放至目标 vol，借贷成本 2%/年/leverage）：

| 配置 | Sharpe | 总收益 | DD | 平均杠杆 |
|---|---|---|---|---|
| 5-asset 基线（无杠杆）| **1.225** | +102% | -7.94% | 1.0 |
| vol target 8% / max 1.5 | 1.172 | +125% | -12% | 1.31 |
| vol target 10% / max 1.5 | 1.202 | +147% | -12.83% | 1.42 |
| vol target 12% / max 2.0 | 1.192 | **+199%** | -17.25% | 1.83 |
| vol target 12% / max 3.0 | 1.161 | +225% | -19.88% | 2.16 |

**关键洞察**：
- Vol targeting **不提升 Sharpe**（教科书结果：固定权重 + 线性 scaling = Sharpe 不变）
- 借贷成本侵蚀 Sharpe 边际（-0.02 ~ -0.07 取决于平均杠杆）
- 但**绝对收益 scale up**（+50% to +120%）至代价更大 DD

## 实施建议

### 推荐方案：5-asset 无杠杆（保守）

更新 `memory/deployment_plan_2026-05.md`：

| 账户 | 占比 |
|---|---|
| HK 港股账户（hk_share daily_run） | **25%** |
| A 股账户 / 子策略 A — momentum（bottomup_timing daily_run）| **25%** |
| A 股账户 / 子策略 B — mean-reversion（mean_reversion daily_run）| **15%** |
| US ETF 账户（QQQ 持有） | **15%** |
| 黄金 ETF 账户（GLD / 518880 持有） | **20%** |

A 股账户内 **同时跑两个 daily_run**（不同子资金）：
```bash
# A_mom (250K)
python scripts/daily_run.py --market a_share --strategy bottomup_timing --capital 250000

# A_mr (150K) — 在同账户内或分账户
python scripts/daily_run.py --market a_share --strategy mean_reversion --capital 150000
```

### 不推荐方案：杠杆

- vol targeting 不改 Sharpe，只放大收益和 DD
- 实盘融资有真实成本（券商 5%+ vs 测算 2%）+ margin call 风险
- 当前 5-asset 无杠杆 Sharpe 1.225 + DD -7.9% 已属 ** excellent**，不必冒险

## 后续可探索（按 ROI）

| 方向 | 预期 ΔSharpe | 评估 |
|---|---|---|
| HK mean-reversion 策略（同方法） | +0.02 | 类似 A 但 HK 数据稀疏，价值有限 |
| 事件驱动策略（年报/季报 drift）| +0.05 | 需新数据 wiring |
| Pairs trading（AH 套利）| +0.03 | 需衍生品账户 |
| ML 因子（XGBoost）| +0.0~0.3 | 过拟合风险高 |
| 加 IEF（中期债，替代 TLT）| +0.0~0.05 | 利率敏感度较低，值得一试 |

## 已穷尽 / 不推荐方向

- 真做空 leverage（HSCEI / IF 期货）：已分析显示 Sharpe 不增
- Vol targeting：已分析显示 Sharpe 不增
- us_share 主动策略：已 deprecated

**Why:** 2026-05-15 multi-strategy + leverage 实验，证实多策略叠加 +0.027 Sharpe / DD 改善，杠杆只放大不改 Sharpe。
**How to apply:** 实盘部署优先 5-asset 无杠杆方案；A 股账户跑两个 daily_run（momentum + mean-reversion）。
