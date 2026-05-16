---
name: zhuang L1/L2/L3 实验全量记录 2026-05-16
description: 10 个实验全量结果 — 6 L1 entry filters + 4 L2/L3 signal overlays；L1-E 最终 Sharper 1.37 (3y) / 1.35 (6y)
type: project
---

## 实验框架

- `scripts/run_experiment.py`：读取 base config → override 参数 → 全量回测 → 导出 summary JSON
- 所有实验 universe size **3307 只 A 股**
- 3 年窗口：2022-01-01 → 2024-12-31（726 天）
- 6 年窗口（验证）：2020-01-01 → 2026-05-04（1532 天）

baseline config:
- `accumulation_score_entry`: 65
- `entry_price_position_min`: 0.5
- `position_max_count`: 6

## L1 实验 (entry filter)

| tag | override | Sharpe | tot_ret | DD | trades | win% | pf |
|---|---|---|---|---|---|---|---|
| baseline | — | 0.965 | +17.3% | -5.5% | 90 | 41.1% | 2.97 |
| L1A-pos066 | pos=0.66 | 0.812 | +13.6% | -3.4% | 56 | 39.3% | 3.63 |
| L1A2-pos040 | pos=0.40 | 1.143 | +20.4% | -7.1% | 112 | 41.1% | 2.92 |
| L1A3-pos030 | pos=0.30 | 1.044 | +19.4% | -7.6% | 123 | 39.8% | 2.84 |
| L1B-score70 | score=70 | 1.022 | +15.8% | -3.6% | 56 | 44.6% | 3.14 |
| L1D-pos8 | max_pos=8 | 0.928 | +16.9% | -5.9% | 92 | 40.2% | 3.01 |
| **L1E-combined** | **pos=0.4 + score=70** | **1.370** | +20.1% | -4.1% | 63 | 46.0% | 3.37 |

## L2/L3 实验 (signal overlay, 基于 L1-E)

| tag | override | Sharpe | tot_ret | DD | trades | win% | pf |
|---|---|---|---|---|---|---|---|
| L1E (对照) | pos=0.4 + score=70 | 1.370 | +20.1% | -4.1% | 63 | 46.0% | 3.37 |
| L2A-rs0 | +rs≥0 | 0.520 | +10.1% | -3.3% | 47 | 42.5% | 2.84 |
| L2B-rs003 | +rs≥0.03 | 0.048 | +6.2% | -3.2% | 42 | 40.5% | 2.44 |
| L3A-vol80 | +vol≤80pct | 0.279 | +7.9% | -4.7% | 46 | 39.1% | 2.99 |
| L3B-vol70 | +vol≤70pct | -0.089 | +5.3% | -3.3% | 36 | 38.9% | 2.85 |

## 6 年验证 (L1-E only)

| tag | Sharpe | tot_ret | DD | trades | win% | pf |
|---|---|---|---|---|---|---|
| baseline (2020-2026) | 0.944 | +37.3% | -5.56% | 196 | 42.9% | 2.76 |
| L1E-validate-6y | **1.346** | +44.0% | **-3.77%** | 141 | **50.3%** | 2.89 |

## 结论

1. L1-E (`pos≥0.4 + score≥70`) 是最优 — 两窗口高度一致
2. L2 relative strength 在小盘庄股上负转移（砍信号）
3. L3 vol regime 同负转移
4. 下一步：更新 config.yaml 默认值、跑新 baseline 验收入门
