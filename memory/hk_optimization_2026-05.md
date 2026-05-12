---
name: HK 策略 2026-05 优化路线图 + 验证记录
description: HK bottomup_timing 策略 6 个月迭代记录（v1→v10），关键洞察、坑、未做完的方向；每次 session 开始读
type: project
---

## 起点和终点

| 指标 | v1 baseline (2026-05-12 之前) | v10 final (2026-05-12) |
|---|---|---|
| Sharpe | 0.42 ❌ FAIL | **0.65 ✅ PASS** |
| 总收益 | +47.2% | **+79.6%** |
| 最大回撤 | -13.2% | -13.4% |
| 超额收益 vs HSCHK100 | +69.4pp | **+101.7pp** |
| 年化收益 | 4.88% | 7.47% |

回测区间 2018-01-01 → 2026-05-04，HK HSCHK100 universe，143 笔交易。

## 关键改动（提交在 worktree branch `worktree-hk-l1-wider-trail-partial-exit`）

### L1：M5 出场层重构（commit `1782e18`）

- **TP runner 机制**：触及 take_profit 时不全平，promote 为 runner（stop 拉到 target - 1×ATR 锁利）
- **修关键 bug**：runner 激活后 TP 永久解除，不再每天重复砍仓（修复前 27 笔无效 TP 出场）
- **RSI 超买改 promote**：runner 不存在时 RSI≥80 且已浮盈，promote 替代砍仓
- **wider ATR trail**：HK 基础 trail 2.0×ATR → 2.5×ATR（HK 波动比 A 股大）
- **单仓 0.15 → 0.20**：拉高资金利用率（HK 候选少，10 仓位上限不绑死）

### L3：基准做空 overlay（commit `1782e18`）

- 关键洞察：HK 策略对 HSCHK100 beta 已经只有 **0.155**（不是预想的高 beta drag），MA200 门控已经消除大半 beta
- 但「**on-regime hedge**」仍有效：仅在 MA200 ON 时做空（持仓期）
  - regime-OFF 时做空 → 被熊市反弹打损（Sharpe 跌到 0.06-0.24）
  - regime-ON 时做空 → 真正隔离 alpha
- 最优参数：`ratio=0.3, ma_days=200, borrow_cost=0.03`
- Sharpe 0.52 → 0.65, DD -16% → -13%

### L2-A：HK 财务数据接入（commit `209ae5e`）

- `stock_financial_hk_analysis_indicator_em(symbol="00700", indicator="年度")` 提供 ROE_AVG / EPS_TTM / BPS / OPERATE_INCOME_YOY，数据到 2025-12-31
- 90 天披露滞后（HK 年报通常 FY-end 后 3-4 个月公布）
- **意外发现**：HK 价值因子（PE/PB）在 2018-2026 有反 alpha（H 股银行价值陷阱），质量因子（ROE）有正 alpha
- 最优权重：`roe 0.30, revenue_growth 0.10, momentum_3m 0.30, momentum_6m 0.30, PE=PB=0`

## 重要陷阱（避坑指南）

1. **HK 因子模型 ranking 影响有限**：大多数日子入场候选 < 10 仓位上限，ranking 根本不绑定。要提升 alpha，要么扩入场（更多候选），要么改时机（更早入更晚出）。
2. **HK 财务数据老 endpoint `stock_hk_indicator_eniu` 数据停在 2022-07**，不能用。必须用 EM 的 `stock_financial_hk_analysis_indicator_em`。
3. **on-regime hedge 是反直觉的**：常见的「熊市做空对冲」反而最差。原因：熊市内反弹经常发生，没 MA200 突破就反空，被反复打损。
4. **TP runner promote bug**：实现 runner 时必须显式让 runner 永久解除 TP 检查（否则下一根 bar 还在 target 之上就立刻 TP 砍仓，runner 形同虚设）。

## 未完成方向（按 ROI 排）

| 优先级 | 方向 | 预期 Sharpe Δ | 代价 |
|---|---|---|---|
| **A** | 接入南向资金（港股通净流入）— `ak.stock_hsgt_hist_em` | +0.05~0.10 | 中（loader 扩展 + 信号整合）|
| **B** | 接入 AH 溢价指数 — H 股估值套利信号 | +0.05~0.10 | 中 |
| **C** | 提升入场候选数（放宽 RSI 带 / cross_lookback）| ±0.05 | 低 |
| **D** | 真做空 leverage（current overlay 是合成的）| +0.10? | 高（杠杆模型）|

**Why:** 2026-05-12 一次 session 内 10 轮回测的实验沉淀，部分发现与早期假设相反（HK 价值因子反 alpha、on-regime hedge 优于 off-regime hedge），需要记忆才能避免下次重做同样实验。
**How to apply:** 任何 HK 策略改动 session 启动时先读，避免重复 ground truth；新方向要在「未完成」列表选；权重调整以 v10 为 baseline。
