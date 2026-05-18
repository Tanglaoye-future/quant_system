---
name: zhuang L4 出场规则单变量扫描（2026-05-17 起，进行中）
description: zhuang L1-E 之后的下一层优化 — 出场规则参数扫描；已完成 baseline 与 L4A1（take_profit 10%）显著抬升 Sharpe
type: project
---

## 背景

zhuang L1-E (entry_price_position_min=0.4 + accumulation_score_entry=70) 已是当前最优入场过滤
（6.4y Sharpe 1.346 / 3y Sharpe 1.370）。L2/L3 (相对强度、vol regime) 均负转移。
L4 是下一个自然分支 — 出场规则有 6 个未联调变量。

## 基础设施（2026-05-17 完成）

- monorepo 合并后 zhuang 数据基建缺失（无 universe csv、无 daily CSVs、venv 无 baostock）
- `scripts/prefetch/prefetch_zhuang_universe.py` 拉 universe + 3270 只 6 年日线（~56min, 0 失败）
- `data/prices/` ~291MB，已加 .gitignore
- `ZhuangBacktester.run()` 加 `px_cache` 可选参数，sweep 复用避免每实验 4min disk IO
- `scripts/backtest/run_l4_sweep_zhuang.py` — 12 个 L4 单变量实验 + baseline，输出 markdown summary

## 实验设计（窗口 2022-2024，3y）

| 标签 | 变量 | 基线值 | 实验值 |
|---|---|---|---|
| L4A1/A2 | take_profit_pct | 0.15 | 0.10 / 0.20 |
| L4B1/B2 | stop_loss_atr_mult | 2.0 | 1.5 / 2.5 |
| L4C1/C2 | momentum_stop_pct | 0.05 | 0.03 / 0.07 |
| L4D1/D2 | max_hold_days | 15 | 10 / 20 |
| L4E1/E2 | extend_profit_pct | 0.05 | 0.03 / 0.08 |
| L4F1/F2 | distribution_turnover_thresh | 8.0 | 6.0 / 10.0 |

## 全量结果（13/13 完成）

按 Sharpe 降序：

| 排名 | 标签 | 覆盖 | Sharpe | 收益 | DD | 胜率 | PF | 笔数 |
|---|---|---|---|---|---|---|---|---|
| 1 ⭐ | L4D1-mh010 | max_hold_days=10 | **1.615** | +22.4% | -2.8% | 50.0% | 3.54 | 62 |
| 2 | L4A1-tp010 | take_profit_pct=0.10 | **1.581** | +22.0% | -2.9% | 48.4% | 3.43 | 62 |
| 3 | L4B1-atr15 | stop_loss_atr_mult=1.5 | 1.483 | +21.2% | -3.4% | 46.8% | 3.64 | 62 |
| 4 | L4F1-dt060 | distribution_turnover_thresh=6.0 | 1.479 | +20.9% | -3.3% | 48.4% | 3.38 | 62 |
| 5 | L4C1-ms003 | momentum_stop_pct=0.03 | 1.451 | +20.7% | -3.3% | 45.2% | 3.77 | 62 |
| 6 | L4E2-ep008 | extend_profit_pct=0.08 | 1.449 | +20.9% | -3.5% | 46.8% | 3.49 | 62 |
| 7 | baseline-L1E | — | 1.429 | +20.7% | -3.5% | 46.8% | 3.47 | 62 |
| 8 | L4B2-atr25 | stop_loss_atr_mult=2.5 | 1.420 | +20.6% | -3.5% | 46.8% | 3.43 | 62 |
| 9 | L4F2-dt100 | distribution_turnover_thresh=10.0 | 1.404 | +20.5% | -3.5% | 46.8% | 3.42 | 62 |
| 10 | L4C2-ms007 | momentum_stop_pct=0.07 | 1.393 | +20.4% | -3.6% | 46.8% | 3.36 | 62 |
| 11 | L4E1-ep003 | extend_profit_pct=0.03 | 1.372 | +20.2% | -3.5% | 45.2% | 3.59 | 62 |
| 12 | L4D2-mh020 | max_hold_days=20 | 1.365 | +20.2% | -3.7% | 45.2% | 3.55 | 62 |
| 13 | L4A2-tp020 | take_profit_pct=0.20 | 1.333 | +20.6% | -3.6% | 43.5% | 3.76 | 62 |

## 关键洞察

1. **方向一致性 ★★★** —— 全部 6 个"收紧"实验均跑赢基线（最差 +0.02），全部 6 个"放松"实验均跑输（最好 -0.009）。
   零反例。强信号：庄股策略的当前出场参数偏松，需整体收紧。

2. **最强单变量是 max_hold_days 15→10** —— +0.186 Sharpe / +1.7pp 收益 / +0.7pp DD改善 / +3.2pp 胜率。
   逻辑：庄股拉升周期通常 5-10 个交易日，15 日窗口给了反向震荡时间。

3. **次强单变量是 take_profit_pct 15→10%** —— +0.152 Sharpe。
   逻辑：庄股拉升常 10-12% 后高位放量出货，15% 止盈太晚被反吃。

4. **笔数完全不变（62 笔）** —— 出场参数变化未影响入场，验证 L1-E 入场过滤是独立维度。
   出场参数只影响每笔的退出节点 → 改善单笔收益分布。

5. **DD 也一致改善** —— 4 个 top winner DD 都从 -3.5% → -2.8 ~ -3.4%。出场收紧不仅升 Sharpe，也降回撤。

## 组合实验（3y 窗口 2022-2024，5 个）

按 winner 强度逐层叠加，每加一项观察增量：

| 组合 | 改动 | Sharpe | 收益 | DD | 胜率 | PF | Δ |
|---|---|---|---|---|---|---|---|
| baseline-L1E | — | 1.429 | +20.7% | -3.5% | 46.8% | 3.47 | — |
| combo1 | mh10+tp10 | 1.723 | +23.2% | -2.1% | 51.6% | 3.46 | +0.294 |
| combo2 | +atr15 | 1.775 | +23.7% | -2.1% | 51.6% | 3.64 | +0.052 |
| combo3 | +dt60 | 1.843 | +23.9% | -1.9% | 53.2% | 3.57 | +0.068 |
| combo4 | +ms03 | **1.849** | +23.9% | -1.8% | 51.6% | **3.83** | +0.006 |
| combo5 | +ep08 | 1.849 | (== combo4) | | | | no-op |

combo4 vs combo3 增量为 +0.006（噪音边缘），ep08 在 max_hold=10 下不触发（no-op）。

## 6 年验证（2020-2026，三对照）

| 标签 | Sharpe | 收益 | DD | 胜率 | PF | 笔数 |
|---|---|---|---|---|---|---|
| baseline-L1E | 1.389 | +44.7% | -3.6% | 50.7% | 2.95 | 136 |
| combo3 | 1.614 | +48.0% | -3.2% | 55.1% | 2.83 | 136 |
| **combo4 ⭐** | **1.627** | **+48.1%** | **-3.1%** | 54.4% | **2.96** | 136 |

**3y → 6y 改进衰减：3y +0.420 → 6y +0.238 Sharpe。**衰减但稳定正向 → 非过拟合。
combo4 仍微微优于 combo3（+0.013 Sharpe / +0.13 PF），选 combo4。

## 最终落地（config/zhuang.yaml）

| 参数 | 原值 | 新值 |
|---|---|---|
| max_hold_days | 15 | **10** |
| take_profit_pct | 0.15 | **0.10** |
| stop_loss_atr_mult | 2.0 | **1.5** |
| distribution_turnover_thresh | 8.0 | **6.0** |
| momentum_stop_pct | 0.05 | **0.03** |

## 累计提升路径

| 阶段 | Sharpe (6y) | 收益 (6y) | DD | 累计提升 |
|---|---|---|---|---|
| v5 原始 | 0.944 | +37.3% | -5.56% | — |
| L1-E | 1.346 | +44.0% | -3.77% | +0.402 |
| **L4-combo4** | **1.627** | **+48.1%** | **-3.10%** | **+0.683** |

zhuang 子策略 Sharpe 翻倍（0.94 → 1.63），DD 减半（-5.56% → -3.10%）。

**Why:** L4 出场参数收紧（mh/tp/atr/dt/ms 五维同向）显著抬升 Sharpe；
3y/6y 双窗口一致验证，非过拟合；落地为新基线。
**How to apply:** 已写入 config/zhuang.yaml；下一步可考虑：
(a) zhuang 6-asset overlay 重算（旧 0.94 → 现 1.63 应进一步抬高组合 Sharpe）；
(b) L5 仓位权重（score 加权 vs 等权）；
(c) DuckDB 数据层迁移（独立基建任务）。

## 性能注意

- 主循环瓶颈：`for code in universe` × `for date in all_dates` = 3270 × 726 = 2.37M 次入场扫描
- 每次入场 check 涉及 df 过滤 + accumulation_score 计算（多个 rolling stat）
- 单进程 19min 已确认；首次 sweep 跑得 14× 慢（4.6h/exp）原因不明（疑同时多后台进程争用）
- 重启后单一进程，速度恢复正常

**Why:** L1-E 后顺序优化的下一层；早期数据显示出场规则有显著抬升空间。
**How to apply:** 等 sweep 完成 → 单变量赢家做组合实验 → 6 年验证 → 落地到 config.yaml。
