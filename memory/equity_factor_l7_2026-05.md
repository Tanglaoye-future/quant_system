---
name: equity_factor L7 实盘修复 2026-05
description: 用户实盘 equity_factor 套牢 → L7-A/B Pullback 入场重写失败 → L7-C3 出场优化成功，DD 改善 5pp
type: project
---

## 背景

2026-05 用户反馈 equity_factor 实盘亏钱，主诉"策略总在高位接盘、套牢"。
诊断：当前追高 timing (金叉+RSI 50-70+量能+20日新高) 4 个条件都是高位特征。

## 已尝试 (失败)

**L7-A Pullback 入场重写** (主动识别低位机会):
| 标签 | Sharpe | DD | 笔数 |
|---|---|---|---|
| A1 defaults (pos<=0.5+RSI 35-55+量缩+企稳) | -0.157 | -42.9% | 1289 |
| A2 pos<=0.7 | -0.019 | -44.2% | 1288 |
| A3 pos<=0.3 (越严越差) | **-0.977** | **-59.6%** | 1181 |

**L7-B Pullback + 强势 regime + 反弹确认**:
| 标签 | Sharpe | DD |
|---|---|---|
| B1B2 强势 regime + higher_low + close>MA20 | -0.684 | -35.0% |
| B1B2B3 + 相对强度 | -0.684 | -35.0% (无效) |

**结论：纯"价格位置低"在 HS300 大盘股缺乏预测力。熊市中"低位"变 catching falling knives。**

## 成功 (L7-C3)

完全弃用 pullback 思路，保留 baseline 追高入场，叠加 3 组出场优化（类似 zhuang L4 思路）：

**3 单变量 winner** (2022-2026 4y):
- E base: atr_stop 2.0→1.5 + atr_target 4.0→3.0 + max_hold 60→40 → Sharpe 0.226→0.449
- E4: + m5_regime_exit_enabled (HS300<MA60 强制平仓) → DD 改善的关键 -14.0%
- E5: + partial_exit (TP 触发卖 50% + 剩余宽松 trail) → 胜率从 36% 升到 50%

**组合**:
| 标签 | Sharpe | 收益 | DD | 胜率 | 笔数 |
|---|---|---|---|---|---|
| C1 (E+regime+hold30) | 0.512 | +33.5% | -13.9% | 38.4% | 346 |
| C2 (E+regime+partial) | 0.542 | +33.9% | -14.5% | 50.5% | 398 |
| **C3 (全部)** ⭐ | **0.619** | **+38.5%** | -14.3% | 50.3% | 396 |
| baseline (对照) | 0.226 | +17.7% | -19.5% | 41.4% | 261 |

C3 vs baseline (4y):
- Sharpe **+174%** (0.226→0.619)
- 收益 **+117%** (+17.7%→+38.5%)
- DD **改善 5.2pp** (-19.5%→-14.3%)
- 胜率 **+8.9pp** (41.4%→50.3%)

## 8 年验证 (2018-2026)

| 标签 | Sharpe | 收益 | DD | 胜率 | 笔数 |
|---|---|---|---|---|---|
| baseline (8y) | 0.527 | +76.6% | -18.5% | 42.6% | 474 |
| **C3 (8y)** | **0.402** | +56.0% | **-14.8%** | **51.0%** | 663 |

**8y 出现 trade-off：**
- 牛市 (2018-2021): baseline 占优 (动量追高吃趋势, C3 partial_exit 早锁利损失上行)
- 熊/震荡 (2022-2026): C3 占优 (regime_exit 在 2022 熊市保护 + partial_exit 锁利)
- 平均下来 8y Sharpe 略输，但 **DD 始终改善** (-18.5%→-14.8%) + 胜率显著抬升 (+8.4pp)

## 落地

`config/equity_factor.yaml` 在 `markets.a_share.timing` 新增 5 个 override:
```yaml
timing:
  atr_stop_mult: 1.5
  atr_target_mult: 3.0
  max_hold_days: 30
  m5_regime_exit_enabled: true
  partial_exit_enabled: true
  partial_exit_pct: 0.5
```

只覆盖 A 股；HK 配置保留原 atr_stop=2.5/atr_target=5.0 (港股 TP runner 已优化过)。

## 关键洞察

1. **HS300 大盘股的"低位识别"信号不工作** — 与 zhuang 小盘庄股（已验证 Sharpe 1.81）完全相反。
   原因：大盘股流动性强，"低位"早被套利；信号集中在动量/趋势，不在均值回归。

2. **DD 改善的关键不是入场，而是 regime exit + partial profit taking** —
   类似 zhuang L4-combo4 的思路（出场参数收紧）也适用于 HS300。

3. **trade-off 的本质**：partial_exit 在牛市卖飞，regime_exit 在反弹初期错过 → 牛市跑输；
   但在震荡/熊市，这两个机制保命。**用户当前痛点是后者**，C3 是对症下药。

4. **未来如果转牛市**：可考虑切回 baseline 或加 regime-aware 开关
   (e.g., 仅在 HS300 < MA200 时启用 partial_exit；MA200 上方时全量持仓)。

**Why:** 用户实盘套牢；L7-C3 在用户面对的 2022-2026 震荡熊市环境下 Sharpe +174%/DD 改善 5pp.
**How to apply:** config.yaml a_share.timing 已落地；daily_run 自动生效；监控 8y trade-off 在牛市的影响.
