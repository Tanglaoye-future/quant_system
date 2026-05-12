---
name: A 股从 HK 移植实验记录（2026-05 E 阶段）
description: 把 HK 验证有效的 L1/L2/L3 套用到 A 股的实验结果。结论：L1/L2 不可移植，L3 可移植。
type: project
---

## 总结

| 改动 | A 股 Sharpe | 结果 |
|---|---|---|
| baseline | 0.58 | PASS |
| L1 (HK 配置) | 0.50 | ❌ DD 变深 |
| L1 (tight runner) | 0.30 | ❌ FAIL（DD 突破 25%）|
| L2 (drop PE, boost ROE+Mom) | 0.53 | ❌ |
| **L3 (HS300 hedge, MA60, r=0.3)** | 0.63 | ✅ +0.05 |
| L2-B (北向资金) | 0.63 | 零效应（候选已足）|
| **L2-add (fcf_yield 0.20)** | **0.65** | ✅ +0.02 |

A 股最终 final = baseline + L3 hedge + fcf_yield 因子。Sharpe 0.65。

## 关键洞察（不要重做）

### L1 不可移植：市场结构差异

HK 2018-2026 是「8 年大熊 + 间歇上行」的**趋势市场**：
- HSCHK100 累计 -22%，但中间有 2020 / 2021 / 2023 多次强反弹
- TP runner 抓得到这些反弹的延长部分

A 股 2018-2026 是**均值回归 + 短周期切换**市场：
- HS300 8 年 +18%，但波动性大
- TP（4×ATR）出场点已是局部最优，runner 持有反而捕到反转
- v2 实验：TIME_STOP 数从 6 → 33（runners 持到 max_hold），证明 trends 不延续

### L2 不可移植：数据现实差异

- HK 财务 akshare 覆盖窄，PE/PB 实际是 NaN（v10 才用 EM endpoint 修好），所以「HK 拿掉 value」其实是「拿掉 placeholder」
- HK 财务接通后实测 PE/PB 在 2018-2026 有反 alpha（银行价值陷阱）
- **A 股 PE/PB 是真数据 + 真 alpha**（A 股破净修复行情真实存在），不能照搬 HK 的去 value 套路

### L3 可移植但效果较弱

- HK 受益更大（+0.13）：HSCHK100 长期负回报，beta drag 严重
- A 股受益较小（+0.05）：HS300 长期 +17.6%，beta drag 不严重
- 但 A 股 alpha 是「市场之外的纯 stock-picking」（excess +69pp 已扣 hedge cost）
- 借券成本（3%）+ 滑点对 A 股 hedge 影响更大

### 配置定型

```yaml
markets:
  a_share:
    timing: {}                  # 用全局默认
    factors:
      weights:                  # 用全局默认
    hedge:
      ratio: 0.3
      ma_days: 60
      borrow_cost: 0.03
```

## 未尝试方向

- **A 股 northbound flow（陆股通北向）**：HK southbound 移植版，逻辑对称（北向是 HK 资金给 A 股定价）。可能比 HK 的 southbound 效果更强（北向更稳定）
- **A 股因子原计划**：strategy_optimization_plan.md 写了 fcf_yield + revenue_acceleration，需 loader 扩展
- **多 universe 联合（HK + A 股）**：低相关性资产组合，可能突破单 universe Sharpe 天花板

**Why:** 2026-05-12 一次 E 阶段移植实验，4 个市场配置尝试，得出 HK→A 不可全套移植的硬性结论。
**How to apply:** 启动 A 股策略改动 session 先读，避免重做 L1/L2 移植实验。专注 L3 已通且未来重点 northbound 因子。
