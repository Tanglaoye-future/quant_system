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

1. **HK 实盘账户未开通** — 最大 blocker（详见 Reverse fallback）
2. **跨境汇款**：A 股 → IBKR 需 3-5 工作日；A 股 → HK 香港账户更长
3. **加密 ETF 时段限制**：IBIT 仅美东时段交易 (21:30-04:00 北京时间)
4. **税务问题**：
   - HK 股票分红 0% 预扣
   - QQQ / GLD / IBIT 分红 30% 预扣（W8-BEN 后 10%）
   - PM 需自行处理外汇所得申报
5. **A_mom 日内做 T**：已启用 advisory v1（[[intraday_t_execution_pr1_5_2026-06]]）；spot_em 数据源恢复后开始发信号

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
