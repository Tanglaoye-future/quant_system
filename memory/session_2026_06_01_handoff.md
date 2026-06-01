---
name: session-2026-06-01-handoff
description: 2026-05-31~06-01 session 总账 + 下个 session cold-start backlog；4 条新证伪 (10→13) + 月度 KPI 脚手架；三层 efficient set 同构 (L8D2 HS300 / L1-E zhuang / v5 组合) → strategy 层 + 因子层 + 组合层全饱和；剩余 alpha 通道极度收敛
metadata:
  type: project
---

## 当前状态 (2026-06-01 收工)

- **v5 部署不变** (HK25/A_mom10/A_mr10/zhuang40/QQQ5/GLD10) — 13 条证伪路径 + 三层 efficient set 已证 v5 是真 frontier
- **实盘窗口**: 2026-05-30 起, **2026-06-30 是第一次月度 KPI checkpoint**
- 本 session 5 commit: 3f34bd9 / 9da1470 / 8fd1bdb / 4c6aa2e / b8f1738
- 本 session 6 个新 memory: zhuang_l7a_falsified / zhuang_l7b_falsified / zhuang_l8_fundamentals_falsified / monthly_kpi_scaffold / equity_factor_l9b_falsified / 本文件
- 所有 commit 已 push origin/main

## 13 条已证伪路径累积（按类别分组）

### 组合层（5 条 — 2026-05-30）
- v6 砍 A_mr: 组合 -0.10 + 2022 反向
- v6 regime overlay: -0.089 + 2025-26 反弹 -0.40
- +IBIT 5/10%: -0.28 / -0.87
- +TLT 5/10%: -0.13 / -0.37
- +CSI1000 5/10%: -0.10 / -0.34

### A_mr strategy（2 条 — 2026-05-30）
- v1 SwingReversion 4y Sharpe -0.27
- v2 (buffer+slope+grace) sweep plateau -0.27~-0.34

### zhuang sleeve（4 条 — L6 / L7 / L8）
- weights strong-volume / strong-conso 过拟合 (5-30)
- L7-A position_max_count 6→8/10 三 case 同分 (cap 不 binding)
- L7-B accumulation_score_entry 70→67/65 单调下 (放宽损质量)
- L8 fundamentals gate ROE>0+营收>0 误杀比 47%

### 因子层 / 单维（2 条）
- HK overlay AH 溢价 alpha 不稳定
- equity_factor L9-B ROIC + AR YoY (HS300) 三 case 全负

## 🔑 三层 efficient set 同构（本 session 最大结构发现）

| 层 | efficient 配置 | 证伪路径 |
|---|---|---|
| 组合层 | v5 (HK25/A_mom10/A_mr10/zhuang40/QQQ5/GLD10) | 5 |
| 因子层 (HS300) | L8D2 (pe 0.15 / pb 0.10 / roe 0.20 / rev_g 0.15 / mom3m 0.20, fcf=0 + L9-B=0) | 2 |
| zhuang sleeve | L1-E (score=70 + pos=0.4) + L6-A equal weights | 3 |

**结论**: strategy 层 (zhuang) + 因子层 (HS300) + 组合层 (6-asset) **三层都已饱和**。在当前 universe + 信号集合下, alpha 已被吃完。

## 剩余 alpha 通道（极度收敛）

按 ROI × 风险排:

### A. 新维度信号【可自主推, 最高 ROI】

#### A1. 资金流 overlay (北向/南向)【强烈推荐 — 数据已接入, 工程极轻】
- **现状**: `DataLoader.get_a_share_northbound_flow()` + `get_hk_southbound_flow()` 已存在
  - 路径: `src/quant_system/strategies/equity_factor/data/loader.py:555-568`
  - 数据: 通过 `akshare.stock_hsgt_hist_em` 拉北向/南向日级 net_buy
- **未使用**: 当前 backtest 没有任何策略消费这个数据
- **假设**: 入场前 N 日北向累计净流入 > 0 作为 quality gate / 加权信号
- **测试设计**:
  - 先 trades.csv 预检查（同 L8 套路）— 看 L9-A winner trades 入场前 5/10/20 日北向是否正
  - 若 winner 净流入显著正 (>60% 正)：3y A 股 momentum sweep 加 northbound_filter
  - 双窗口验证 → 落 yaml
- **预期**: +0.05-0.10 sleeve Sharpe, 组合 +0.02-0.04
- **工程**: 1 session（数据已在, 只需补 strategy.py 消费逻辑 + 单测）

#### A2. CSI1000 small-cap universe 上的 L9-B 重启
- **现状**: L9-B (ROIC + AR YoY) 在 HS300 证伪, 但 HS300 行业属性主导大盘股 → small-cap 可能不同
- **假设**: CSI1000 因子层未饱和, ROIC 在小盘有真实 alpha (区分"小而精"vs"小而烂")
- **风险**: CSI1000 universe size 1000 + 周转更高 → backtest 时间可能 3-5×
- **工程**: 1-2 session
- **执行前必读**: [[equity_factor_l9b_falsified_2026-05]] 末尾「未来 small-cap universe 可重启」段

### B. 实盘 KPI 跟踪（每月触发）

#### B1. 2026-06-30 第一次月度 KPI 报告
- **触发**: 实盘满 1 个月
- **入口**: `./venv/bin/python scripts/reporting/monthly_kpi_report.py --month 2026-06 --aum-cny <真实> --qqq-return <ytd 1m> --gld-return <ytd 1m>`
- **告警**: sleeve win rate < 30% / 组合月收益 < -2% / zhuang AUM > 30M
- **详见**: [[monthly_kpi_scaffold_2026-05]]

#### B2. Phase 2 KPI: 60d 滚动 ρ + MTD Sharpe
- **触发**: 实盘 ≥60 个交易日（≈ 2026-09 后）
- **数据源**: JournalSnapshot.unrealized_pnl_pct 日级 → sleeve daily MTM → ρ
- **工程**: 1 session

### C. 多策略 ensemble【中等 ROI, 中等工程】

- **假设**: 当前 equity_momentum 是 single signal (mom3m 0.20). 试 multi-period (mom3m 0.10 + mom6m 0.10) ensemble
- **历史**: factors.py 已有 momentum_6m 字段 (默认 0)
- **预期**: 不确定 — 短/中期 momentum 在 A 股大盘相关性高, ensemble 可能稀释而非增强
- **执行前**: 类似 L9-B 套路, 3y sweep + 8y verify

### D. HK 真做空 leverage【高 ROI, 高风险, 不可自主】

- **PM 决策**: 需明确实盘资金 + 合约管理批准
- **预期**: alpha 放大 1.5-2× (HK overlay 路线 D)
- **执行前必读**: [[hk_optimization_2026-05]]

## Cold-start 给新 session 的最重要 4 条

1. **不要再 sweep zhuang / equity_factor 参数 / 因子权重** — 三层 efficient set 已锁死, 13 条证伪覆盖所有自然候选
2. **不要假设"应该 sweep XXX"** — 先查 [[zhuang_l7a_falsified_2026-05]] / [[equity_factor_l9b_falsified_2026-05]] / [[v5_efficient_frontier_2026-05]] 确认未被证伪
3. **下个最高 ROI 是 A1 北向资金流 overlay** — 数据已在 loader, 工程极轻, 是 13 条证伪后唯一 cheap 的新维度信号
4. **2026-06-30 KPI 报告是硬节点** — 工具已就绪, 那天必跑

## 不要做（避免下个 session 重蹈覆辙）

- 不要再动 HS300 因子权重（含 ROIC / AR / fcf 任何方向）— L9-B + L8 双向都触底
- 不要再动 zhuang entry 参数（score / pos / cap）或加 fundamentals gate — L7A/L7B/L8 三向锁死
- 不要再加新资产到 v5（IBIT/TLT/CSI1000/任何）— 已是 efficient frontier
- 不要无 [[zhuang_l8_fundamentals_falsified_2026-05]] 模式的"trades.csv 预检查"就投 1+ session 接 loader
- 不要 sleeve sweep 不双窗口就落 yaml — 过拟合教训 (strong-conso 3y 赢 6y 反转)
- sleeve→组合放大率 ~0.45× — 任何 sleeve 改进 < 0.05 sharp 在组合层不显著（v5 vol 稀释）

## 关键 memory pointer（cold-start 必读）

- 三层 efficient set 同构: 本文件 + [[equity_factor_l9b_falsified_2026-05]] + [[zhuang_l7a_falsified_2026-05]] + [[v5_efficient_frontier_2026-05]]
- 用户协作风格: [[feedback_user_collab_style]]
- v5 实盘 KPI checklist: [[v5_efficient_frontier_2026-05]] 末尾
- 月度 KPI 工具入口: [[monthly_kpi_scaffold_2026-05]]
- 资金流数据: `src/.../loader.py:555-568` (loader 已就位, 无需重建)

**Why:** 三层 efficient set 同构是本 session 最大的结构性发现, 标志着 "strategy + 因子 + 组合" 三层架构在当前 universe + 信号集合下的 alpha 已彻底吃完。下个 session 必须明确转换思路: alpha 通道只剩"新维度（资金流/衍生品 sentiment）"和"新 universe（small-cap/HK 真做空）"两个方向, 在原架构内继续 sweep 是浪费。
**How to apply:** 新 session 启动后先读本文件 → 选 A1 北向资金流 overlay 推进（最高 ROI cheap 路径）→ 完成后 commit; 不在本 backlog 里的方向先 AskUserQuestion 确认必要性 + 引用本文件给出的"三层饱和"论据。
