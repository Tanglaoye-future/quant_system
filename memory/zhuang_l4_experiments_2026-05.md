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

## 已完成结果（2/13）

| 标签 | 覆盖 | Sharpe | 收益 | DD | 胜率 | PF | 笔数 |
|---|---|---|---|---|---|---|---|
| baseline-L1E | — | 1.429 | +20.7% | -3.5% | 46.8% | 3.47 | 62 |
| **L4A1-tp010** | take_profit=0.10 | **1.581** | +22.0% | -2.9% | 48.4% | 3.43 | 62 |

**早期洞察：take_profit 收紧到 10% (从 15%) → Sharpe +0.15 / DD -0.6pp / win +1.6pp，笔数不变。**
逻辑：庄股拉升常常是 10-12% 后高位放量出货，15% 止盈太晚反而被反向震荡侵蚀。

## 进行中（剩余 11 个）

L4A2 (tp=20%) / L4B1/B2 (atr stop) / L4C1/C2 (mom stop) / L4D1/D2 (max_hold) / L4E1/E2 (extend) / L4F1/F2 (dist thresh)。
当前每实验 19min（单进程，已诊断确认 px_cache 复用稳定），ETA ~3.5h 完成。

## 性能注意

- 主循环瓶颈：`for code in universe` × `for date in all_dates` = 3270 × 726 = 2.37M 次入场扫描
- 每次入场 check 涉及 df 过滤 + accumulation_score 计算（多个 rolling stat）
- 单进程 19min 已确认；首次 sweep 跑得 14× 慢（4.6h/exp）原因不明（疑同时多后台进程争用）
- 重启后单一进程，速度恢复正常

**Why:** L1-E 后顺序优化的下一层；早期数据显示出场规则有显著抬升空间。
**How to apply:** 等 sweep 完成 → 单变量赢家做组合实验 → 6 年验证 → 落地到 config.yaml。
