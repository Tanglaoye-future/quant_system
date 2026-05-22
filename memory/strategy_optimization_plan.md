---
name: A 股中线策略优化计划（2026-05 周计划）
description: 基于专业量化分析，经回测验证的 A 股中线策略优化路线图。优先级排序，每步均需跑回测对比确认。
type: project
---

## 背景与结论（2026-05-06 会话产生）

**已验证的关键结论：**

- 短线策略（max_hold=15d）回测：Sharpe **-0.54**，胜率 34.4%，总收益 -2.2%
- 中线策略（max_hold=60d）回测：Sharpe **0.65**，胜率 46.5%，总收益 +86.9%
- HFT 在 A 股股票市场因 T+1 制度**结构性不可行**
- 当前 Sharpe 0.65 与机构目标（1.0+）之间的差距来自三处：
  1. 入场信号滞后（MA20 交叉是均值回归信号，与中线动量逻辑不匹配）
  2. 因子模型 Alpha 不足（PE 在 A 股信噪比低，缺现金流/增速加速度因子）
  3. 组合构建粗糙（无行业集中度约束，出场全仓一次性）

---

## 本周优化计划（按优先级）

### Level 1：改动小、可快速验证（本周内）

**任务 1：验证 FETCH_FLOOR bug 修复效果**
- 状态：bug 已修复（`factors.py` line 81，`start_dt = max(...)` 已提交）
- 动作：跑完整 2018-2026 A 股回测，确认 Sharpe 恢复到 ≥0.65
- 命令：`python scripts/backtest.py --market a_share --start 2018-01-01 --end 2026-05-04 --refresh-days 999`

**任务 2：打开行业分散约束**
- 改动：`config.yaml → factors.m4.m4_max_same_industry: 3`（代码已支持，只需改配置）
- 对比：跑短回测看 Sharpe 是否提升，同时观察 entry_candidates.csv 行业分布

**任务 3：部分出场逻辑**
- 改动：在 `timing/signals.py` 出场模块加 50% 部分出场
- 逻辑：ATR 止盈触发 → 出场 50%，剩余 50% 切换到 1.5× 更宽松 trailing stop
- M 节点：M5（exit_taxonomy 层）
- 需更新 exit_events.csv 的 event 字段区分 partial/full

### Level 2：因子模型手术（下周）

**任务 4：去 PE，加现金流质量因子**
- 去掉 `pe_inverse`（A 股 PE 可调节，与未来收益相关性低）
- 加入 `fcf_yield`（自由现金流 / 市值）
  - 数据源：`akshare.stock_financial_report_sina()` 或 `ak.stock_cash_flow_sheet_by_report_em()`
  - asof 截断：必须用公告日，不能用报告期
- `revenue_growth` 改为**增速加速度**（本期增速 − 上期增速）
- 权重调整建议：`pb_inverse 0.20, roe 0.25, fcf_yield 0.20, rev_accel 0.15, momentum_3m 0.20`

**任务 5：北向资金作为入场辅助信号**
- 数据：`akshare.stock_hsgt_north_net_flow_in_em()`（陆股通北向净买入）
- 用法：当日北向净买入 > 近 20 日均值 × 1.5 时，入场信号 RSI 上沿放宽 5pt
- M 节点：M2/M3（timing/signals.py 的 RSI 带调整逻辑）

### Level 3：入场信号替换（中期，需单独验证分支）

**任务 6：MA20 交叉 → 突破 + 量能确认**
- 新信号：收盘价创 20 日新高 + 成交量 > 近 10 日均量 × 1.3 + RSI 50-70 + MA60 市场门
- 逻辑：右侧确认趋势延续，而非预测均值回归反弹
- 此改动影响 M2 核心，需单独开实验分支回测对比，不直接合入 main

---

## 回测对照表（持续更新）

| 版本 | 改动 | Sharpe | 总收益 | 交易数 | 状态 |
|------|------|--------|--------|--------|------|
| v1 基线 | 原始策略 | 0.65 | +86.9% | 398 | PASS |
| v2 回归 | 250日窗口 bug | 0.31 | +36.0% | 177 | FAIL（bug 已修复）|
| 短线实验 | max_hold=15d | -0.54 | -2.2% | 61 | FAIL（方向否定）|
| L7-C3 实盘修复 | 2026-05-22 落地（regime_exit+partial_exit+collar） | 0.619 (4y) / 0.402 (8y) | +38.5% (4y) | 396 | ✅ PASS — 落地 config |
| zhuang 累计 | v5→L1-E→L4-combo4→L5 | 0.944→**1.806** (6y) | +37%→+76% | 136 | ✅ PASS — 全部落地 |

## equity_factor 实盘修复摘要（L7-C3, 2026-05-22）
- L7-A/B Pullback 入场重写全失败（Sharpe -0.16 ~ -0.98）
- L7-C3 回到 baseline 追高入场 + 收紧出场（类似 zhuang L4）
- 4y 2022-2026: Sharpe 0.23→0.62 (+174%), DD -19.5%→-14.3%
- 8y 2018-2026: DD 始终改善；牛市段 baseline 占优（partial_exit 早锁利）
- 落地: atr_stop=1.5, atr_target=3.0, max_hold=30, regime_exit=on, partial_exit=on
- 详见 `memory/equity_factor_l7_2026-05.md`

## zhuang 累计优化摘要（L1→L5, 2026-05-18~19）
- L1-E: entry_price_position_min=0.4 + score≥70 → Sharpe 0.94→1.35
- L4-combo4: mh=10+tp=0.10+atr=1.5+dt=6.0+ms=0.03 → Sharpe 1.35→1.63
- L5: score 分级仓位 (3%/5%/8%) → Sharpe 1.63→1.81
- 6-asset overlay: zhuang 20-25% 占比, 组合 Sharpe 1.91→2.14
- 详见 `memory/zhuang_optimization_2026-05.md`, `zhuang_l4_experiments_2026-05.md`, `zhuang_l5_experiments_2026-05.md`

---

## 核心原则

- **每个改动单独对照**：改一个变量，跑回测，与 v1 基线比
- **回测区间统一**：2018-01-01 → 2026-05-04，market=a_share
- **准入门槛**：Sharpe ≥ 0.5，最大回撤 ≤ 25%，胜率 ≥ 40%
- **不允许跳步**：Level 1 全部通过后才做 Level 2

**Why:** 2026-05-06 会话中经专业量化分析和回测实验验证，短线方向已被数据否定，中线优化路径经论证后锁定。
**How to apply:** 每次会话开始先读此文件确认当前进度，按优先级继续下一个未完成任务。
