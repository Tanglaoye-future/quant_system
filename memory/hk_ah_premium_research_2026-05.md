---
name: hk-ah-premium-research-2026-05
description: 2026-05-30 — AH 溢价 overlay 微研究：5 只 8y H+A 双股，z60>=1 时 H 股未来 5d 收益 lift 仅 +0.32pp 均值且分布不稳（1 强 1 负 3 弱）→ 按 zhuang_hk_research 模板"先调研不实现"，避免投 1-2 天工程换 +0.05 弱 Sharpe
metadata:
  type: project
---

## 起点

[[hk_optimization_2026-05]] 路线图 B 级未做方向：AH 溢价指数 — H 股相对 A 股折价套利 +0.05? 中代价。

## 数据可达性侦察（关键工程问题先确认）

| 接口 | 数据 | 状态 |
|---|---|---|
| `akshare.stock_zh_ah_spot_em` (eastmoney) | 实时 AH 比价 + 溢价 字段 | ❌ push2.eastmoney.com ConnectionAborted（与 [[zhuang_hk_research_2026-05]] 同 blocker） |
| `akshare.stock_zh_ah_spot` (sina) | 实时 H 股价 (200 只 AH 双股) | ✅ 可达，但无溢价字段需自算 |
| `akshare.stock_zh_ah_name` (tencent) | AH 双股名单 | ❌ stock.gtimg.cn 不通 |
| `akshare.stock_zh_ah_daily(symbol)` (tencent) | 个股 H 股 daily 历史 | ✅ 可达，2017-05 → 2026-05 完整 8y |
| A 股 daily | 已有 loader 缓存 | ✅ |

→ 数据 OK：sina 拿名单 + tencent 拿个股历史 + A 股 loader 已有。**无 blocker**。

## HK universe ∩ AH 双股 = 21 只 (42%)

HK universe 50 只里 21 只是 AH 双股，主要央企（建行 / 工行 / 中行 / 中石油 / 中石化 / 平安 / 人寿 / 太平 / 招行 等）。

## 5 只代表样本 alpha 测试（4759 天 ~ 18y 数据）

信号定义：每日 AH 溢价 = (a_close × 0.92 - h_close) / h_close（0.92 是 HKD/RMB 简化常数）；z60 = (spread - mean60) / std60；high-premium = z60 ≥ 1（top 16% 折价日）。

目标变量：H 股未来 5d 收益。

| Pair | 全样本 5d fwd | z≥1 时 5d fwd | lift |
|---|---|---|---|
| 00939 建行 | +0.12% | +0.15% | +0.02pp |
| 01398 工行 | +0.11% | +0.29% | +0.18pp |
| 00857 中石油 | +0.69% | +2.23% | **+1.55pp** |
| 02318 平安 | +0.07% | +0.13% | +0.07pp |
| 02628 人寿 | +0.11% | -0.10% | **-0.22pp** |
| **均值** | +0.22% | +0.54% | **+0.32pp** |

## 结论：不实现

1. **alpha 不稳定**：5 只里 1 强（中石油）/ 1 负（人寿）/ 3 弱正。lift 均值 +0.32pp 但 std 大，不是稳定可重复信号
2. **ROI 太低**：1-2 天工程换路线图自评 +0.05 Sharpe + 不稳定信号 = 性价比劣
3. **真套利做不了**：本质 mean-reversion 套利需要双边持仓（多 H 空 A），HK 策略只能纯多
4. **HK 候选池 < 10 仓位上限** ([[hk_optimization_2026-05]]) → 入场宽度本来不是 binding constraint，加 21 只额外 entry score 边际有限

按 [[zhuang_hk_research_2026-05]] 模板"先调研不实现"。

## 如未来重启

前置条件：
- AH 溢价 alpha 在 21 只全样本均值 lift > +0.5pp 且 std < +0.3pp（稳定可重复）
- 或者：能加 A 股做空腿做真双边套利

实施路径（如前置满足）：
1. 拉 21 只 H+A 历史到 cache
2. 加 `AhPremiumOverlay` 计算器：每日给 HK universe 每只 AH 双股一个 z-score
3. HK strategy entry signal：当 z ≥ 1 时 RSI 下沿放宽 5pt（类比 [[hk_optimization_2026-05]] L2-B 南向资金的 +/-pt 调整）
4. 4y/8y 双验，Sharpe +0.05 才落 yaml

## 不要做

- 不要在 z 信号未证实稳定前实现 — 5 只样本已显示 1/5 是负贡献
- 不要把 FX 当固定常数 0.92 — 长窗口要用真实 HKD/RMB 日序列（akshare currency_history 可得）
- 不要假设 AH spread mean-reversion 普适 — 央企 H 股长期折价是结构性而非临时套利窗口

**Why:** 5 只样本测试给"投不投工程"决策提供量化依据；alpha 不稳定就先调研不实现，避免 1-2 天工程花在 +0.05 弱信号。
**How to apply:** 下次想做"看似 free lunch"的 overlay 信号，先做 5-10 只 4y 样本测试看 lift / std，再决定是否投工程；不要直接照路线图工程化。
