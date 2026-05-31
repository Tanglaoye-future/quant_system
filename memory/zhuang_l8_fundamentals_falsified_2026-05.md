---
name: zhuang-l8-fundamentals-falsified-2026-05
description: L8 fundamentals quality gate 预检查软证伪 — 庄股 alpha 与 ROE/营收增速几乎正交 (winner ROE>0 占 73%, loser ROE>0 占 79% 反而更高)；联合 gate 误杀比 47% ≈ 随机
metadata:
  type: project
---

## 一句话结论

把 L7B-score70 (= L1-E) 的 58 笔 trades 喂 fundamentals (akshare stock_financial_abstract, ROE / 营收增速 / 净利润增速 as-of entry date, 100% 覆盖) — **winner/loser 的 fundamentals 分布几乎相同**, 联合 gate (ROE>0 AND 营收增速>0) 误杀比 47% 接近随机。不接 loader、跳完整 sweep，省 1-2 hr 工程。

## 实验设置

- **driver**: L7-A + L7-B 双向证伪 zhuang sleeve 参数 sweep 后, 外部信号是唯一 alpha 通道
- **候选**: handoff #3 「入场加 ROE>0 + 营收增速>0」
- **方法**: 跑 L7B-score70 的 58 笔 trades, 每笔 entry_date as-of 90 天发布滞后取最新 abstract value
- **fundamentals 覆盖率**: ROE 58/58 (100%), 营收增速 58/58, 归母净利增速 58/58 — akshare A 股全覆盖, 后续接入零数据风险

## 关键分布（30 winner / 28 loser, base win rate 51.7%）

| 维度 | winner > 0 | loser > 0 | 反差 |
|---|---|---|---|
| ROE | 22/30 (73.3%) | 22/28 (**78.6%**) | loser 略高于 winner |
| 营收增速 | 18/30 (60.0%) | 14/28 (50.0%) | winner 略高 (+10pp) |
| 净利增速 (未做 gate) | — | — | — |

**ROE 在 winner/loser 几乎完全相同** — 这就是 fundamentals gate 失败的核心证据：庄股 winner 不是因为基本面好启动, loser 也不是因为基本面差失败, 这两组的 ROE 分布几乎同色。

## 联合 gate 模拟 (ROE>0 AND 营收增速>0)

| 桶 | n | 占原桶 % |
|---|---|---|
| keep winner | 16/30 | 53.3% |
| keep loser | 12/28 | 42.9% |
| **drop winner (误杀)** | 14 | 46.7% |
| drop loser (有效) | 16 | 57.1% |
| **误杀比** = drop_winner / drop_total | **47%** | ≈ 随机 |

| 指标 | gate 前 | gate 后 | Δ |
|---|---|---|---|
| win rate | 51.7% | 57.1% | +5.4pp（看似改善）|
| trades | 58 | 28 | -51.7%（**腰斩**）|

**为何 win rate +5.4pp 不是利好**: trades 减半意味着 sleeve 暴露时间和 trade 数双砍, 单 trade 收益分布无显著改善（pf 改善不可见, 没单测）, **Sharpe 极可能下跌**（sleeve vol 不变, 收益砍掉 ~47%）。

## 与 L2/L3 信号 overlay 的同构性

[[zhuang_l1_l2_l3_experiments_2026-05]] L2/L3:
- +rs≥0 (relative strength): Sharpe 1.370 → 0.520
- +vol≤80pct (vol regime): Sharpe 1.370 → 0.279

L2/L3 已经证明: **入场端任何额外 filter 都是负转移** — 庄股的 alpha 锁在 score+pos 这两个吃货期信号里, 加任何其他维度都是稀释 alpha + 引入噪音。L8 fundamentals 完全符合这个模式 — 把 fundamentals 当 binary gate 等于又加一层负转移过滤器。

## 反向洞察 — 为何庄股 alpha 与 fundamentals 正交

1. **庄股本质是资金驱动**, 不是基本面驱动 — 主力吃货阶段 (我们捕获的 phase A) 通常发生在**业绩低谷或事件预期前**, 这时业绩往往是负的（营收增速<0 winner 占 40% 印证）
2. **fundamentals 是滞后信号** — ROE/营收增速反映过去 1-3 季度, 但庄股拉升期通常在 fundamentals 转好之前启动（领先时间 = 主力 alpha）
3. **akshare A 股 publication_lag=90 天** — 即使数据完全准确, 真实可用的是 3-12 个月前的 fundamentals, 这跟"3-5 天的吃货 → 5-10 天拉升"的庄股节奏完全错配

## 时间成本

- 工程: ~15 min（写预检查脚本, 复用 equity_factor DataLoader）
- akshare 拉 abstract: ~3 min (58 unique codes, cache 后续可复用)
- 总: ~20 min — 证伪成本极低, 省了 1-2 hr 全 sweep 工程

## 不要做（避免下次重蹈）

- 不要再做 zhuang fundamentals binary gate (ROE>0 / 营收>0 / 净利>0 / 任何阈值)
- 不要尝试"放宽 fundamentals 阈值"（如 ROE>-5）— 47% 误杀比说明结构性正交, 不是阈值问题
- 不要把 fundamentals 加入 accumulation_score 作第六维（同样会稀释前五维 alpha, 跟 strong-volume 过拟合教训同构）
- 如果未来真要做 fundamentals overlay, 应该在 **survivor universe filter** 层（如剔除连续 3 年亏损 + 即将退市股）而不是 entry signal 层

## 落地决策

- yaml 不动
- handoff 11 → 12 条证伪路径
- 下个 zhuang 优化方向: **L4 出场端续作 + L5 仓位 sizing 优化** (相关 memory: [[zhuang_l4_experiments_2026-05]] / [[zhuang_l5_experiments_2026-05]]) 或外部 **资金流维度** (北向流入 / 龙虎榜机构席位) 才是真正的外部信号通道, 不是 fundamentals

**Why:** zhuang 在 strategy 层进一步证伪 — L7A 仓位, L7B score, L8 fundamentals 三个方向全证伪后, 明确把 zhuang 划入"capacity-constrained alpha sleeve, 当前架构已饱和"。
**How to apply:** 未来 zhuang 改进提案如果还在动 entry filter / score 阈值 / fundamentals gate, 直接 reject — 引用 L7A/L7B/L8 三条 memory。
