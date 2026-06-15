---
name: v5-efficient-frontier-2026-05
description: 2026-05-30 — 5 条组合层优化路径全证伪 (v6 grid/regime/+IBIT/+TLT/+CSI1000)；v5 (HK25/A_mom10/A_mr10/zhuang40/QQQ5/GLD10) 2.22 Sharpe 是真 efficient frontier，下阶段转 3 月实盘验证收集真数据
metadata:
  type: project
---

> **[SUPERSEDED 2026-06-15]** zhuang 弃用 ([[zhuang-deprecated-2026-06]]) + 用户决定加入加密 10% → v5 框架全失效。新 efficient frontier 见 [[v7-efficient-frontier-2026-06]] (HK50/A_mom20/A_mr0/QQQ10/GLD10/IBIT10)，下方 v5 内容仅历史归档。本 memory 5 条证伪 (v6 grid/regime/+IBIT/+TLT/+CSI1000) 中的 IBIT/TLT/CSI1000 部分对 v7 仍有参考价值（v7 选 IBIT 与彼时 IBIT 5/10% 证伪表面矛盾 — 但用户在 v7 是固定加密 10% 不入 grid，避免了同款证伪）。

## 5 条组合层优化路径全证伪

| 路径 | v5 base | 改后 | Δ Sharpe | 状态 |
|---|---|---|---|---|
| v6 grid 砍 A_mr | 2.22 | 2.12 | **-0.10** | ❌ |
| v6 regime overlay 动态切 | 2.231 | 2.142 | **-0.089** | ❌ |
| +5% IBIT (BTC) | 3.283 (短) | 3.005 | **-0.277** | ❌ |
| +5% TLT (长债) | 2.231 | 2.098 | **-0.133** | ❌ |
| +5% CSI1000 (A 小盘) | 2.231 | 2.128 | **-0.103** | ❌ |

每条都试 +10% 配比，Δ Sharpe 更负（-0.34 ~ -0.87）。

## 为什么 v5 是 efficient frontier

新资产要拉升 v5 Sharpe 2.22 必须满足任一：
1. **单 Sharpe ≥ 2.0** AND ρ < 0.3（高质量但不重复）
2. **真 uncorrelated (ρ < 0.10 与所有现有资产)** AND 单 Sharpe ≥ 1.0

3 候选都不满足：
- IBIT: Sharpe 0.66 + 与 QQQ ρ 0.42（机构买盘共振）— 不够纯
- TLT: 单 Sharpe -0.19（加息周期长债大跌）— 拖累
- CSI1000: Sharpe 0.28 + 与 A_mom ρ 0.20 + GLD ρ 0.14 — 平庸

满足两条同时的资产**极少**。zhuang (Sharpe 1.81 + ρ ≤ 0.06) 是教科书级稀缺；已经在 v5 里 40%（capacity 顶满）。

## PM 真相 — 转实盘窗口

3 个月实盘 (2026-05-30 起) 是必经路径，原因：
1. **回测 Sharpe 2.22 vs 实盘期望 1.0-1.5**：8y 数据足够、组合稳健，但实盘必有 slippage + 摩擦 + execution lag + capacity 渗透
2. **未来 alpha 的真信号来自实盘**：哪个 sleeve 偏离回测、哪个相关性变了，都是更精确的优化输入
3. **再投工程在回测层是 sunk cost**：5 条路径已证组合层无剩余 alpha

## 3 月实盘验证 KPI checklist

### 月度采集（每月最后交易日）

| KPI | 目标 | 警报阈 |
|---|---|---|
| 各账户 MTD 收益 | 与回测同期方向一致 | 偏离 ±5pp 触发诊断 |
| 各账户 MTD Sharpe (滚动 30d) | HK ≥ 0.8, A_mom ≥ 0.3, zhuang ≥ 1.5 | < 0.5 任一 sleeve 暂停 |
| 组合月收益 | +0.7% (年化 8.6% / 12) | < -2% 立即诊断 |
| 跨账户日收益 ρ (滚动 60d) | < 0.30 | > 0.50 重评配比 |
| zhuang 总 AUM 利用率 | < 30M RMB cap | > 30M 把 zhuang 压回 20-25% |

### 3 月节点（2026-08-30）触发条件

判定实盘 vs 回测匹配度：
- **匹配** (年化 Sharpe ∈ [1.0, 2.5]): 维持 v5，继续运行
- **大幅低于** (年化 Sharpe < 0.5): 单独审 sleeve 是否有 bug；可能 yfinance 数据延迟 / journal 漏记 / 实盘 slippage 比模型高
- **大幅高于** (年化 Sharpe > 2.5): 警惕 survivorship bias 或样本运气；不增 leverage

### 季度再平衡 (每季末)

`deployment_plan_2026-05.md` 已规定：偏离目标 ±5pp 才动；transfer 时按本币计价。

### 月度报告模板（写到 memory 即可）

```
# 实盘 month <YYYY-MM> 报告
窗口: <month start> → <month end>
- 各账户 MTD 收益 + Sharpe
- 组合收益 vs 回测同期
- 跨账户相关性 60d 滚动
- 异常告警: <list>
- 决策: 维持 / 暂停 sleeve / 重平衡 / 触发深度诊断
```

## 不要做（基于 2026-05-30 验证 + 之前 4 月经验）

- 不要继续在组合层试新权重 / 新资产 — 5 条路径全证伪
- 不要在 strategy 层继续优化 A_mr — 4 条路径全证伪 ([[a_mr_v2_falsified_2026-05]])
- 不要因为单月跑赢回测就增 leverage — 单月样本太小
- 不要因为单月跑输回测就立刻调权重 — 季度再平衡周期是缓冲

## 真正的下一步候选（实盘 3 月后再决策）

按 [[a_mr_v2_falsified_2026-05]] 末尾列出，按 ROI 排：
1. **zhuang strategy 层 L6+**（Sharpe 1.81 → 2.0+ 直接拉组合 — 因为 40% 配比放大）
2. **fundamentals 升级** (L9-A 因子加 ROIC / 应收增速)
3. **HK 真做空 leverage** (融券/期货 alpha 放大)

这些都比"再加新资产"或"再切权重"高 ROI。

## 产物

- 验证脚本：`scripts/portfolio/run_v6_new_assets_addition.py`
- 数据：`data/backtest/portfolio_v6_new_assets.md` (+.json)

**Why:** 5 条组合层路径全死是非常高价值的 PM 结论 — 它告诉我们 v5 不是凑合可用，而是真正的 efficient frontier；下一步应该是实盘观察，不是更多回测。
**How to apply:** 任何"调权重 / 加资产 / 砍 sleeve"提议都先指本 memory；下次有时间投工程，优先级是 (1) 实盘 3 月报告 (2) zhuang L6+ (3) fundamentals 升级，不是组合层重 grid。
