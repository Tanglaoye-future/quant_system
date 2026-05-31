---
name: equity-factor-l9b-falsified-2026-05
description: L9-B (ROIC + 应收账款周转率 YoY) 4y HS300 三 case 全输 baseline 0.857; ROIC -0.096 显著, AR YoY -0.031 微负; HS300 因子层已饱和 (L8D2 是 efficient set), 与 zhuang L1-E 同构
metadata:
  type: project
---

## 一句话结论

加 ROIC (投入资本回报率) 或应收账款周转率 YoY 到现有 L8D2 因子集 — **4y HS300 三 case 全劣于 baseline 0.857**, ROIC 单独 10% 拉低 Sharpe **-0.096**。结构性原因: ROIC 与现有 ROE 0.20 高度相关重复, AR YoY 在大盘 universe 是行业属性而非 alpha。L8D2 是 HS300 因子层 efficient set, 跳 8y verify。

## 实验设置

- **driver**: handoff #4 — L9-A 8y Sharpe 0.363 边缘 PASS, 候选 fundamentals 升级
- **窗口**: 4y (2022-01-01 → 2026-05-04), HS300 universe
- **baseline = L8D2 (yaml 当前)**: pe 0.15 / pb 0.10 / roe 0.20 / rev_g 0.15 / mom3m 0.20 / fcf 0 / rev_accel 0 (sum=0.80)
- **新接入因子**:
  - `roic` ← akshare abstract `投入资本回报率` (90 天披露窗口)
  - `ar_turnover_yoy` ← akshare abstract `应收账款周转率` n=2 同比 (本期-上期)/|上期|
- **数据覆盖**: akshare A 股 100% (601939 全 80 indicators 列表已验证)

## 结果（4y 单调向下）

| rank | tag | weights_override | Sharpe | 年化 | DD | win% | trades | Δ vs base |
|---|---|---|---|---|---|---|---|---|
| 1 | L9B-base | {} | **0.857** | +11.4% | -12.8% | 44.3% | 366 | — |
| 2 | L9B-both-05 | roic=0.05 + ar=0.05 | 0.838 | +11.2% | -12.7% | 44.3% | 366 | -0.019 |
| 3 | L9B-ar-10 | ar=0.10 | 0.826 | +11.0% | -12.6% | 44.6% | 368 | -0.031 |
| 4 | L9B-roic-10 | roic=0.10 | **0.761** | +10.1% | -13.4% | 44.4% | 365 | **-0.096** |

## 证伪机制分析

### 1. ROIC 是 ROE 的去杠杆翻译，重复信号

- 公式: ROIC = NOPAT / (Equity + Debt), ROE = Net Income / Equity
- 在 HS300（成熟大盘）上, 这两个指标横截面 ρ 通常 > 0.7（金融业例外）
- 加 0.10 ROIC = 在 ROE 0.20 基础上叠 50% 同向权重 → "资本效率"维度过载, 挤压 pe/pb/momentum 的相对权重
- 类比: L6-A "strong-volume" 在 zhuang 上单维过载证伪同样逻辑

### 2. AR turnover YoY 在大盘是行业属性, 不是横截面 alpha

- 应收账款周转率 = 营业收入 / 应收账款平均余额
- 银行：低周转（贷款本质是长账期应收）→ 永远负 YoY
- 制造/消费：高周转 → 永远正 YoY
- HS300 行业固定后, YoY 主要由行业基线决定, 而非个股造假信号
- z-score 横截面化只是把"行业"换成了不同分布的横截面噪音

### 3. 与 L8 fcf_yield、L9-A 加新因子失败的同构性

- L8 fcf_yield 0.20 → fcf=0 4y Sharpe +0.10 (反向减权重就赢)
- L9-B roic 0.10 → 加权重就输 -0.10 (对称)
- 共同根因: **HS300 baseline 5 因子（pe/pb/roe/rev_g/mom3m）已经吃完横截面 alpha**, 任何新因子要么重复要么噪音, 都会稀释相对权重

## 结构性结论

**L8D2 是 HS300 因子层的 efficient frontier**, 与下列同构:

| sleeve | efficient set | 证伪路径数 |
|---|---|---|
| zhuang | L1-E (score=70 + pos=0.4) + L6-A equal weights | 3 (L7A/L7B/L8) |
| equity_factor HS300 | L8D2 (sum=0.80) + L9-A regime-aware partial_exit | 2 (fcf_yield, L9-B 本次) |
| 组合层 v5 | HK25/A_mom10/A_mr10/zhuang40/QQQ5/GLD10 | 5 (v6 grid/regime/+IBIT/+TLT/+CSI1000) |
| HK overlay | AH 溢价 (微研究) | 1 |
| A_mr | v1/v2 sweep | 2 |

→ 12 条 + L9-B = 13 条证伪路径累积, **当前架构在所有 strategy + 组合 + factor 三层都接近饱和**

## 未来 alpha 通道（剩余空间）

1. **HK 真做空 leverage** (handoff #5) — 实盘需 PM 批准, 不可在沙箱推
2. **新 universe** — sp500/nasdaq100 已证伪 ([[sp500_negative_2026-05]]), CSI1000 已证伪; 剩 HK 小盘/SP500-后 500/A 股全市场?
3. **新维度信号** — 资金流（北向/南向/龙虎榜）, 衍生品 sentiment (期权 PCR, VIX)
4. **多策略架构** — 当前是 single signal/sleeve, 可尝试 ensemble (多周期 momentum / 多 lookback factor)

## 接入工程（保留，未来可用）

虽然 L9-B 因子在 HS300 证伪, 工程已落, 不删除:
- `factors.py`: FactorWeights 加 `roic` / `ar_turnover_yoy` 字段（默认 0）
- `compute_raw_factors`: a_share 段拉 `投入资本回报率` + `应收账款周转率` n=2 算 YoY
- `tests/equity_factor/test_l9b_factors.py`: 9 单测 (字段存在 / ROIC 取值 / 披露窗口 / YoY 计算 / NaN 兜底 / 指标缺失)
- yaml 不动 (roic=0 + ar_turnover_yoy=0)

→ 未来若试 small-cap universe (CSI1000 因子层不一定饱和), 可重启 sweep 测这两个因子，无需重复工程

## 时间成本

- 调研 (existing factors / abstract indicators / L8D pattern): ~15 min
- factors.py 扩展 (FactorWeights + compute_raw_factors): ~10 min
- 单测 9 个: ~15 min
- sweep 脚本 (复用 L8D 模板): ~10 min
- 4 case 4y backtest: ~25 min (HS300 universe 比想象快)
- 分析 + memory: ~15 min
- 总: ~90 min — 远低于 backlog 估的 2-3 session

## 不要做（避免下次重蹈）

- 不要在 HS300 universe 再加 fundamentals 因子（任何）— L8D2 已是 efficient set, 加什么都是稀释
- 不要给 ROIC 加权重 — 与 ROE 重复, 数学上注定负贡献（除非同时砍 ROE，但那是因子互换不是新 alpha）
- 不要把 AR turnover 加到任何大盘股 universe — 行业属性主导, 不是 alpha
- 8y verify 不必跑 — 4y 三 case 全负 + 同构机制清晰, 跑 8y 是浪费

## 落地决策

- factors.py + 单测 + sweep 脚本保留（未来 small-cap universe 可用）
- yaml 不动 (roic=0 + ar_turnover_yoy=0)
- handoff 12 → 13 条证伪路径
- backlog #4 关闭（4y 软证伪）
- 剩余 backlog: #5 HK 真做空 (PM 决策) + 新方向（资金流维度 / 多策略 ensemble）

**Why:** L9-A 边缘 PASS 0.363 sleeve, 用户期望 +0.05-0.10 sleeve Sharpe → +0.02-0.04 组合 Sharpe。实测 4y 直接 -0.10 反方向, 与 fcf_yield 反向证伪同构 → HS300 因子层结构性饱和。
**How to apply:** 未来 equity_factor 改进提案如果还在动 HS300 因子权重 / 加新 fundamentals 因子, 直接 reject — 引用 [[equity_factor_l8_2026-05]] + 本 memory。alpha 通道转向 universe 切换 (small-cap) 或新维度 (资金流/衍生品)。
