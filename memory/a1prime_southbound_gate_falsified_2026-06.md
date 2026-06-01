---
name: a1prime-southbound-gate-falsified-2026-06
description: A1' HK 南向 gate 4y backtest 证伪 — Sharpe 1.080 → 1.022 (-0.058), 预检查 mean +37% 是 base rate spurious correlation, 没翻译成可交易 Sharpe; widen+gate 互斥; HK sleeve 也已饱和
metadata:
  type: project
---

## 一句话结论

预检查显示 10d>200亿阈值下 mean pnl_pct +37%, 但 4y HK backtest 实测 **Sharpe 1.080 → 1.022 (-0.058)** — 预检查的 base rate spurious correlation 没翻译成可交易 alpha, 现 yaml widen 与 gate 互斥进一步打架。HK sleeve 在 v5 当前架构也已饱和, 与 zhuang L1-E / HS300 L8D2 同构。第 14 条证伪路径。

## 实验设置

- **driver**: A1' 预检查 PROCEED ([[a1_northbound_dead_southbound_alive_2026-06]])
- **窗口**: 4y (2022-01-01 → 2026-05-25), HSCHK100 universe
- **baseline (yaml 当前)**: equity_hk_momentum + widen 已开 (`m3_southbound_widen_enabled: true, threshold: 2.0`)
- **gate 实现**: 入场前要求南向 N 日累计净流入 ≥ threshold, 否则拒入场
- **cases**: A1P-base (gate=off) / A1P-gate-10d200 (10d 累计 ≥ 200亿)

## 结果（4y 反向）

| tag | Sharpe | 年化 | 收益 | DD | win% | trades | Δ Sharpe |
|---|---|---|---|---|---|---|---|
| **A1P-base** | **1.080** | +14.0% | +73.9% | -13.6% | 54.4% | 114 | — |
| A1P-gate-10d200 | 1.022 | +12.8% | +65.8% | -14.0% | 53.7% | 95 (-17%) | **-0.058** |

## 预检查 vs Backtest paradox 诊断

| 指标 | 预检查 (binary filter on trades.csv) | 真 backtest |
|---|---|---|
| trades 数 | 保留 58.3% (193/331) | 95/114 = 83% (less filtered) |
| win rate | 61.1% (+4.9pp) | 53.7% (-0.7pp) |
| mean pnl_pct | +1.04pp (+37%) | -8.1% 总收益 |

**为何 paradox**:

1. **Base rate spurious correlation 应验** — 预检查计算 "winner 入场前 5/10/20d 累计 > 0 占比" 时, winner 入场日**先验上更可能落在牛市段**（市场情绪好 → 南向流入 + 个股 momentum 触发）, loser 反之。这种自相关被预检查捕获为"信号", 但不是**可交易**的 alpha — 实盘里你无法用 hindsight 选择"在 winner 的入场日入场"
2. **widen + gate 互斥打架** — 现有 yaml widen 设计是"南向强买日放宽 RSI 入场带"让更多 trade 进来; gate 设计是"南向累计低就拒入场"减少 trade。两者方向相反, 同时开等于自我对冲
3. **HK universe 小 + 信号本就强** — HSCHK100 只 100 只股, 4y 仅 114 trades (≈28/年), gate 拒 17% 后 sample 太小, 统计 alpha 被压扁
4. **Sample 跨段不平均** — 真 backtest 是逐日扫 universe + 信号触发后 ranking 入场, 与"事后看 trades 集合"完全不同流程

## 与历次"预检查正向 + backtest 反向"同构教训

| 路径 | 预检查指标 | backtest 结果 |
|---|---|---|
| L9-B ROIC | 4y 因子全面接入 + ROIC 数据 100% 覆盖 | -0.096 Sharpe |
| L7-A pos_max | 假设 cap binding 8% trades 增量 | 三 case 同分 (cap 不 binding) |
| L8 fundamentals | 假设 ROE>0 gate 提质量 | winner/loser ROE 占比反向 |
| **A1' southbound gate** | **mean pnl_pct +37%** | **Sharpe -0.058** |

**核心教训**: trades.csv 后验分析 ≠ 真 backtest, 因 base rate / selection bias / 信号互斥三重坑。
未来"预检查正向"必须先识别这 3 个风险才能值得 1-2 hr backtest 工程。

## 结构性结论

HK sleeve 在 v5 当前架构下 (widen + L9-A regime-aware partial + factor weights) 也已饱和。
**三层 efficient set 同构升级 → 四层**:

| sleeve / layer | efficient set | 证伪路径 |
|---|---|---|
| 组合层 v5 | HK25/A_mom10/A_mr10/zhuang40/QQQ5/GLD10 | 5 |
| HS300 因子层 | L8D2 + L9-A regime partial | 2 |
| zhuang sleeve | L1-E + L6-A equal | 3 |
| **HK sleeve** | **现 yaml (widen on, gate off)** | **1 (本)** |

## 工程保留决策

虽 4y 证伪, 工程已落, 不删除:
- `TimingRegimeContext.southbound_cum_lookback` 字段 (regime.py)
- `build_timing_regime_context` 加 `southbound_gate_lookback_days` 参数
- `TimingConfig.m3_southbound_gate_*` 3 字段 (默认 disabled)
- `entry_signal_from_enriched` gate 检查逻辑
- 8 个单测 (字段 / 拒入场 / 数据缺失兜底 / yaml loader)

未来若改 HK universe (HSI 全市场 / 港交所小盘) 或关 widen 单跑 gate, 可重启 sweep 无需重做工程。

## 不要做（避免下次重蹈）

- 不要再以"trades.csv 预检查正向"作为投 backtest 的充分条件 — base rate / spurious correlation 风险必须先排除
- 不要把 gate threshold 再压低 (50 亿 / 100 亿) — widen 已开下 gate 是噪音
- 不要"关 widen + 开 gate" — 已是变体探索, 但 widen 历史 PASS (落 yaml), 拆掉它去验证 gate 是反向工程
- 不要在 HK sleeve 因子层再扩 — 与 HS300 同构饱和

## 落地决策

- yaml 不动 (gate disabled)
- handoff 13 → 14 条证伪路径
- HK sleeve 未来 alpha 通道 = 真做空 leverage (handoff #5, PM 决策) 或新 universe (HSI 全市场)
- 不再做 HK widen / gate / factor 参数 sweep

**Why:** A1' 是 handoff [[session_2026_06_01_handoff]] 排序最高的 ROI 路径, 实测 4y 反向证伪明确 — HK sleeve 在 v5 当前架构已饱和, 与组合 + HS300 + zhuang 三层同构。
**How to apply:** 未来 HK 改进提案如果还在动 entry filter / RSI 带 / 量能门槛 / 资金流 overlay, 直接 reject — 引用 [[hk_optimization_2026-05]] (v1-v10 完整) + 本 memory。alpha 通道转向新 universe 或真做空 leverage。
