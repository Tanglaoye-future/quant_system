---
name: v7-efficient-frontier-2026-06
description: 2026-06-15 V7 6-asset efficient frontier — zhuang 出 / 加密入；Top1 配比 HK50/A_mom20/A_mr0/QQQ10/GLD10/BTC10 双窗口同向 PASS (4y Sharpe 1.842 / 8y 1.455 / DD -12.5%/-14.8%)，5 个 Pareto 全部 dominate 用户原提议；supersede v5_efficient_frontier_2026-05
metadata:
  type: project
---

# V7 6-asset Efficient Frontier — 2026-06-15

**用户决策**: GLD 10% 固定 + 加密 10% 固定 + 股市 80% (HK/A_mom/A_mr/QQQ) 优化。
**Top1 落地**: **HK 50% / A_mom 20% / A_mr 0% / QQQ 10% / GLD 10% / BTC(IBIT) 10%**。
**Supersedes**: [[v5_efficient_frontier_2026-05]] + [[v5_t1_recalibration_2026-06]] + [[v5_grid_hk_t0_recalibration_2026-06]]。

## 触发上下文

[[zhuang_deprecated_2026-06]] 弃用 → 组合层 zhuang 15-25% 空出。
[[hk_t0_recalibration_2026-06]] HK T+0 校准后 HK_mom alpha +0.06 Sharpe。
[[us_t0_recalibration_asymmetry_2026-06]] US 主动 momentum 双 FAIL → 转被动 QQQ。
用户决定：股市 80% + GLD 10% + 加密 10%。需要在新框架下重做 efficient frontier。

## Grid 设计

| 项 | 值 |
|---|---|
| 资产数 | 6 (HK_mom / A_mom / A_mr / QQQ / GLD / BTC-USD) |
| GLD 固定 | 10% |
| 加密固定 | 10% (BTC-USD 代理 IBIT，因 IBIT 仅 2024+ 历史不足) |
| 股市 budget | 80% 在 HK/A_mom/A_mr/QQQ 内 step 5% search |
| 单一资产 cap | 50% |
| 股市组合数 | 745 |
| 双窗口 | 4y (2022-01-05 → 2026-04-30) + 8y (2018-01-03 → 2026-04-30) |

脚本: `scripts/portfolio/run_v7_6asset_grid_crypto.py`
产物: `data/backtest/portfolio_v7_6asset_crypto_{4Y,8Y}.{md,json}`

## 单资产基础（双窗口）

| 资产 | 4y Sharpe | 4y DD | 8y Sharpe | 8y DD | Ann Vol |
|---|---:|---:|---:|---:|---:|
| HK_mom | +1.729 | -8.02% | +0.987 | -14.71% | 9% |
| A_mom (L9-A) | +0.917 | -12.75% | +0.578 | -18.15% | 11% |
| A_mr | +0.066 | -11.57% | +0.234 | -11.57% | 7% |
| QQQ | +0.714 | -32.42% | +0.933 | -35.12% | 24% |
| GLD | +1.323 | -21.03% | +1.031 | -22.00% | 17% |
| BTC-USD | +0.512 | -66.74% | +0.660 | -81.40% | 67% |

相关性核心点：
- HK_mom 与 A_mom 0.13 (低相关，A 股内部独立)
- HK_mom 与 A_mr -0.11 (hedge 价值)
- A_mom 与 A_mr -0.21 ~ -0.27 (强 hedge 价值)
- BTC-USD 与 QQQ 0.28 (8y) / 0.42 (4y) — **BTC 与 QQQ 同 risk-on，非完全独立**
- BTC 与其它资产 ρ ≈ 0 (除 QQQ 外)，分散有效

## 双窗口同向 PASS — 5 个 Pareto 候选

筛选条件：4y Top20 by Sharpe ∩ 8y Top20 by Sharpe ∩ DD ≤ 15% (双窗口)。

| Rank | 配比 | 4y Sharpe | 4y DD | 8y Sharpe | 8y DD | Sharpe Sum |
|---|---|---:|---:|---:|---:|---:|
| **1** ⭐ | HK50/A20/Amr0/Q10/G10/B10 | **+1.842** | -12.52% | **+1.455** | -14.78% | **+3.297** |
| 2 | HK50/A20/Amr5/Q5/G10/B10 | +1.872 | **-10.96%** | +1.424 | **-13.72%** | +3.296 |
| 3 | HK50/A15/Amr5/Q10/G10/B10 | +1.824 | -12.54% | +1.458 | -14.76% | +3.282 |
| 4 | HK50/A15/Amr10/Q5/G10/B10 | +1.853 | -10.98% | +1.425 | -13.58% | +3.278 |
| 5 | HK45/A25/Amr0/Q10/G10/B10 | +1.822 | -12.36% | +1.446 | -14.71% | +3.268 |

**全部 dominate 用户原提议** (HK35/A20/Amr10/Q15/G10/B10) — Sharpe sum 1.676+1.447=3.123，落 Top 5 外。

## Top1 选定：HK50 / A_mom20 / A_mr0 / QQQ10 / GLD10 / BTC10

### 双窗口 metrics

| 维度 | 4y | 8y |
|---|---:|---:|
| Sharpe | **+1.842** | **+1.455** |
| Ann Return | +17.14% | +14.12% |
| Max DD | -12.52% | -14.78% |
| Ann Vol | 9.35% | 9.71% |
| Total Return | +88% | +180% |

### 配比决策依据

| 资产 | 配比 | 决策依据 |
|---|---:|---|
| **HK_mom** | **50%** | 单资产 4y/8y 都 Top1；grid 双窗口 cap 50% binding；HK T+0 alpha 已落 |
| **A_mom** | **20%** | 双窗口 Pareto 共识 15-25% 区间；新增日内做 T advisory v1 增量 alpha 通道 |
| **A_mr** | **0%** | 8y solo Sharpe 0.23 弱；hedge 价值在 HK50+A_mom20 框架下边际为 0；[[a_mr_v2_falsified_2026-05]] |
| **QQQ** | **10%** | 4y 偏好 0% (DD 拖累)，8y 偏好 15-20% (Sharpe 强)；妥协 10% 双窗口都接受 |
| **GLD** | **10%** | 用户固定 |
| **加密 (IBIT)** | **10%** | 用户固定；BTC-USD 代理验证，10% 配比 risk contribution ~25-30% |

## 与 v5 / 历史对比

| 配比 | HK | A_mom | A_mr | zhuang | QQQ | GLD | IBIT | 4y Sharpe | 4y DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **v7 Top1 (本)** | **50%** | **20%** | **0%** | — | **10%** | **10%** | **10%** | **+1.842** | -12.52% |
| v5 baseline (deployment_plan_2026-05) | 25% | 25% | 15% | — | 15% | 20% | — | +1.198 (4y) | -7.94% |
| v5+zhuang grid Top1 (T+0 recal) | 35-40% | 10-15% | 10-15% | 10-15% | 10% | 15% | — | (历史不可比 含 zhuang) | — |
| 用户原提议 | 35% | 20% | 10% | — | 15% | 10% | 10% | +1.676 | -13.67% |

**Δ vs v5 baseline**:
- Sharpe 4y +1.198 → +1.842 (Δ+0.644) — HK 重仓 + 加密 BTC 暴露推高
- DD -7.94% → -12.52% (Δ-4.58pp) — 加密 BTC 67% vol 提高组合 vol，可接受

**Δ vs 用户原提议**:
- Sharpe 4y +0.166 / 8y +0.008 (双窗口同向 PASS)
- DD 4y 改善 1.15pp / 8y 改善 1.16pp
- 关键差异：HK 35→50 / A_mr 10→0 / QQQ 15→10

## 风险考量

### 加密 10% 实际风险贡献 ~25-30%
- BTC ann vol 67% vs HK_mom 9% (BTC vol 是 HK 的 7 倍)
- 10% 名义但 BTC 占 portfolio vol ~30%
- 历史 BTC 单年 -80% (2022) 是真实场景
- 组合层 DD -12.5% (4y) ~ -14.8% (8y) 已包含此风险
- **如果 BTC 再来 -80%，组合层最大 DD 可能扩到 -20%**（grid 历史窗口已涵盖 BTC 2022 熊市）

### HK 50% capacity
- HK 集中度高（HSCHK100 TOP10 占 50%）
- 50% 配比下流动性仍充足（HK 大盘日 turnover 高）
- 但**实盘账户未开通** — 这是 Top1 落地的最大 blocker

### QQQ 10% 是双窗口妥协
- 4y QQQ DD -32% (2022 熊市) 把 4y top 偏好砍到 0%
- 8y QQQ Sharpe 0.93 较强 → 8y top 偏好 15-20%
- 10% 是双窗口同向 PASS 的最大公约数
- 未来如果 4y/8y 窗口 roll forward (含更多 QQQ 上涨年)，可能 grid 重做后偏向 15%

## 实盘落地路径（详 [[deployment-plan-v7-2026-06]]）

主要 blocker:
1. **HK 实盘账户** — 需打通 HK 券商账户才能落 HK 50% (当前 0 实盘仓位)
2. **加密 ETF** — IBKR 已可买 IBIT，无 blocker
3. **zhuang 清仓资金** — 今日 3 笔人工卖出后转入 HK / QQQ / IBIT
4. **A_mr 资金归零** — 现金缓冲转其他腿（A_mr 仍跑 daily 出信号，PM 参考但 0 仓位）

## Backstop 5 条检查

- **#1 18 条证伪墙**: 不撞（grid 是组合层 weight 重做，不撬 strategy alpha；A_mr 0% 与 [[a_mr_v2_falsified_2026-05]] 一致）✓
- **#2 双窗口同向 PASS**: 5 个 Pareto 候选 4y/8y 都在 Top20，Top1 选定 ✓
- **#3 实盘 < 30 笔不撬 frontier**: 本 grid 用 4y/8y 全样本（非实盘小样本），合规 ✓
- **#4 PM 决策权**: 用户 2026-06-15 明确授权"Top1 落地" ✓
- **#5 采集 vs alpha 分离**: N/A（不涉及 self-learning）✓

## 后续监控

- 实盘 ≥ 90 天 + ≥ 30 笔 closed 后跑 [[session_2026_06_08_self_learning_pipeline]] L5 retrospective
- 6-12 月后窗口 roll forward 重做 v7 grid，看 BTC / QQQ 配比是否需要调整
- 月度 KPI 报告（[[monthly_kpi_scaffold_2026-05]]）追组合层 Sharpe vs 1.5 期望

## 不要做（沿用旧规则）

- ❌ 不要因实盘 1-3 个月 metrics 偏离 grid 预期就调权重（Backstop #3）
- ❌ 不要因 4y top 偏好 QQQ 0% 就把 QQQ 砍 0%（8y 反向 → 撞 paradox 第 6 类窗口依赖）
- ❌ 不要把 A_mr 改 5%+（hedge 价值在 HK50+A_mom20 框架下已饱和；改回是 v5 旧框架思维）
- ❌ 不要把 BTC 改 5% 或 15%（用户决策已定 10%；调动 BTC 配比需重跑 grid）
- ❌ 不要因 HK 实盘账户未开通就降 HK 配比（开通账户是工程问题，不是策略问题）

## 关联

- [[project_north_star]] 4 根支柱框架
- [[zhuang_deprecated_2026-06]] zhuang 出局来源
- [[hk_t0_recalibration_2026-06]] HK T+0 alpha 来源
- [[us_t0_recalibration_asymmetry_2026-06]] US 主动失效 → 被动 QQQ 来源
- [[tp_runner_sweep_falsified_2026-06]] 第 18 条证伪（HK 策略层 alpha 饱和）
- [[a_mr_v2_falsified_2026-05]] A_mr 0% 来源
- [[intraday_t_execution_pr1_5_2026-06]] A_mom 日内做 T 增量 alpha 通道
- `scripts/portfolio/run_v7_6asset_grid_crypto.py` 可复跑脚本
- `data/backtest/portfolio_v7_6asset_crypto_4Y.md` + `_8Y.md` 完整 grid 报告

**Why**: zhuang 弃用 + HK T+0 校准 + US 主动失效 + 用户决定加密 10% 的 4 个变化后，v5 efficient frontier 全部失效；v7 grid 验证 + Pareto 双窗口 PASS 替代。

**How to apply**: 任何"调组合层权重"提议，先指本 memory 5 个 Pareto 候选 + Top1；偏离 Top1 需要数据支撑（不能仅凭直觉或单窗口）。任何"加新资产 / 砍资产"提议，需先跑 grid 双窗口验证。
