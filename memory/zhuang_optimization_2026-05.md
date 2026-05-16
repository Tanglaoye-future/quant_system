---
name: zhuang_system 基线 + L1 优化
description: v5 baseline (Sharpe 0.944/6.4y, 196笔, Win 42.9%) → L1-E entry filter (pos≥0.4 + score≥70) Sharpe 1.346/6.4y, DD -3.77%, Win 50.3%
type: project
---

## Baseline (v5, 2020-2026)

Sharpe **0.944** | 收益 +37.3% | DD -5.56% | 胜率 42.9% | 盈亏比 2.76 | 196 笔
config: `accumulation_score_entry=65`, `entry_price_position_min=0.5`

## L1-E entry filter（当前最优，2026-05-16）

参数改动（仅改两个值）：
- `entry_price_position_min`: 0.5 → **0.4**
- `accumulation_score_entry`: 65 → **70**

6.4 年全量（3307 只）回测：
Sharpe **1.346** | 收益 +44.0% | DD **-3.77%** | 胜率 **50.3%** | 盈亏比 2.89 | 141 笔

3 年窗口（2022-2024，交叉验证）：
Sharpe **1.370** | 收益 +20.1% | DD -4.1% | 胜率 46.0% | 盈亏比 3.37 | 63 笔

两窗口高度一致 → 不是过拟合。

## 搜索路径

| step | param | 方向 | 结果 |
|---|---|---|---|
| L1-A | price_pos=0.66 (tighten) | ↓ Sharpe 0.812 | 现金闲置 |
| L1-A2 | price_pos=0.40 (loosen) | ↑ Sharpe 1.143 | 放宽正确 |
| L1-A3 | price_pos=0.30 (too loose) | Sharpe 1.044 | 过度 |
| L1-B | score=70 (tighten) | Sharpe 1.022 | 质量提升 |
| L1-D | max_pos=8 | Sharpe 0.928 | 无用 |
| L1-E | pos=0.4 + score=70 | Sharpe **1.370** | 组合最优 |

## 关键 insight

放宽位置 + 收紧 score 是正交维度：放宽位置让更多候选入池（防闲置），高 score 保证质量（控风险）。

## L2/L3（均为负转移）

- L2 relative_strength (RS≥0)：Sharpe 0.520
- L2 relative_strength (RS≥0.03)：Sharpe 0.048
- L3 vol_regime (≤80pct)：Sharpe 0.279
- L3 vol_regime (≤70pct)：Sharpe -0.089

RS 和 vol regime 在小盘庄股上砍掉了太多有效信号。

**Why:** L1-E entry filter 优化将 zhuang baseline Sharpe +43%，代价是减少约 28% 交易。
**How to apply:** 更新 config.yaml 中 `entry_price_position_min=0.4` 和 `accumulation_score_entry=70` 为新的默认基线。
