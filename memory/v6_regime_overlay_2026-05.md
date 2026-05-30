---
name: v6-regime-overlay-2026-05
description: 2026-05-30 — v6 HS300+HSCHK100 双 MA200 regime gate 动态权重，全窗口 Sharpe 2.142 < v5 静态 2.231（ΔSharpe -0.089）→ v5 已是 efficient frontier，组合层动态化不提升；2025-26 反弹段 -0.40 是关键短板（月末 rebalance lag）
metadata:
  type: project
---

## 起点

[[portfolio_p1_p2_weights_capacity_2026-05]] P1+ 显示 2022 熊市 v4→v5 ΔSharpe **+1.087**，PM 假设动态权重可以再榨 0.1-0.2 Sharpe。

## 设计

`scripts/portfolio/run_v6_regime_overlay.py`：
- regime gate: HS300 close > MA200 **且** HSCHK100 close > MA200 → bull；任一 ≤ → defensive
- bull / defensive 子集分别 grid search 最优权重（共享 cap: HK 40 / A_mom 30 / A_mr 20 / zhuang 40 / QQQ 20 / GLD 25）
- 月末重平衡：上月末 regime 决定下月权重（避免日频切换摩擦）

## 数据 (2020-01-03 → 2026-04-29, 1441 天)

- bull 天数 653 (45.3%)
- defensive 天数 788 (54.7%)

## 子集最优权重（in-regime metrics）

| Regime | n_days | Sharpe | Ann | DD | 权重 |
|---|---|---|---|---|---|
| bull | 653 | **+3.510** | +15.43% | -1.96% | HK 20/A_mom 10/A_mr 10/zhuang 40/QQQ 10/GLD 10 |
| defensive | 788 | +1.148 | +4.63% | -3.61% | HK 20/A_mom 0/A_mr 20/zhuang 40/QQQ 5/GLD 15 |

**关键观察**：bull/def 权重差异不大 — A_mom -10/A_mr +10/QQQ -5/GLD +5。zhuang 40% / HK 20% 在两 regime 都是 cap 满。

## v5 vs v6 全窗口

| 配置 | Sharpe | Ann | DD |
|---|---|---|---|
| **v5 静态** (HK25/A_mom10/A_mr10/zhuang40/QQQ5/GLD10) | **+2.231** | +8.63% | -2.71% |
| **v6 动态** (regime switching) | **+2.142** | +8.94% | -3.61% |
| **ΔSharpe** | **-0.089** ❌ | +0.31% | -0.90% |

v6 动态全窗口 **跑输 v5** ε-0.089 Sharpe，DD 还恶化 0.90pp。

## 跨段稳健性（v5 vs v6）

| 段 | v5 | v6 | ΔSharpe | v5 DD% | v6 DD% |
|---|---|---|---|---|---|
| 2020 疫情 | +1.08 | +1.30 | +0.22 | -2.30 | -3.46 |
| 2021 牛/顶 | +2.14 | +2.21 | +0.06 | -2.44 | -1.95 |
| 2022 熊 | +0.41 | +0.51 | +0.10 | -2.33 | -2.70 |
| 2023-24 震荡 | +2.94 | +2.98 | +0.04 | -2.71 | -2.50 |
| **2025-26 反弹** | **+3.15** | **+2.74** | **-0.40** | -2.52 | -3.61 |

**短板段**: 2025-26 反弹 v6 -0.40 大幅落后 — 月末 rebalance lag 让 v6 在快速反弹段进 bull mode 晚了。其他 4 段 v6 都微优（+0.04~+0.22），但 2025-26 一段抵消所有。

## PM 结论

1. **v5 已是 efficient frontier**：3 条优化路径（A_mr 砍掉 / AH 溢价 overlay / regime 动态化）全证伪
2. **组合层不再有自由 alpha**：所有静态 grid 都被 v5 覆盖
3. **rebalance lag 是 regime 切换的硬约束**：要在 2025-26 这种快反弹段 v6 ≥ v5，必须日频切换或加预测性 regime（而非滞后 MA200 gate）

## 不要做（已证伪）

- 不要继续做组合层 grid search / regime overlay — v5 已是局部最优
- 不要把 rebalance 频率从月末改到周末或日频 — transition cost 会进一步伤 Sharpe
- 不要单边解读"bull regime in-regime Sharpe 3.51" — 切换 lag 让动态组合实际拿不到 in-regime 收益

## 未来 alpha 在哪（PM 视角）

按 ROI 排：

1. **A_mr v2 strategy 层修缺陷**（[[a_mr_rebuild_v6_grid_2026-05]] 末尾 v2 待做）：加 MA200 buffer + 斜率门 → break_ma200 出场从 46% 压到 15-20%。预期 A_mr Sharpe -0.27 → +0.2~+0.4，组合 Sharpe 可能拉到 2.30+
2. **新引入低相关性资产**：当前 6 资产，最大 ρ 0.17（QQQ↔GLD），加 BTC ETF（5%）或 EM 债 ETF 可能再降组合 vol
3. **数据源升级**：A 股 fundamentals 加 ROIC / 应收增速 / 现金流质量分项，让 L9-A 因子层精进
4. **HK 真做空 leverage**：当前 hedge 是 synthetic short，融券/期货可以放大 alpha（[[hk_optimization_2026-05]] 路线 D）

**Why:** 用户要"从对冲基金视角优化策略"，3 轮 PM 假设全被数据否决；v5 是真实 efficient frontier 是个高价值结论，避免未来浪费精力在组合层重新切。
**How to apply:** 任何"权重重新分配" / "regime 动态切换" / "砍弱腿"提议，先指本 memory；alpha 在 strategy 层（A_mr v2 / 新因子 / 新资产）而非组合层。
