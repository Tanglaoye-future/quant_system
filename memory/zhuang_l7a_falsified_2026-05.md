---
name: zhuang-l7a-falsified-2026-05
description: L7-A position_max_count 6/8/10 三 case 3y 同分 → cap 在 L1-E 严入场下永不 binding；证伪 + 反向洞察 "入场严格度 dominates 仓位上限"
metadata:
  type: project
---

## 一句话结论

`position_max_count` 从 6 提到 8/10 在 L1-E 入场（pos≥0.4 + score≥70）下**零边际效应** — 3y 三 case 跑出**完全相同**的 Sharpe 1.505 / 收益 +25.4% / DD -2.63% / 58 trades，cap 永不 binding。L7-A 直接证伪，跳过 6y verify。

## 实验设置

- **窗口**: 3y (2022-01-01 → 2024-12-31), 726 交易日
- **入场 (yaml)**: L1-E (`entry_price_position_min=0.4` + `accumulation_score_entry=70`)
- **权重 (yaml)**: L6-A equal (0.20×5)
- **universe**: 2497 只 A 股 (`universe_2022-01-01.csv`)
- **cases**: position_max_count ∈ {6 (baseline), 8, 10}

## 结果（3 case 同分）

| tag | pos | Sharpe | Ret% | DD% | N | win% | pf |
|---|---|---|---|---|---|---|---|
| L7A-posmax6 | 6 | +1.505 | +25.37 | -2.63 | 58 | 51.7% | 3.24 |
| L7A-posmax8 | 8 | +1.505 | +25.37 | -2.63 | 58 | 51.7% | 3.24 |
| L7A-posmax10 | 10 | +1.505 | +25.37 | -2.63 | 58 | 51.7% | 3.24 |

## 并发持仓分布（解释为何同分）

| 并发数 | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|---|
| 天数 | 517 | 110 | 74 | 13 | 4 | 6 | 4 |
| 占比 | 71% | 15% | 10% | 1.8% | 0.6% | 0.8% | 0.5% |

- **均值并发**: 0.5（远低于 cap 6）
- **打到 6 的天数**: 仅 4 天 (0.5%)
- **L1-E 入场太严**: 71% 时间空仓，扩 cap 根本接不到新机会

## 反向洞察（重要 — 给未来 session）

**L1-E (pos≥0.4 + score≥70) 把入场流量压到 mean concurrent 0.5 仓位** — 这意味着：

1. **`position_max_count` 不是当前瓶颈** — 后续 L7 系列调它属于无效优化路径
2. **真正的边际** 在入场过滤层：
   - 放宽 score (70→65) 同时保留 pos≥0.4：是否能用上闲置仓位且不显著掉 Sharpe?
   - baseline 65+pos=0.5 历史 Sharpe 0.965（[[zhuang_l1_l2_l3_experiments_2026-05]]）
   - L1-E 65+pos=0.5 → 70+pos=0.4 把 trades 从 90 压到 63 Sharpe 提到 1.370
   - **未测过的组合**: 65+pos=0.4（用 pos 滤但放 score）可能找到新中间点
3. **若想增加暴露**，比起调 cap，更应该考虑：
   - 入场松绑 + 配合 L5 tiered position 自动给低分小仓
   - L9-A 加 fundamentals 因子做正向过滤而非阈值 gate

## 时间成本

- 工程: ~10 min（写 sweep 脚本 `run_l7a_zhuang_posmax_sweep.py`）
- 计算: ~15 min（3 case 串行 × ~5 min/case, posmax6 单 case 才 1338 字节 log）
- 总: ~25 min — 证伪成本低

## 不要做（避免下次重蹈）

- 不要再对 `position_max_count` 做 sweep 直到 L1-E 入场放宽 — 否则 cap 仍然 not binding
- 不要假设"更大 cap = 更多 alpha" — 必须先看 concurrent position 分布
- 不要无诊断地落 yaml — 4 天打满 cap 不构成需要放大的依据

## 落地决策

- **yaml 保持 `position_max_count: 6` 不变** — 无需改动
- **handoff backlog 移除 L7-A** — 9 条证伪路径升级到 10 条

**Why:** L7-A 在 [[session_2026_05_31_handoff]] 里被排为最高 ROI 待做，但实测一开就同分证伪，把 sleeve 优化思路从"调上限"转到"调入场严格度"或"加 fundamentals"。
**How to apply:** 未来 zhuang sleeve 优化先看 `trades.csv` 算 mean concurrent；如果 < cap × 60%，cap 优化路径直接跳过。
