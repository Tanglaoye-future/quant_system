---
name: session-2026-06-01-handoff
description: 2026-05-31~06-01 session 总账 + 下个 session cold-start backlog；5 条新证伪 (10→14) + 月度 KPI 脚手架 + 南向 gate 接入；四层 efficient set 同构 (L8D2 HS300 / L1-E zhuang / v5 组合 / HK widen-on) → strategy + 因子 + 组合三层架构全饱和；剩余 alpha 通道仅 small-cap / 真做空 / 实盘 KPI
metadata:
  type: project
---

## 当前状态 (2026-06-01 收工)

- **v5 部署不变** (HK25/A_mom10/A_mr10/zhuang40/QQQ5/GLD10) — 14 条证伪路径 + 四层 efficient set 同构证 v5 是真 frontier
- **实盘窗口**: 2026-05-30 起, **2026-06-30 是第一次月度 KPI checkpoint**（工具就绪）
- 本 session 7 commit (全部 push origin/main):
  - 3f34bd9 L7-A position_max_count 证伪
  - 9da1470 L7-B score 反向证伪
  - 8fd1bdb L8 zhuang fundamentals gate 软证伪
  - 4c6aa2e v5 月度 KPI 报告脚手架 (10 单测)
  - b8f1738 L9-B ROIC/AR YoY 接入 + 证伪 (9 单测)
  - b98e15f 06-01 handoff 初稿 + 三层 efficient set
  - **f31bdd9 A1 北向死 + A1' HK 南向 gate 接入 + 4y 证伪 (8 单测)**
- 本 session 9 个新 memory: zhuang_l7a/l7b/l8 + equity_factor_l9b + monthly_kpi_scaffold + a1_northbound_dead_southbound_alive + a1prime_southbound_gate_falsified + 本文件
- 测试基线: **192 passed, 0 regression**

## 14 条已证伪路径累积（按类别分组）

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

### HK sleeve（1 条 — 2026-06-01）
- **A1' 南向 gate (10d/200亿): 4y Sharpe 1.080 → 1.022 (-0.058) widen+gate 互斥**

### 数据源死亡（1 条 — 2026-06-01, 不算 strategy alpha 但同等重要）
- **A1 北向 stock_hsgt_hist_em 2024-08 起永久 NaN, akshare 无替代; 不投 backtest**

## 🔑 四层 efficient set 同构（本 session 核心结构发现）

| 层 | efficient 配置 | 证伪路径 |
|---|---|---|
| 组合层 v5 | HK25/A_mom10/A_mr10/zhuang40/QQQ5/GLD10 | 5 |
| HS300 因子层 | L8D2 (pe 0.15 / pb 0.10 / roe 0.20 / rev_g 0.15 / mom3m 0.20, fcf=0 + L9-B=0) | 2 |
| zhuang sleeve | L1-E (score=70 + pos=0.4) + L6-A equal weights | 3 |
| HK sleeve | widen on + L9-A regime partial + factor weights (gate=off) | 1 (A1') |

**结论**: strategy 层 (zhuang + HK) + 因子层 (HS300) + 组合层 (6-asset) **四层在当前 universe + 信号集合下都已饱和**。

## 🔑 核心教训 — 预检查正向 ≠ backtest 正向（4 次同模式）

| 路径 | 预检查信号 | backtest 结果 |
|---|---|---|
| L7-A pos_max | 假设 cap binding 增量 8% | 三 case 同分 (cap 不 binding) |
| L8 fundamentals gate | ROE>0 是质量信号 | winner/loser ROE 占比反向, 误杀 47% |
| L9-B ROIC | 因子 100% 覆盖, 数据完美 | -0.096 Sharpe (与 ROE 重复) |
| **A1' southbound gate** | **mean pnl_pct +37%** | **Sharpe -0.058 (base rate spurious)** |

**根因 3 类**:
1. **Base rate spurious correlation** — trades.csv 的 winner 入场日先验已在好市场段, 不是 gate 能"提前识别"的可交易信号
2. **信号互斥** — 已有 widen 与新 gate 反向, 或 ROIC 与 ROE 同向重复
3. **Sample size 压扁** — 过滤后 trades 数减 17-50% 把统计 Sharpe 直接打死

**未来纪律**: trades.csv 后验分析 ≠ 真 backtest, 预检查正向必须先排除这 3 个风险, 否则 1-2 hr backtest 工程基本上是浪费。

## 剩余 alpha 通道（极度收敛）

按 ROI × 风险排:

### A2. CSI1000 small-cap universe L9-B 重启【可自主推, 最高 cheap ROI】
- **现状**: L9-B (ROIC + AR YoY) 在 HS300 证伪, 但 HS300 大盘行业属性主导 → small-cap 可能不同
- **假设**: CSI1000 因子层未饱和, ROIC 在小盘区分"小而精"vs"小而烂"; AR YoY 在小盘可能不被行业噪声淹没
- **工程已落** (b8f1738): factors.py + 9 单测 + sweep 模板, 改 market='a_share' + universe='csi1000' 即可
- **风险**: CSI1000 universe 1000 + 周转更高 → backtest 时间 3-5×; 数据接入需确认 baostock 覆盖
- **预期**: 不定 (中等概率为正), sleeve +0.05-0.10 / 组合 +0.02-0.04
- **预期工程**: 1-2 session
- **执行前必读**: [[equity_factor_l9b_falsified_2026-05]] 末尾 + 本文件"4 次同模式"

### C. 多策略 ensemble (mom3m + mom6m)【中等 ROI, 中等工程】
- **假设**: 当前 equity_momentum 单 signal (mom3m 0.20). 试 multi-period (mom3m 0.10 + mom6m 0.10) ensemble
- **历史**: factors.py 已有 momentum_6m 字段 (默认 0), 数据已就位
- **风险**: 短/中期 momentum 在 A 股大盘相关性可能高, ensemble 稀释而非增强 (与 ROIC/ROE 同样模式)
- **类比警告**: 这与 L9-B ROIC 失败逻辑同构 — 测试前先看 mom3m / mom6m 横截面 ρ
- **执行前**: 先算 HS300 两 momentum 横截面相关性, 若 > 0.7 → 直接软证伪不做 backtest

### B1. 2026-06-30 第一次月度 KPI 报告【硬节点】
- **触发**: 实盘满 1 个月 (= 2026-07-01 跑)
- **入口**: `./venv/bin/python scripts/reporting/monthly_kpi_report.py --month 2026-06 --aum-cny <真实> --qqq-return <ytd 1m> --gld-return <ytd 1m>`
- **告警**: sleeve win rate < 30% / 组合月收益 < -2% / zhuang AUM > 30M
- **详见**: [[monthly_kpi_scaffold_2026-05]]

### B2. Phase 2 KPI: 60d 滚动 ρ + MTD Sharpe【实盘 ≥60 个交易日后】
- **触发**: ≈ 2026-09 后
- **数据源**: JournalSnapshot.unrealized_pnl_pct 日级 → sleeve daily MTM → ρ
- **工程**: 1 session

### D. HK 真做空 leverage【高 ROI, 高风险, 不可自主】
- **PM 决策**: 需明确实盘资金 + 合约管理批准
- **预期**: alpha 放大 1.5-2× (HK overlay 路线 D)
- **执行前必读**: [[hk_optimization_2026-05]] 路线 D

### 已死方向（不要再做）
- ~~A1 北向 overlay (任何形式)~~ — 数据源 2024-08 永久封死
- ~~A1' HK 南向 gate (任何 threshold)~~ — widen+gate 互斥 + base rate spurious, 4y 证伪

## Cold-start 给新 session 的最重要 5 条

1. **四层架构已饱和** — 不要再 sweep zhuang / HK / HS300 因子 / 组合权重, 14 条证伪覆盖所有自然候选
2. **预检查正向 ≠ backtest 正向** — 4 次同模式打脸, 投 backtest 前先排除 base rate / 信号互斥 / sample 压扁 三类风险
3. **下个最高 ROI 是 A2 CSI1000** — 工程已落 (factors.py + sweep 模板可改 market 即跑), 但 universe 接入需先验证 baostock 覆盖
4. **2026-06-30 KPI 报告是硬节点** — 工具已就绪 (`scripts/reporting/monthly_kpi_report.py`), 那天必跑
5. **资金流数据 A 股北向已死, HK 南向 4y 反向** — 不要再做任何"资金流 overlay" 方向 (除非接到非 akshare 的新数据源)

## 不要做（避免下个 session 重蹈覆辙）

- 不要再动 HS300 因子权重 (含 ROIC / AR / fcf 任何方向) — L9-B + L8 双向都触底
- 不要再动 zhuang entry 参数 (score / pos / cap) 或加 fundamentals gate — L7A/L7B/L8 三向锁死
- 不要再动 HK widen / gate / RSI 带 / 量能门槛 — A1' 证伪 + [[hk_optimization_2026-05]] v1-v10 都做过
- 不要再加新资产到 v5 (IBIT/TLT/CSI1000/任何) — 已是 efficient frontier
- **不要"trades.csv 预检查正向就投 backtest"** — 必须先识别 base rate / 信号互斥 / sample 压扁
- 不要 sleeve sweep 不双窗口就落 yaml — 过拟合教训 (strong-conso 3y 赢 6y 反转)
- sleeve→组合放大率 ~0.45× — 任何 sleeve 改进 < 0.05 sharp 在组合层不显著 (v5 vol 稀释)
- 不要尝试 akshare hsgt 任何接口取日级北向 — 全停, 实测过

## 关键 memory pointer（cold-start 必读）

- 四层 efficient set 同构: 本文件 + [[equity_factor_l9b_falsified_2026-05]] + [[zhuang_l7a_falsified_2026-05]] + [[a1prime_southbound_gate_falsified_2026-06]] + [[v5_efficient_frontier_2026-05]]
- 预检查 paradox 教训: [[a1prime_southbound_gate_falsified_2026-06]] (含 4 次同模式对比表)
- 资金流数据死亡: [[a1_northbound_dead_southbound_alive_2026-06]] (含 akshare 全接口实测)
- 用户协作风格: [[feedback_user_collab_style]]
- v5 实盘 KPI checklist: [[v5_efficient_frontier_2026-05]] 末尾
- 月度 KPI 工具入口: [[monthly_kpi_scaffold_2026-05]]

## 工程入口（接 backlog 用）

- `scripts/backtest/run_l9b_factor_sweep.py` — HS300 sweep 模板 (改 market='a_share' + universe='csi1000' 给 A2 用)
- `scripts/research/zhuang_l8_fundamentals_precheck.py` — fundamentals 预检查模板
- `scripts/research/hk_southbound_overlay_precheck.py` — trades.csv 后验分析模板 (注意 paradox 教训)
- `scripts/reporting/monthly_kpi_report.py` — 月度 KPI 报告入口
- `src/quant_system/strategies/equity_factor/timing/signals.py` — TimingConfig 已有 southbound_gate 字段 + entry_signal_from_enriched gate logic (默认 disabled)

**Why:** 四层 efficient set 同构 + 预检查 paradox (4 次同模式) 是本 session 两大结构性发现。前者锁死当前架构内的优化空间, 后者给未来"看似有信号" 的提议提供 sanity check 框架。下个 session 必须明确转换思路: alpha 通道只剩"新 universe (CSI1000 small-cap / HK 真做空 leverage)" 和"实盘 KPI 跟踪" 两条线, 在原架构 sweep 是浪费。
**How to apply:** 新 session 启动后先读本文件 → 第一选项 A2 CSI1000 (但要先验证 baostock 数据覆盖 + 用本文件 paradox 表 sanity check 假设) → 完成后 commit; C 多策略 ensemble 是次选 (但同样需先做 mom3m/mom6m 相关性预检); B1 视日期触发; D HK 真做空必须用户批准。
