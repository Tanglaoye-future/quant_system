---
name: a-mr-rebuild-v6-grid-2026-05
description: 2026-05-30 — 重写 A_mr 为 swing_reversion(dip+bounce+ATR target) 4y Sharpe -0.27 仍 FAIL；v6 grid 验证砍 A_mr 反而 Sharpe 跌 0.10 + 2022 熊市从 +0.47 翻 -0.32，确认 A_mr hedge 价值 > solo 价值
metadata:
  type: project
---

## 起点

A_mr 旧 MeanReversion 4y Sharpe -0.30 / 8y -0.06 — 弱腿。用户选"重新造 strategy"路径。

## SwingReversion v1 设计与实现

`SwingReversionStrategy` 加在 `src/quant_system/strategies/equity_factor/engine/strategy.py`（与 MeanReversionStrategy 并存）。

设计要点：
- 入场：过去 N 日 RSI 触底 (≤ rsi_dip_max) + 今日 RSI ≥ rsi_bounce_min_today + bounce ≥ N pts + close > MA200 + 量 ≥ MA20
- 出场：close ≤ stop (1.5×ATR) / close ≥ target (3.0×ATR) / RSI ≥ 70 / close < MA200 / hold ≥ 20d
- 单测：tests/equity_factor/test_swing_reversion.py 7 个 全过
- backtest CLI：`--strategy swing_reversion --market a_share` 走 factory `kind=swing_reversion`

## 4y 实测（2022-2026, HS300）

| 指标 | 旧 MR | 新 SwingRev v1 |
|---|---|---|
| Sharpe | -0.30 | **-0.27** |
| 笔数 | 48 | 208 (×4.3) |
| 胜率 | 52% | **34%** ↓ |
| 盈亏比 | 1:1.56 | **1:2.43** ↑ |
| 总收益 | -1.25% | -7.69% |

入场放宽到位（笔数 ×4.3），盈亏比上去了（atr_target 28 笔均 +17.31%），但胜率掉得过狠。

## 出场归因（4y 4P 数据 — 高信息密度）

| 出场 | 笔数 | 平均 pnl% | 持有 |
|---|---|---|---|
| **break_ma200** | **95 (46%)** | **-2.86%** | 7d |
| time_stop | 50 (24%) | +2.35% | 22d |
| atr_stop | 31 (15%) | -6.82% | 9d |
| atr_target | 28 (14%) | **+17.31%** | 12d |
| rsi_overbought | 4 (2%) | +3.77% | 4d |

**核心缺陷**：dip+bounce 入场常贴 MA200，反弹一弱就跌穿 → 46% 出场是 break_ma200 noise churn。

整体每笔均值 +0.65%，扣摩擦 0.5% 净 +0.15%/笔 太薄。

## v6 PM 重配资 grid（验证"砍 A_mr"假设）

脚本 `scripts/portfolio/run_v6_no_amr_grid.py` — 5 资产 (HK 35% cap / A_mom 25% / zhuang 40% / QQQ 25% / GLD 25%)。

| 配置 | Sharpe | Ann | DD | 2022 熊市 |
|---|---|---|---|---|
| **v5 保持** (HK25/A_mom10/A_mr10/zhuang40/QQQ5/GLD10) | **2.22** | +8.6% | -2.7% | **+0.47** |
| v5 减 A_mr 留 10% 现金 | 2.17 | +8.4% | -2.8% | — |
| **v6 top1** (HK30/A_mom10/zhuang40/QQQ10/GLD10) | 2.12 | +10.1% | -3.97% | **-0.32** |

**反向洞察 — PM 直觉被数据否决**：

- A_mr solo Sharpe -0.27（4y）/ -0.06（8y）— 看着废
- 但 A_mr 与 zhuang ρ=-0.019、与 A_mom 隐含负 ρ → **diversification value > standalone value**
- 砍 A_mr 把权重移给 HK/QQQ → 组合 Sharpe **跌 0.10**，2022 熊市 Sharpe **跌 0.79**（+0.47 → -0.32）
- 教科书"hedge 腿即使 solo 亏钱也要保留"

## 决策

- **保留 v5 不动**（A_mr 10% 配比 hedge 价值真实）
- SwingReversion 代码 + 单测留仓内（不进 yaml），未来想做 A_mr v2 (MA200 buffer 修 break_ma200) 有起点
- 下一步转 HK AH 溢价 (task #2) 或 regime overlay (task #3) 找真边际

## v2 待做（如未来重启 A_mr 优化）

基于 break_ma200 46% 出场的诊断，v2 的明确改进方向：

1. **MA200 buffer**：入场要求 close > MA200 × 1.03（不止贴 MA），过滤瓶口反弹
2. **MA200 斜率**：要求 MA200 上升才入场，避免在下跌段 catch falling knife
3. **break_ma200 grace period**：要求连续 N 天 < MA200 才出，避免单日抖动

预期 break_ma200 从 46% 压到 15-20%，Sharpe -0.27 → +0.2~+0.4。

## 不要做

- 不要 PM 直觉砍 A_mr — v6 grid 已经否决；hedge 价值 hidden 在组合层
- 不要继续 SwingReversion v1 不加 buffer 直接调参 — break_ma200 是结构性问题，不是 RSI 阈值能解决
- 不要让 daily_equity.py 接 swing_reversion（实盘）— 4y FAIL，仅 backtest 探索阶段

## 产物

- 代码：`src/quant_system/strategies/equity_factor/engine/strategy.py` (SwingReversionStrategy)
- 单测：`tests/equity_factor/test_swing_reversion.py` (7 个，全过)
- backtest 入口：`scripts/backtest/backtest.py` (factory `kind=swing_reversion`)
- 4y 数据：`data/backtest/swing_reversion_a_share_2022-01-01_2026-05-25/`
- v6 grid 脚本：`scripts/portfolio/run_v6_no_amr_grid.py`
- v6 grid 数据：`data/backtest/portfolio_v6_no_amr.md` (+.json)

**Why:** PM 视角看 A_mr solo -0.27 像该砍的弱腿；但定量 grid 显示其负相关在组合层贡献 +0.10 Sharpe + 2022 熊市从亏损翻盈利，是 "diversification > standalone" 教科书案例。这个 reverse 必须记住，避免下次再重复这个失误。
**How to apply:** 下次再有"A_mr 是不是该砍"的讨论，先指本 memory；想优化 A_mr 时直接走 v2 (MA200 buffer) 不要再造新策略；任何"砍弱腿"决策必须先 grid search 验证组合层影响。
