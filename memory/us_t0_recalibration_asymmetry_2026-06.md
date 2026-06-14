---
name: us-t0-recalibration-asymmetry-2026-06
description: 2026-06-14 — US t+0 recal 双策略反向 — SP500 同 HK 改善 (4y +0.153 / 8y +0.031 Sharpe), NASDAQ100 反向恶化 (4y -0.195 / 8y -0.029); 揭示 T+0 不是普适改善, 集中度/趋势性强的 universe 早出场反伤 alpha; 两策略 baseline 仍负不解救
metadata:
  type: project
---

# US T+0 recalibration — 双策略反向不对称（2026-06-14）

## 一句话

HK T+0 recal +0.06 Sharpe 后跑 US 双策略，**SP500 同向改善 4y +0.153 / 8y +0.031**，但 **NASDAQ100 反向恶化 4y -0.195 / 8y -0.029**。两策略 baseline 仍负 Sharpe → T+0 是语义正确性但**不解救** [[sp500_negative_2026-05]] / [[three_universe_2026-05]] 结论。揭示 T+0 不是普适改善：集中度高+趋势性强的 universe 早出场会过早砍掉强势股。

## 双窗口结果

### equity_us_momentum (NASDAQ100, capital_pct=0, deprecated)

| window | mode | Sharpe | Ret | DD | WR | N |
|---|---|---|---|---|---|---|
| 4y | t+1 | -0.222 | -7.31% | -24.83% | 42.5% | 273 |
| 4y | **t+0** | **-0.417** | -17.45% | -29.77% | 40.1% | 277 |
| 8y | t+1 | +0.099 | +22.65% | -18.72% | 41.6% | 529 |
| 8y | **t+0** | **+0.069** | +19.13% | -22.77% | 40.0% | 545 |

**Δ 反向恶化**: 4y Sharpe -0.195 / Ret -10.14pp / DD -4.94pp / WR -2.42pp

### equity_sp500_momentum (SP500, capital_pct=0, 观察)

| window | mode | Sharpe | Ret | DD | WR | N |
|---|---|---|---|---|---|---|
| 4y | t+1 | -0.181 | -5.10% | -22.96% | 37.5% | 365 |
| 4y | **t+0** | **-0.027** | +3.13% | -22.51% | 38.1% | 381 |
| 8y | t+1 | -0.122 | -3.44% | -30.74% | 39.8% | 621 |
| 8y | **t+0** | **-0.091** | -0.46% | -27.53% | 39.1% | 627 |

**Δ 同向改善**: 4y Sharpe +0.153 / Ret +8.24pp / DD +0.45pp；8y Sharpe +0.031 / Ret +2.98pp

## 反向不对称的解释

| universe | 性质 | T+0 影响 |
|---|---|---|
| **NASDAQ100** | MAG7 集中市 + 极端趋势股 (NVDA/META) | RSI 65-80 区间常态; T+0 早一天 evaluate → trail_stop / take_profit / regime_exit 更早 fire → **过早砍掉强势股** → -0.195 Sharpe |
| **SP500** | 503 ticker 广覆盖 + 价值/成长混合 | 趋势均衡; T+0 早一天 → 弱势股早出场, 强势股 trail 没那么贴 → 同 HK 微改善 |
| **HK HSCHK100** | H 股 + 大金融大消费, 中等趋势性 | T+0 中等改善 (+0.06 Sharpe) |
| **A 股 HS300** | T+1 settlement 强制, 不适用 | N/A (真实约束) |

**核心原理**: T+0 = 入场后第一天就可以评估出场。对**强趋势 universe** 这意味着 trail stop 离 entry 太近时 (尤其 atr_stop_mult=2.5 起步)，第一天的盘内波动有概率触发 stop，把本来能跑出 trail 的强势股提前砍掉。对**均衡 universe** 这意味着弱势股早出场释放 capital。

## 决策

1. **NASDAQ100 不切 T+0** — 已 deprecated 不上实盘，但 yaml 显式留 t+0 (markets/us_share.yaml settlement_mode=t+0) 是物理正确，研究者跑 sweep 自负后果
2. **SP500 仍负 Sharpe** — T+0 改善后 4y -0.027 / 8y -0.091 仍 < 0, 不解救 [[sp500_negative_2026-05]] 结论；US 不上实盘维持
3. **HK 是唯一 T+0 净受益的 enabled 策略** — 已落 yaml (PR #31)
4. **可保留的 follow-up**: NASDAQ100 在 T+0 下 atr_stop_mult 应放宽 (3.0+) 测试 — 但已 deprecated 不投工程

## 与五层 efficient set 的关系

- **不撬 16/17 条证伪墙** — 本 PR 是 settlement 校准, 不改 alpha
- **strengthens [[sp500_negative_2026-05]]**: T+0 修正后 SP500 仍 FAIL → 不是 T+1 backtester bug 误判, 是策略本身在 SP500 universe 不成立
- **strengthens [[three_universe_2026-05]]**: NDX MAG7 集中度问题在 T+0 下更明显 (反向恶化) — 主动 momentum 在集中市等权无效的结论加强

## 不要做

- ❌ 不要用 T+0 重启 NASDAQ100 / SP500 sweep — baseline 仍负, sweep 任何参数 +0.05 都不到 PASS
- ❌ 不要因 NASDAQ100 反向就回退 markets/us_share.yaml settlement_mode=t+1 — settlement 是市场物理属性, 不能因策略表现差就改物理
- ❌ 不要把"T+0 改善"推广到 zhuang / A_mom / A_mr — A 股是真实 T+1, 与本 PR 无关

## 关联

- [[hk_t0_recalibration_2026-06]] — HK 同款 +0.06 Sharpe (PR #31)
- [[sp500_negative_2026-05]] — SP500 base FAIL 不变
- [[three_universe_2026-05]] — NASDAQ100 MAG7 集中度问题加强
- `data/backtest/_us_settlement_recal/` — 8 组 backtest 产物
- `scripts/backtest/run_us_t0_recalibration.py`

**Why:** 验证 T+0 修法是否解救 US 历史负 Sharpe; 答案是部分解救 (SP500) 不解救 (NASDAQ100), 整体仍 FAIL; 更深价值是揭示"集中度高+趋势强的 universe 早出场反伤 alpha", 未来评估 T+0 改动效果有了 framework.
**How to apply:** 未来对新 universe 跑 T+0 vs T+1 对比时, 先判 universe 集中度 + 趋势强度: 集中 + 高 RSI → 预期 T+0 反向; 均衡 → 预期改善。SP500 / NASDAQ100 不再投策略层工程。
