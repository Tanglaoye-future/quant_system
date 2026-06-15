---
name: deployment-plan-v7-2026-06
description: 2026-06-15 V7 6-asset 实盘部署计划 — HK50/A_mom20/A_mr0/QQQ10/GLD10/IBIT10；resource 转移路径 (zhuang 清仓资金 → 新配比) + HK 账户开通 TODO + IBKR 持仓清单 + 季度再平衡触发条件；supersede deployment_plan_2026-05
metadata:
  type: project
---

# V7 实盘部署计划 — 2026-06-15

**配比**: HK 50% / A_mom 20% / A_mr 0% / QQQ 10% / GLD 10% / IBIT 10%
**Grid 验证**: [[v7-efficient-frontier-2026-06]]
**Supersedes**: [[deployment_plan_2026-05]]

## 目标账户分布

| 账户 | 资产 | 配比 | 标的 |
|---|---|---:|---|
| HK 券商账户（待开通）| HK_mom 主动 | **50%** | HSCHK100 持仓（10 只 cap）|
| A 股券商账户 | A_mom 主动 + 日内做 T | **20%** | HS300 持仓（10 只 cap）+ 日内 T 信号 |
| A 股券商账户 | A_mr 信号参考 | **0%** | 不分配资金；daily 仍跑 mean_reversion 出信号供 PM 人工参考 |
| IBKR 账户 | QQQ 被动 | **10%** | QQQ ETF |
| IBKR 账户 | GLD 被动 | **10%** | GLD ETF |
| IBKR 账户 | IBIT 被动 | **10%** | IBIT ETF（BlackRock Bitcoin ETF）|

**总账户数**: 3 (HK 券商 / A 股券商 / IBKR)

## 资金转移路径（从当前实盘）

### 当前实盘状态（2026-06-15 上午）

| 资产 | 当前实盘占比 | 实盘账户 |
|---|---:|---|
| A_mom (6 笔) | ~55% | A 股券商 |
| zhuang (3 笔, 今日清仓) | ~25% → 现金 | A 股券商 |
| HK_mom (0 笔, 账户未开通) | 0% | n/a |
| QQQ (0 笔) | 0% | IBKR (未持有) |
| GLD (0 笔) | 0% | IBKR (未持有) |
| 加密 (0 笔) | 0% | n/a |
| 现金缓冲 | ~20% | A 股券商 |

### 转移步骤（按优先级）

1. **[今日 已完成]** zhuang 3 笔清仓 → A 股账户现金 +25%
2. **[本周]** IBKR 账户激活（如已 active 跳过）+ 入金（A 股账户 → IBKR 跨境汇款，约需 3-5 工作日）
3. **[2 周内]** HK 券商账户开通（最大 blocker；如开不通需要 PM 决策"接受 HK 0% / 暂留现金 / 改 v7b 配比"）
4. **[HK 账户 ready 后]** A 股现金 → 跨境汇 → HK 账户 → 跑 daily_equity --strategy equity_hk_momentum 出信号 → 按信号建仓 HK 50%
5. **[IBKR ready 后]**:
   - 买 QQQ 10%
   - 买 GLD 10%
   - 买 IBIT 10%

### Reverse fallback（如 HK 账户长期开不通）

如果 3 个月后 HK 账户仍未开通：
- v7b 配比 = **HK 0% / A_mom 30% / A_mr 0% / QQQ 30% / GLD 10% / IBIT 10% / 现金 20%**
- 跑 grid v7b 验证（额外 30 分钟）
- 但**HK alpha 是 v7 核心**，不开通是真损失（Sharpe 4y 1.84 → 估计 1.2-1.3）

## 阶段性持仓上限（避免突变）

实盘建仓不要一次性满仓，分批进入降低择时风险：

| 周 | HK | A_mom | QQQ | GLD | IBIT | 现金 |
|---|---:|---:|---:|---:|---:|---:|
| W0 (今日) | 0% | 55% | 0% | 0% | 0% | 45% |
| W1 (本周末) | 0% | 50% | 5% | 5% | 5% | 35% |
| W2 | 0% | 35% | 10% | 10% | 10% | 35% |
| W3 (HK 账户 OK) | 15% | 25% | 10% | 10% | 10% | 30% |
| W4 | 30% | 22% | 10% | 10% | 10% | 18% |
| W5 (满仓 V7) | **50%** | **20%** | **10%** | **10%** | **10%** | 0% |

每周末评估 + 调整。如某周 HK 指数大涨 5%+ 暂缓 HK 建仓 1 周（等回踩）。

## 季度再平衡触发条件

不定期再平衡，仅在以下情况触发：

1. **单一资产偏离 ±5pp** — 例 HK 涨到 55% 或跌到 45%，触发卖/买回 50%
2. **加密资产偏离 ±3pp** — BTC 高 vol 容易偏离，更紧阈值
3. **组合层 DD > -10%** — 触发降权重高 vol 资产（IBIT 优先）
4. **季末机械再平衡** — 每年 3/6/9/12 月末，无论是否触发上面阈值都做一次小调

## 月度 KPI 监控（[[monthly_kpi_scaffold_2026-05]]）

| 指标 | 目标 | 触发预警 |
|---|---|---|
| 月度 Sharpe (rolling 90d) | > 1.2 | < 0.8 连续 2 月 → 复盘 |
| 月度 DD | < -8% | < -12% 单月 → 复盘 + 降权 |
| 单资产 P&L | 各资产追历史预期 | HK_mom 月亏 -5%+ → 数据源 / signals 排查 |
| 日内做 T 信号统计 | 等实盘 ≥30 笔 | 实盘 < 90 天禁撬 yaml |

## 现实约束 ⚠️

1. ✅ **HK 实盘账户 — 东方财富港股通已开通** (2026-06-15 用户确认)
   - **但港股通 ≠ HK 本地 T+0**：通过港股通买的港股**强制 T+1**（内地结算系统约束）
   - 影响：HK_mom 单资产 4y Sharpe 1.149 (T+0) → 1.090 (T+1)，Δ-0.06
   - V7 Top1 组合 4y Sharpe 估算 1.842 → **~1.81** / 8y 1.455 → **~1.42**
   - 仍然 dominate 用户原提议 (1.676/1.447)，HK 50% 仍是最优
   - 不改 hk_share.yaml settlement_mode (反映 HK 市场本身)，仅在本 memory 披露执行通道损失
2. ✅ **IBKR 账户 ready 入金完成** (2026-06-15 用户确认) — 本周可买 QQQ/GLD/IBIT
3. **跨境汇款**：A 股 → IBKR 需 3-5 工作日（用户已入金，本周不卡）；A 股 → 港股通账户跨境无需汇款（沪深市券商直通）
4. **加密 ETF 时段限制**：IBIT 仅美东时段交易 (21:30-04:00 北京时间)
5. **税务问题**：
   - 港股通分红：H 股 28% 内地预扣 / 红筹 10% （由券商代扣，PM 不操心）
   - QQQ / GLD / IBIT 分红：W8-BEN 后 10% 预扣
   - 资本利得：港股通免内地资本利得税；IBKR 持有 ≥ 1 年免美国资本利得
6. **A_mom 日内做 T**：已启用 advisory v1（[[intraday_t_execution_pr1_5_2026-06]]）；spot_em 数据源恢复后开始发信号
7. **港股通标的限制**：HSCHK100 主体（H 股 + 中资）95%+ 在港股通名单内；个别成份股可能不在，按策略信号实际下单前 cross-check 港股通名单（东方财富 App 标红/灰即不可买）
8. **港股通日额度**：520 亿（沪+深），散户单笔零压力
9. **印花税 0.13%**：backtest 设 0.0 偏低；年化拖累 ~0.08%，Sharpe 影响 < 0.01 可忽略

## HK regime gate 状态判定（决定何时开始建 HK 仓）

**今日 2026-06-15**: HSCHK100 收盘 **7146.40** < MA200 **7427.44** → **regime OFF**。
**用户决策**：HK 50% 资金全部留现金等 regime ON，不抢跑。

依据：[[hk_optimization_2026-05]] / [[hk_t0_recalibration_2026-06]]：HK 长熊市段（指数 < MA200）反弹常见但持续性差，按策略 M2 不入场是历史 Sharpe 提升 0.2+ 的关键。

判定信号：每日 `scripts/daily/daily_equity.py --strategy equity_hk_momentum` 报表 `market_gate=true` 即 ON。需要：
- HSCHK100 收盘 > MA200 (7427.44 截至 2026-06-15)
- 通常需要指数反弹 5-10%（当前距 MA200 -3.8%）

历史 regime OFF 段长度：[[hk_optimization_2026-05]] 显示 HK 长熊（2018-2019, 2022 年中）持续 6-12 月；短熊（2021 Q3, 2024 Q1）持续 1-3 月。**实际等待时间不可预测**。

## 阶段性 W0→W5 持仓上限（用户 2026-06-15 决策更新）

更新背景：用户决定 HK 50% 全留现金等 regime ON；IBKR ready 本周可买。新路径分两阶段。

### 阶段 A — HK regime OFF 期间（今日起，期限不定）

| 周 | 触发 | HK | A_mom | QQQ | GLD | IBIT | 现金 | 实操 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| W0 | 今日 (zhuang 卖出后) | 0% | 55% | 0% | 0% | 0% | 45% | zhuang 3 笔已平 → 现金 |
| **W1** | **本周末** | 0% | 35% | 10% | 10% | 10% | 35% | A_mom 卖 20pp + IBKR 买 3 资产 |
| W2 | 下周 (微调) | 0% | 25% | 10% | 10% | 10% | 45% | A_mom 再卖 10pp 备 HK |
| **A 稳态** | 维持 | 0% | **20%** | **10%** | **10%** | **10%** | **50%** | 等 regime ON 持续观察 |

### 阶段 B — HK regime ON 触发后（HSCHK100 > MA200）

按信号分批建 HK 仓（不要一次性 50%，避免择时风险）：

| 阶段 | 触发 | HK | A_mom | QQQ | GLD | IBIT | 现金 | 实操 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| B1 | regime ON D+1 起 | 15% | 20% | 10% | 10% | 10% | 35% | HK 第一周买 3 只 candidates |
| B2 | D+8 | 30% | 20% | 10% | 10% | 10% | 20% | HK 第二周补 3 只 candidates (累计 5-7 只) |
| B3 | D+15 | 40% | 20% | 10% | 10% | 10% | 10% | HK 第三周补到目标 8-10 只 |
| **B4 (V7 Top1)** | D+22 | **50%** | **20%** | **10%** | **10%** | **10%** | **0%** | 满仓 V7 Top1 |

**B 阶段建仓约束**：
- 单日最多新建 1-2 个 HK 仓位（避免择时集中风险）
- regime 短期再次破 MA200 → 暂停 B 阶段，回退到 A 稳态
- 港股通账户 T+1 → 单日只能买不能同日卖，节奏需更慢

## 本周实操清单（W1 落地）

### 周一-周三（市场日内时段做）

1. ✅ ~~zhuang 清仓~~ (已人工完成，ledger 等晚间券商对账后回填)
2. **A_mom 减仓 35pp → 20pp**（55% → 20%，卖出 35pp）
   - 推荐：按当前 6 只持仓**等比例卖出 64%**（35/55）
   - 或：按 pnl 排序，卖 pnl 最弱的 4 只（保 pnl_pct > 0 的强势仓）
   - 用户 PM 决策方式，下单在东方财富 A 股账户
3. **A_mom 卖出 35pp 资金 → 跨账户转 IBKR**（如果不能直接划转，国内汇款到 IBKR 链路）
4. **IBKR 买入**：
   - QQQ 占总资金 10%
   - GLD 占总资金 10%
   - IBIT 占总资金 10%
   - 三笔同日下，避免择时偏差

### 周四-周五（监控与微调）

5. 每日运行 `~/quant_system/deploy/run_daily.sh --no-options`（如未恢复 launchd 调度）
6. 看 daily 报表 HK regime 状态；如果突破 MA200 → 立即进入 B 阶段
7. 看 A_mom 日内做 T 是否触发信号（spot_em 数据源恢复后）

### 周末（复盘）

8. zhuang ledger close（你给 3 个成交价 → 我跑 `scripts/admin/close_zhuang_manual.py`）
9. 月度 KPI 报表（[[monthly_kpi_scaffold_2026-05]]）
10. 核对实盘配比 vs W1 目标（HK 0 / A_mom 35 / QQQ 10 / GLD 10 / IBIT 10 / 现金 35）

## 不要做（沿用旧规则）

- ❌ 不要因 1-2 周实盘 metrics 偏离就调权重（Backstop #3）
- ❌ 不要在 HK 账户未开通前部署 HK_mom（pseudo-deploy 无意义）
- ❌ 不要为 IBIT 现货切换（IBIT ETF + IBKR 流程已通）
- ❌ 不要把 A_mr 重启自动建仓（[[a_mr_v2_falsified_2026-05]] solo alpha 死；hedge 价值 v7 框架下已饱和）
- ❌ 不要为美股 SP500 / NDX 重启主动选股（[[us_t0_recalibration_asymmetry_2026-06]] 双 FAIL）

## 关联

- [[v7-efficient-frontier-2026-06]] grid 验证 + Top1 配比依据
- [[zhuang_deprecated_2026-06]] 清仓资金转入来源
- [[intraday_t_execution_pr1_5_2026-06]] A_mom 日内做 T 增量 alpha
- [[hk_t0_recalibration_2026-06]] HK_mom alpha 校准
- [[deployment_plan_2026-05]] 历史 v5 计划（已 superseded）
- [[deploy_checklist_2026-05]] 历史检查清单（部分仍适用）
- [[monthly_kpi_scaffold_2026-05]] 月度 KPI 报表脚手架

**Why**: v7 efficient frontier 落地需要分账户分阶段执行；HK 账户开通是最大 blocker；季度再平衡 + 月度 KPI 防止 frontier 漂移。

**How to apply**: 每周末按"阶段性持仓上限"表评估实盘进度；任何偏离 W0-W5 路径的提议先指本 memory；HK 账户 3 月后仍开不通触发 v7b fallback grid。
