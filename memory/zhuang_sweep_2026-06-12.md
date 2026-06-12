---
name: zhuang-full-sweep-2026-06-12
description: 2026-06-12 — zhuang 全维度参数 sweep (B1-B6)；extreme sizing 落地 config，max_stop=4% 噪音级改进未落
metadata:
  type: project
---

## 背景

[[zhuang_l6a_weights_2026-05]] L6A equal weights 落地后，take-profit (10%)、score-tier thresholds ([75,80]) 从未在新基线下重测。入场/出场/权重/cap 已被 L1-L8 锁死，但 6 个 stop/tp/sizing 维度未独立 sweep。

## Harness

`scripts/backtest/run_full_sweep_zhuang.py` — 3y 快扫 → 8y 验证 → combo，resume 支持。

## Phase 1: 3y 快扫 (2022-2024, 2496 只)

T+1 模式下 3y 全部负 Sharpe，但相对排名用于选 top-1 per category。

| B1 take_profit | 8%= -0.94, 12%= -0.52, 15%= -0.64 → tp=12% 最优（与 baseline 10% 持平）|
|---|---|
| B2 atr_mult | 1.0 -0.49, 1.5 -0.51, 2.0 -0.52 → atr=1.0 微赢 |
| B3 max_stop | 4% -0.42, 6% -0.51, 8% -0.52 → max_stop=4% 赢 |
| B4 min_dist | 0% -0.41, 3% -0.51, 5% -0.62 → min_dist=0% 赢 |
| B5 mom_stop | 3% -0.51, 5% -0.51, 7% -0.51 → mom=7% 持平 |
| B6 sizing | extreme [70,85]→[2%,5%,10%] -0.39 最优 |

## Phase 2: 8y 验证

| Variant | 8y Sharpe | 8y Ret | 8y DD | WR | N |
|---|---|---|---|---|---|
| baseline | 0.253 | +36.3% | -10.3% | 35.6% | 160 |
| B4 min_dist=0% | **-0.307** | +4.8% | -11.9% | 28.5% | 200 |
| ⭐ B6 extreme sizing | **0.282** | **+45.6%** | -12.3% | 35.6% | 160 |

**B4 min_dist=0% 灾难级反转** — 3y 最优但 8y 崩盘（交易暴增至 200 笔，收益蒸发）。验证 min_stop_distance 的长期保护作用。

## Phase 3: Combo

combo (max_stop=4% + extreme sizing) 8y Sharpe 0.286 Ret +46.4% DD -12.6%
baseline: Sharpe 0.253 Ret +36.3% DD -10.3%

## 落地

config/zhuang.yaml 仅落 extreme sizing：

```yaml
tiered_score_thresholds: [70.0, 85.0]    # 曾 [75.0, 80.0]
tiered_position_pcts: [0.02, 0.05, 0.10] # 曾 [0.03, 0.05, 0.08]
```

max_stop=4% 单独增量 +0.006 噪音级，不落地。

## 逻辑

lottery-ticket 结构（35% 胜率，3x 盈亏比）下少数高分大赢家扛全部 alpha。极端化 sizing（低分 2% / 高分 10%）把仓位集中在真正的 alpha 来源上，是 multiplier 而非 selection。

## 不要做

- 不要再碰 min_stop_distance — 3% 是 sweet spot，0% 8y 灾难，5% 3y 恶化
- 不要再 sweep take_profit / atr_mult / mom_stop — 当前值已是 local optimum
- tiered sizing 阈值不要再微调 — 该维度已证明有效且逻辑自洽

## 关联

- [[zhuang_l5_experiments_2026-05]] — L5B tiered sizing 首次落地
- [[zhuang_l7b_falsified_2026-05]] — 入场阈值 sweep 证伪
- [[zhuang_gap_score_precheck_falsified_2026-06]] — gap/score 过滤证伪
- [[zhuang_overlay_combo4_2026-05]] — L4 出场 combo4
