---
name: portfolio-p3-amr-options-baseline-2026-05
description: 2026-05-28 P3 补 A_mr + Options BCS 量化基线 — A_mr 弱(8y Sharpe ~0, hedge价值)；Options BS近似 Sharpe 1.2-1.4 高vol；附带捕获 A_mr stale-data 问题 + v5 重验证通过
metadata:
  type: project
---

## 背景

[[portfolio_p1_p2_weights_capacity_2026-05]] 落 v5 后，两个子策略仍是数据黑洞：A_mr 只从 equity 曲线推过 Sharpe，Options BCS 完全没回测过。P3 补基线。

## A_mr (mean-reversion) 基线

`mean_reversion` 走 backtest.py build_strategy kind，config 用 build_strategy 默认（无独立 yaml）。重跑双窗口：

| 窗口 | Sharpe | 年化 | DD | 胜率 | 笔数 | 总收益 |
|---|---|---|---|---|---|---|
| 4y (2022-2026) | **-0.296** | -0.30% | -13.2% | 52.1% | 48 | -1.25% |
| 8y (2018-2026, fresh) | **-0.061** | +1.28% | -11.6% | 57.0% | 93 | +10.8% |
| 2020-2026 (grid 窗口) | **+0.265** | +2.22% | -11.6% | — | — | +11.3% |

**结论**：A_mr 单独是**弱/负 alpha**（4y 负、8y ~0）。胜率 52-57% / 盈亏比 2.0 不差，但年化收益太低压不出 Sharpe。**它在组合里值钱纯粹靠 -0.16 负相关 hedge（与 A_mom）**，不是靠自身收益。admission FAIL。

### ⚠️ 捕获 stale-data 问题 + v5 重验证

跑 fresh 时发现：旧 A_mr 曲线（`_2018-01-01_2026-05-04`，5/15 跑，**pre-DuckDB 迁移**）8y Sharpe +0.062 / 112 笔，fresh（post-DuckDB）是 -0.061 / 93 笔。差异**全在 2018-19 段**（DuckDB 数据层差异）。

**P1/P1+ grid 当初用的是旧曲线** → 必须重验。结果：
- **grid 窗口 (2020-2026) 里 fresh A_mr Sharpe 0.265 ≈ 旧 0.250**（差异在组合窗口外，因 zhuang 限制窗口从 2020 起）
- 用 fresh A_mr 重跑 P1 grid：**v5 仍是 #1 最优**（HK25/A_mom10/A_mr10/zhuang40/QQQ5/GLD10 → Sharpe 2.231）
- 重跑 P1+ 稳健性：2022 熊市 v4 -0.621 → v5 +0.463（ΔSharpe +1.085），全窗口 v5 2.232 —— 与原结果几乎完全一致

→ **v5 完全验证通过，DuckDB 数据差异不影响组合结论**。已把 P1 脚本 DEFAULT_PATHS["A_mr"] 改指 fresh 曲线 (`_2026-05-25`)。

**教训**：跨脚本复用 equity 曲线产物时，注意产物的生成日期 / 数据层版本。DuckDB 迁移 (2026-05-18) 是分水岭，之前的回测产物可能与现数据层不一致。

## Options BCS (QQQ Bull Call Spread) 基线

**Options 子策略无回测引擎**（selector 用 live IBKR 报价），**无历史期权链** → 无法精确回测。搭了 **BS 近似回测器** `scripts/backtest/backtest_options_bcs.py`：

- 信号层忠实复刻 live（QQQ>MA200 & RSI14∈[50,78] & 3月动量>0；IVR<50 入场，HIGH 跳过）—— QQQ + ^VXN 历史 yfinance 可取
- BCS payoff 用 Black-Scholes 反推行权价（long δ0.45 / short δ0.27，DTE 50，r=0），VXN/100 当 IV
- 出场 profit_target 2× / stop 0.5× / 到期结算；sizing 单标的一仓 premium 10%/笔 + 2% haircut
- 无 scipy → 自实现 Φ (math.erf) + Φ⁻¹ (Acklam)

| 窗口 | 组合Sharpe | 年化 | vol | DD | 胜率 | PF | 笔数 |
|---|---|---|---|---|---|---|---|
| 8y | **1.363** | +30.9% | 22.7% | -22.6% | 56.3% | 2.46 | 71 |
| 4y | **1.121** | +24.9% | 22.2% | -22.5% | 54.3% | 2.18 | 35 |

**相关性**：QQQ **0.52** / 其余资产全 ≈0（HK -0.01/A_mom 0.01/A_mr -0.05/zhuang -0.02/GLD 0.10）。

**结论**：
- **高辛烷值 sleeve**：高 Sharpe (1.2-1.4) 但 vol/DD ~22%，本质是 QQQ 上涨趋势的杠杆化捕获
- 与 QQQ 0.52 相关但非纯 beta 冗余（信号门控 + 定义风险让它部分解耦）
- **稳健 takeaway 是 Sharpe ~1.2 + 胜率 55% + PF 2.2**；+969% 总收益（8y）**几乎肯定高估**（BS 无 vol skew → 高估杠杆，理想 mark）

### BS 模型局限（明确标注）
1. VXN 当 flat IV 喂两腿，忽略 vol skew（真实 OTM 短腿更便宜 → 真实 premium 略低 → 真实杠杆略低）
2. 无真实 bid/ask，用 2% round-trip haircut 近似
3. BS 连续行权价 vs 实际离散挂牌
4. r=0 / 无股息
5. 固定 50 DTE 入场 + 固定 sizing

### 7-asset grid 发现（directional only）

加 Options BCS（cap 15%）：最优 Sharpe 2.231 → **2.391（+0.16）**，且最优解**把 QQQ 完全换成 OPT**（QQQ 0% / OPT 10%）——BCS 是"更好的 QQQ"。

**但这建立在可能高估的 BS 近似上，是上界**。不据此改 v5 实盘权重。**Options 从 sidecar 提升到核心 5-10% slot（替换部分 QQQ）是值得跟的 roadmap 候选，但需先用真实成交验证**（实盘已在跑 IBKR，可累积真实 fill 数据后回测对照）。

## 落地 / 后续

- 未改 v5 实盘权重（A_mr 重验证后 v5 不变；Options 待真实数据验证）
- 产物：`data/backtest/options_bcs_qqq_*/`、`mean_reversion_a_share_*_2026-05-25/`
- **P4 候选**：A_mr 优化（弱但有 hedge 价值，提 Sharpe 到正能让组合再上一点）；Options 真实 fill 验证后考虑提升到核心 slot

**Why**: 用户要"用数据说话"补齐两个数据黑洞。A_mr 证明是 hedge 不是收益源；Options 证明是高辛烷值准-QQQ 替代，BS 近似下甚至想替换 QQQ。
**How to apply**: 下次涉及 A_mr 优化 / Options 实盘验证 / 组合是否加第 7 资产，先读本 memory。A_mr 别指望收益（hedge 定位）；Options 真实数据未验证前不进实盘权重。复用 `scripts/backtest/backtest_options_bcs.py`（BS 近似）+ `scripts/portfolio/run_p1_*.py`。
