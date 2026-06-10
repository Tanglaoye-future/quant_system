---
name: zhuang-gap-score-precheck-falsified-2026-06
description: 2026-06-10 — zhuang gap-up filter + accumulation_score 交叉分析双双证伪；gap-up 砍掉全部正收益 bin，score 仅 16% 有值且 IQR 1.5 点无判别力
metadata:
  type: project
---

# zhuang gap-up filter + accumulation_score 双证伪（2026-06-10）

## 触发

v5 T+1 重校准后 [[v5-t1-recalibration-2026-06]] zhuang 单 Sharpe 0.30/0.20，自然问题：能否在入场侧加 filter 提纯？gap-up（T+1 开盘价相对前日收盘涨幅）和 accumulation_score 是两个最直接的候选。

结论：**两个都不能用**。

## gap-up filter 证伪

基于 `zhuang_a_share_2018-01-01_2026-05-25/trades.csv` 172 笔（29 笔缺 D_close）。

### 分箱数据

| bin | count | pct | win_rate | avg_pnl | med_pnl | sum_pnl |
|-----|-------|-----|----------|---------|---------|---------|
| <-0.5% | 29 | 16.9% | 37.9% | -0.42% | -3.96% | -12.2% |
| -0.5~0% | 10 | 5.8% | 40.0% | -1.10% | -2.81% | -11.0% |
| **0~0.5%** | **83** | **48.3%** | **12.0%** | -0.21% | -0.56% | **-17.4%** |
| 0.5~1% | 11 | 6.4% | 36.4% | -0.41% | -3.03% | -4.5% |
| 1~2% | 3 | 1.7% | 33.3% | -2.81% | -4.62% | -8.4% |
| 3~5% | 2 | 1.2% | 0.0% | -6.57% | -6.57% | -13.1% |
| **5%+** | **34** | **19.8%** | **41.2%** | **+5.20%** | -4.26% | **+176.7%** |

### 累积 cutoff 验证

```
gap<=0.005:  n=122 (71%)  wr=20.5%  avg=-0.33%  sum=-40.5%
gap<=inf:    n=172 (100%) wr=25.6%  avg=+0.64%  sum=+110.2%
```

gap>0.005 侧（被剔）：n=50 (29%) wr=38.0% avg=+3.01% sum=+150.7%

**直觉反转**：gap-up 不是"追高吃亏"，而是庄股 T+1 开盘强涨 = 确认信号。过滤 gap-up 会砍掉策略全部正收益。

### 结构洞察

所有 bin 的 **median pnl 都是负的** — 策略正期望完全靠少数大赢家（lottery-ticket 结构）。5%+ bin 的 avg +5.20% vs med -4.26% 是典型。

0~0.5% "平淡" gap 是真正噪音段：占 48% 交易量、胜率 12%、sum -17.4%。

## accumulation_score 证伪

### 缺失率 84%

172 笔中仅 28 笔有 accumulation_score 值（16%），其余全是 NaN。

### 范围极窄无判别力

```
10%: 70.2,  25%: 70.5,  50%: 70.8,  75%: 72.0,  90%: 72.4
```

IQR = 1.5 个点，90% 的样本落在 70.2-72.4。基本是同一条平行线，无法区分好交易和差交易。

### 交叉表样本量不足

- gap 0~0.5% (83笔): 仅 14 笔有 score，score 65-72 段 wr=36% avg=+1.22% vs 72-80 段 wr=67% avg=-0.56%，方向矛盾
- gap 5%+ (34笔): 仅 1 笔有 score，wr=0% avg=-7.84%

样本量太小，无法得出统计结论。

### Phase 也是废变量

全部 172 笔 phase = A，无 B/C/D 阶段。phase 列无过滤价值。

## 结论

1. **gap-up filter 加了会砍掉全部正收益** — 5%+ bin 是唯一正收益源，gap>0.005 侧 sum +150.7% 贡献全部 alpha
2. **accumulation_score 不提供判别力** — 缺失率 84% + 值域极窄 (IQR=1.5)，基本是同常数
3. **phase 不提供过滤** — 全 A 无变体
4. **zhuang sleeve 的 alpha 落在 lottery-ticket 尾部**（20% 交易贡献全部正收益），入场侧 filter 会破坏这个结构

## 不要做

- 不要加 gap-up filter（砍掉 5%+ bin）
- 不要在 accumulation_score 上投更多工程（废变量）
- 不要在 gap 0~0.5% "噪音段"单独加 filter（当前无法在不伤 5%+ 的前提下隔离它）

## 关联

- [[v5-t1-recalibration-2026-06]] — T+1 重校准，zhuang 单 Sharpe 0.30/0.20
- [[zhuang_l7a_falsified_2026-05]] — position_max_count 永不 binding（入场严格度才是瓶颈，但 gap 不是入场严格度的正确切法）
- [[zhuang_l7b_falsified_2026-05]] — score 阈值反向证伪（score 70→67→65 单调下）
- [[zhuang_l8_fundamentals_falsified_2026-05]] — fundamentals 与庄股 alpha 正交
- [[zhuang_overlay_combo4_2026-05]] — zhuang 单资产 Sharpe 2.35 的 T+0 假设（已 supersede）
