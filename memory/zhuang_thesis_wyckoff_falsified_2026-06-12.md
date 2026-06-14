---
name: zhuang-thesis-wyckoff-falsified-2026-06-12
description: 2026-06-12 — Wyckoff 价跌量缩入场 thesis 双窗口证伪；entry 跌势入场全崩 (ΔSharpe -0.78~-1.13)，exit 放量派发 8y 微输 baseline
metadata:
  type: project
---

# zhuang Wyckoff thesis 证伪 (2026-06-12)

## 用户 thesis

"价格下跌 + 成交量不断减小 → 入场吃货；价格上涨放量 → 派发出场"

## 实验设计

13 变体 3y+8y 双窗口 sweep (`scripts/backtest/run_thesis_sweep_zhuang.py`)：

- **E1-E7**：反转入场逻辑 —— price 在 20d 区间下半段（价跌）+ 量缩条件
- **X1-X3**：出场加放量派发 —— 量相对自身均值放大 + 浮盈门槛
- **C1-C2**：combo entry+exit

## 3y 结果 (2022-2024, 2496 只)

| 变体 | 3y Sharpe | N | WR |
|------|-----------|----|------|
| baseline | **-0.39** | 65 | 36.9% |
| E1 下半50% | -1.22 | 61 | 31.1% |
| E5 价跌量缩 | -1.18 | 60 | 31.7% |
| E6 完整thesis | -1.17 | 46 | 28.3% |
| X1-X3 放量派发 | -0.355~-0.357 | 65 | 38.5% |

## 8y 结果 (2018-2026, 2039 只)

| 变体 | 8y Sharpe | TotRet | ΔSharpe |
|------|-----------|--------|---------|
| **baseline** | **0.2182** | +45.58% | — |
| X3 放量2x+浮盈≥2% | 0.2173 | +45.44% | -0.0009 |
| X2 放量1.5x | 0.2164 | +45.32% | -0.0018 |
| X1 放量2x | 0.2152 | +45.09% | -0.0030 |

## 结论

1. **入场侧全面证伪** —— Wyckoff "价跌入场"逻辑让 Sharpe 从 -0.39 暴跌到 -1.17~-1.53。庄股 alpha 落在突破确认端（gap 5%+ bin），不在抄底端
2. **出场侧噪音级** —— 放量派发信号从未独立触发，8y ΔSharpe -0.0009~-0.0030，无落地价值
3. **当前 entry_price_position_min=0.4（上半段）+ 六层出场 = local optimum**

## 不要做

- 不要再反转入场逻辑为"跌时入场"
- 不要再在派发出场上加放量条件（当前 turnover>6 + close<high 已够）
- thesis 逻辑自洽但数据矛盾 → 庄股 alpha 结构与 Wyckoff 积累/派发周期不匹配

## 关联

- [[zhuang_gap_score_precheck_falsified_2026-06]] — gap-up 5%+ bin 贡献全部正收益，入场 filter 破坏 alpha 结构
- [[zhuang_sweep_2026-06-12]] — extreme sizing 是唯一有效改进
- [[zhuang_l4_experiments_2026-05]] — L4 combo4 出场收紧（非放量派发方向）
- [[case_2026_06_08_600584_distribution]] — 实盘 distribution 信号 case
