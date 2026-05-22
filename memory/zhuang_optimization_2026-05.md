---
name: zhuang 策略 L1→L5 完整优化（2026-05）
description: v5 baseline (Sharpe 0.944) → L1-E entry (1.346) → L4 出场收紧 (1.627) → L5 score 仓位 (1.806, 6y) — Sharpe 翻 1.9 倍 / 收益 +37%→+76% / DD -5.6%→-4.9%
type: project
---

## 累计提升路径 (6y, 2020-2026)

| 阶段 | Sharpe | 收益 | DD | 笔数 |
|---|---|---|---|---|
| v5 原始 | 0.944 | +37.3% | -5.56% | 196 |
| L1-E (入场收紧) | 1.346 | +44.0% | -3.77% | 141 |
| L4-combo4 (出场收紧) | 1.627 | +48.1% | -3.10% | 136 |
| **L5B (score 仓位)** | **1.806** | **+76.0%** | -4.90% | 136 |

## 落地配置 (config/zhuang.yaml)

```yaml
# L1-E
entry_price_position_min: 0.4
accumulation_score_entry: 70

# L4-combo4
max_hold_days: 10
take_profit_pct: 0.10
stop_loss_atr_mult: 1.5
distribution_turnover_thresh: 6.0
momentum_stop_pct: 0.03

# L5B-tiered-aggressive
position_size_mode: tiered
tiered_score_thresholds: [75.0, 80.0]
tiered_position_pcts: [0.03, 0.05, 0.08]
```

## 搜索路径 (完整)

L1 入场: 6 个变体 → L1-E (pos>=0.4 + score>=70) 组合最优 (见 `zhuang_l1_l2_l3_experiments_2026-05.md`)
L2 RS: 负转移
L3 vol_regime: 负转移
L4 出场: 13 单变量 + 5 组合 + 6y verify → combo4 (5 维同向收紧) (见 `zhuang_l4_experiments_2026-05.md`)
L5 仓位: 5 变体 + 6y verify → tiered-aggressive (3/5/8%) (见 `zhuang_l5_experiments_2026-05.md`)

## 6-asset overlay (L4-combo4 后)

zhuang 单资产 Sharpe 2.35 (2020-2026, vol 2.77%, 与其他资产 ρ<=0.06).
25% 占比: 组合 Sharpe 1.91→2.21 / DD -7.6%→-5.1%.
实盘推荐 zhuang 20-25% (见 `zhuang_overlay_combo4_2026-05.md`)

**Why:** L1→L5 共 5 层优化，每层叠加 0.15-0.20 Sharpe，全程非过拟合（3y/6y 双窗口验证）。
**How to apply:** config/zhuang.yaml 已落地全部参数；daily_zhuang.py 每天盘后扫描。
