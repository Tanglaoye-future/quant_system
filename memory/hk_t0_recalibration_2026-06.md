---
name: hk-t0-recalibration-2026-06
description: 2026-06-14 — equity_factor Backtester settlement_mode 市场独立化, HK 从错用的 T+1 切换到正确的 T+0 后双窗口 Sharpe +0.059 / +0.065；零 alpha 改动纯语义修正；HK sleeve efficient set 改写
metadata:
  type: project
---

# HK T+0 recalibration（2026-06-14）

## 一句话

equity_factor `Backtester` 历史把 A 股 T+1 锁仓语义全市场套用，HK / US 被无谓延迟一天 → 修成 market-aware settlement_mode 后 HK 4y Sharpe +0.059 / 8y +0.065 双窗口同向 PASS，无 alpha 修改。[[a1prime_southbound_gate_falsified_2026-06]] "HK sleeve 饱和" 结论需要在新 baseline 下重审。

## 触发

用户 2026-06-14 提示 "港股 T+0 可做多 + 美股 T+0 + A 股 T+1 买卖" → 审 backtester 发现 `engine/backtest.py:266` 硬编码 "A 股 T+1: 当日买的不能当日卖" 对 HK / US 也生效，错配。

## 改动（最小化语义校准）

- `MarketContext` 加 `settlement_mode: str = "t+1"` 字段 + yaml 显式 a_share=t+1 / hk_share=t+0 / us_share=t+0
- `Backtester` 加 `settlement_mode` 构造参数（默认 t+1 兼容旧调用）+ Step 3 evaluate 仅 t+1 时跳过入场当日仓
- `scripts/backtest/backtest.py` 入口读 `market_ctx.settlement_mode` 注入
- `tests/equity_factor/test_settlement_mode.py` 15 case (契约 + Step 3 行为差异)
- 不动 alpha / yaml 权重 / RSI 带 / factor weights / hedge ratio

## 双窗口结果（HK equity_hk_momentum）

| window | mode | Sharpe | Sortino | Ann | Ret | DD | WR | N | avgHold |
|---|---|---|---|---|---|---|---|---|---|
| 4y | t+1 baseline | +1.090 | +1.055 | +14.37% | +76.02% | -13.66% | 55.6% | 117 | 32.4 |
| 4y | **t+0 new** | **+1.149** | +1.109 | +15.15% | **+81.09%** | -13.53% | 55.4% | 121 | 31.3 |
| 8y | t+1 baseline | +0.579 | +0.515 | +7.45% | +79.36% | -15.10% | 45.2% | 188 | 29.9 |
| 8y | **t+0 new** | **+0.644** | +0.577 | +8.13% | **+88.72%** | -14.71% | 45.3% | 190 | 29.1 |

### Δ (T+0 − T+1)

| window | ΔSharpe | ΔSortino | ΔRet | ΔDD | ΔWR | ΔN |
|---|---|---|---|---|---|---|
| 4y | **+0.059** | +0.055 | **+5.07pp** | -0.13pp | -0.18pp | +4 |
| 8y | **+0.065** | +0.062 | **+9.36pp** | -0.39pp | +0.05pp | +2 |

Backstop #2 双窗口同向 PASS（4y / 8y 都正 + Ret 都 +5pp+ + DD 不恶化）。

## 为什么 +0.06 Sharpe 不是噪音

1. **机理可解释**：T+1 多套的一天延迟把 stop_loss / take_profit / regime_exit 出场决策推后 1 bar，HK 单日 ATR 大（趋势市场），延迟 1 bar 对持仓 PnL 显著
2. **N trades 几乎不变**：4y +4 笔 / 8y +2 笔 — 不是 sampling 增多，而是同样的入场被更早出场
3. **DD 改善**：-0.13pp / -0.39pp，方向自洽（更快出场 → 回撤变浅）
4. **WR 几乎不变**：胜率本身是入场质量函数，settlement 改动不影响，对照符合预期

## 与历次发现的关系

| 旧结论 | 修正后状态 |
|---|---|
| [[hk_optimization_2026-05]] v14 Sharpe 0.66（T+1 假设） | T+0 下 8y Sharpe 0.644 ~ 持平；Ret +9.36pp 显著改善 |
| [[a1prime_southbound_gate_falsified_2026-06]] "HK sleeve 饱和" | T+1 baseline 下饱和；T+0 新基线下需重审是否仍饱和 |
| [[v5_t1_recalibration_2026-06]] HK_mom 4y T+1 Sharpe 1.660 | 那个是 v5 grid 单资产，本回测是 strategy-level；不直接可比但同向 |

**不撬五层 efficient set 升级**——这是 backtester 执行层语义校准，不是新 alpha 路径，第 17 条证伪墙不动。

## 仍然不要做（沿用旧规则）

- ❌ 不要因为 +0.06 Sharpe 改 HK strategy yaml（widen / RSI 带 / 因子权重）
- ❌ 不要重启 A1' 南向 gate sweep — gate 本身机制 base-rate spurious 不变（4y/8y 两个 baseline 都已 falsify）
- ❌ 不要把 zhuang 切回 T+0 — A 股 T+1 是真实约束，commit 7f34bf8 切到 T+1 是 correctness fix
- ❌ 不要在 backtester 引入"日内信号 / 盘前入场" — 入场仍是 D+1 open，settlement 只放开"入场当日 close 评估"

## Out-of-scope（follow-up）

- v5 组合层 grid 是否在 HK T+0 重新校准 → PM 决策（[[v5_t1_recalibration_2026-06]] 同款模板）
- US equity_factor 双窗口 T+0 recalibration — 当前 [[sp500_negative_2026-05]] base Sharpe -0.18，T+0 是否解救？预计差异比 HK 更小（US 趋势 ATR 比 HK 平），但应跑一次确认
- HK 实盘 IBKR 交易侧 T+0 settlement 已天然支持，本 PR 不动 daily 流程
- HK / US lot size 真实化（HK 多 lot 100/500/1000；US 1 股）— A 股 100 股一手仍硬编码

## 5 条 Backstop 检查

- **#1 17 条证伪墙**：本 PR 是执行层校准非新 alpha，不撬墙 ✓
- **#2 双窗口同向 PASS**：4y / 8y Sharpe / Ret 全同向正 ✓
- **#3 实盘 < 30 笔不撬 frontier**：本 PR 不改 yaml 不撬 frontier，HK 实盘当前 0 仓（HK_mom 部署在 yaml 但实盘账户未开通），无回撤 ✓
- **#4 PM 决策权**：本 PR 仅修 backtester 语义 + 跑回测对比；不自动改 yaml 不自动改组合权重 ✓
- **#5 采集 vs alpha 分离**：N/A（不涉及 self-learning） ✓

## 关联

- `docs/specs/market_settlement_t0_t1.md` — 本 PR spec
- `tests/equity_factor/test_settlement_mode.py` — 15 case
- `data/backtest/_hk_settlement_recal/` — 4 组 backtest 产物 + summary
- [[hk_optimization_2026-05]] — HK v1→v14 路线图（T+1 baseline）
- [[a1prime_southbound_gate_falsified_2026-06]] — HK sleeve 饱和结论（待 T+0 baseline 下重审）
- [[v5_t1_recalibration_2026-06]] — zhuang T+1 切换前例（settlement 校准姐妹任务）
- [[feedback_harness_first_pr_split]] — harness-first spec 落地

**Why:** 修正历史 backtester market-agnostic 假设的 bug；HK alpha 估计被低估 0.06 Sharpe / 9pp Ret（8y），同语义错误也存在于 US。**How to apply:** 未来对 HK / US 的历史"饱和"结论（A1' / NASDAQ100 / SP500）做"重审性"假设：旧结论可能基于错误 T+1 baseline，重跑前先确认 settlement_mode；任何引用 [[hk_optimization_2026-05]] 数字的策略对比需注意是 T+1 还是 T+0 baseline。
