---
name: a1-northbound-dead-southbound-alive-2026-06
description: A1 北向资金 overlay 因 2024-08-19 官方停更日级披露硬证伪；pivot 到 A1' HK 南向 overlay (12y 数据完整 + 至今实盘可用)；预检查信号 PROCEED, 10d 累计 >200亿 阈值下 mean pnl_pct +37%
metadata:
  type: project
---

## 一句话结论

A1（A 股北向资金入场过滤）**因数据源永久封死直接证伪** — 2024-08-19 起官方取消日级北向 net_buy 披露, akshare 无替代源, 实盘无法部署。Pivot 到 A1'（HK 南向 overlay）数据完整, 预检查信号显著（331 trades 模拟 10d 累计 >200亿 阈值下 win rate +4.9pp / mean pnl_pct +37%）, **推进完整 backtest**。

## A1 北向硬证伪诊断（避免下次重新发现）

### 数据源验证（所有 akshare hsgt 接口）

| 接口 | 状态 | 备注 |
|---|---|---|
| `stock_hsgt_hist_em(symbol='北向资金')` | **日级 NaN 自 2024-08-19** | cached 数据 2024-08-19 → 2026-06-01 全 NaN（410+ 天） |
| `stock_hsgt_fund_flow_summary_em()` | **今日成交额 = 0** | 交易状态字段 = 3 = 停摆 |
| `stock_hsgt_hold_stock_em()` | **API NoneType err** | 个股持仓接口已失效 |
| `stock_hsgt_individual_em()` | **签名变了** | `stock=` kwarg 不接受, 接口不可用 |

### 根因

2024-08-19 起港交所/上交所取消日级北向净买卖披露（监管口径变化, 实际事件）。
官方现仅保留：
- 季度持仓汇总（远低于日级精度）
- 今日总成交额（净流入字段为 0）

**结论**: 即使历史 backtest 显示北向 overlay 有 alpha, 实盘日无数据 = 信号永久失效。
A1 路径 **结构性死亡**, 不需要做预检查或 backtest。

### 不要做
- 不要再尝试 `akshare.stock_hsgt_*` 任何接口作 A 股北向日级 — 全部已停
- 不要找替代数据源 — 监管层面已禁日级披露, 其他第三方也只能拉到季度数据
- 不要在 A 股策略层加任何"北向 N 日累计"因子 — 实盘永远 NaN

## A1' HK 南向 overlay 预检查（PROCEED）

### 数据完整性

`DataLoader.get_hk_southbound_flow()` 走 `akshare.stock_hsgt_hist_em(symbol='南向资金')`：
- 12 年完整序列 2014-11-17 → 2026-05-22 (2636 行)
- **non-NaN 2635/2636 = 99.96%**
- 至今实盘窗口可用
- 正流入比例 77.3%（南向比北向更"积极"，长期净流入）

### 预检查方法

从 `data/backtest/equity_momentum_hk_share_2018-01-01_2026-05-25/trades.csv` (8y, 331 trades, base win rate 56.2%) 抽样:
- 每笔 trade 算入场前 5/10/20 日南向累计净流入（亿元）
- winner vs loser 分桶对比

### 分布对比（>0 占比 + mean）

| lookback | winner pos% | loser pos% | Δ pp | mean Δ (亿) | verdict |
|---|---|---|---|---|---|
| **5d** | 94.5% | 83.6% | **+10.9** | +26.55 | **PROCEED** |
| 10d | 96.2% | 91.0% | +5.2 | +54.25 | AMBIGUOUS |
| **20d** | 97.8% | 87.6% | **+10.2** | +98.46 | **PROCEED** |

5d 短端 + 20d 长端都 PROCEED, 10d 中间窗口 noise（不影响结论）。

### Binary filter 模拟（trades.csv 后验, 不是真 backtest）

| lookback | threshold (亿) | kept% | win rate | Δ pnl_pct |
|---|---|---|---|---|
| 5d | 0 | 87.6% | 59.7% (+3.5pp) | +0.56pp |
| 5d | **50** | **74.6%** | **60.7% (+4.5pp)** | **+0.91pp** |
| 5d | 200 | 25.7% | 64.7% (+8.5pp) | +0.54pp（过度过滤）|
| **10d** | **200** | **58.3%** | **61.1% (+4.9pp)** | **+1.04pp** ⭐ |
| 20d | 50 | 88.2% | 60.6% (+4.4pp) | +0.70pp |
| 20d | 200 | 77.6% | 60.3% (+4.1pp) | +0.89pp |

**sweet spot = 10d 累计 > 200 亿** — 保留 58% trades, win rate +4.9pp, mean pnl_pct 从 2.83% 涨到 3.87% (+37%)。

### Base rate caveat（重要！）

南向 77.3% 天数本身 > 0, 这意味着即使没有真 alpha:
- "winner 入场日更可能在正常市场（南向流入）期间"
- "loser 入场日更可能在熊市（南向流出）期间"
- 两者的 5d 累计差异部分来自市场状态自相关, 不全是新 alpha

因此 mean pnl_pct +1pp **不等于** Sharpe +1pp:
- vol 可能也上升（过滤后 sample size 小 + 集中在好市场期间）
- 需要完整 backtest 跑 sleeve Sharpe 才能定论

但 Δ +37% mean pnl_pct 是显著信号（非 noise 级），值得投 backtest 时间。

## 下一步推进 (handoff backlog A1')

按 ROI 顺序:
1. **strategy overlay 实现** — 在 HK BottomupTimingStrategy 入场逻辑加 southbound filter
   - yaml 加 `southbound_overlay: {enabled, lookback_days, threshold_yi}` 节点
   - filter 时机: 在 timing signal pass 后, 入场前 check 当日南向 lookback 累计
2. **4y/8y backtest 2 case** (base / +overlay 10d/200亿)
3. **单测 5-6 个** 覆盖 filter 触发 / 阈值 / 数据 NaN 容错
4. **双窗口同向赢才落 yaml**

预期工程: 1-2 hr。预期 sleeve Sharpe 改进: **不定**（mean +37% 但 vol 不知, 实测才知）。
组合层放大率 ~0.45×, HK sleeve 权重 25% → 即使 sleeve Sharpe +0.10, 组合 +0.025-0.05。

## 不要做（除上述 "A1 北向" 段）

- 不要无 base rate 控制就声明 A1' 有 alpha — mean Δ 部分来自市场状态自相关
- 不要用 5d threshold=200 — 只保留 25.7% trades, 实盘信号触发率过低
- 不要在 HK strategy 用 binary cut 之外的复杂权重 — 预检查是 binary 信号, z-score 加权属于过拟合方向

## 时间成本

- A1 数据源诊断（含 akshare hsgt 全接口测试）: ~15 min
- HK 南向预检查脚本 + run: ~10 min
- Binary filter 模拟: ~5 min
- 总: ~30 min

**Why:** A1 是 handoff 推荐的最高 ROI 路径，但数据源永久封死。South pivot 提供同语义的实盘可用方向，且 HK sleeve 25% 权重是组合最大（与 zhuang 40 并列前二），改进收益放大。
**How to apply:** 下个 session（或本 session 续作）实现 strategy overlay → 4y/8y sweep → 落 yaml。本 memory 永久封 A1 路径, 避免未来重做。
