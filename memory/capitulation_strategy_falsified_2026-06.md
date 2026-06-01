---
name: capitulation-strategy-falsified-2026-06
description: 用户描述 "散户绝望卖出时吃货, 散户狂热时派发" 反向情绪策略系统化路径 4 重证伪 — zhuang sleeve 信号互斥 + 跌停撬开数据死 + 放量反包样本压扁 + LHB 机构净买滞后不可作 trigger; 替代方案 = dashboard 辅人工; 第 16 条
metadata:
  type: project
---

## 一句话结论

用户人工 T 14% 日收益的核心 trigger (跌停板撬开 + 盘中分时大单簇 + 散户散单抛压) 是**盘中 execution alpha**, 不能系统化。4 重数据 + 信号 + 样本检查全 FAIL: (1) 当前 zhuang sleeve 已是横盘吃货, capitulation 信号方向**互斥** (winner 入场 RSI 63 / 距 20 日高 -1.6%, 不是 oversold); (2) akshare 跌停撬开/炸板/涨停股池历史 4y 封死 (近 30 日限制); (3) 放量反包变体 264 panic events 仅 9 反包 (3.4%), 反包+LHB 机构净买仅 1 个; (4) LHB 机构净买 T+1 才公开 = 滞后, 不可作 entry trigger. 结论: 不做新 sleeve, 改做 dashboard 辅人工. 第 16 条证伪.

## 用户描述的策略

> "散户绝望下跌卖出时吃货买入, 拉涨时散户冲入完成派发, 反过来收割"

本质 = 反向情绪 + capitulation + reversal. 与 zhuang sleeve 表面相同 (庄家行为模仿), 但 zhuang 当前实现是 "横盘吃货", 不是 "急跌吃货" → 信号互斥.

## 4 重证伪 (predictions + outcomes)

### #1 — Zhuang sleeve 信号互斥 (script: `scripts/research/zhuang_capitulation_entry_precheck.py`)

**预设**: 加 capitulation entry trigger 扩展 zhuang sleeve.
**测试**: L7B-score70-pos40 (= L1-E baseline) 的 57 trades, winner (n=30) vs loser (n=27) 入场前 20 日特征.

| 特征 | winner mean | loser mean | Δ | 解读 |
|---|---|---|---|---|
| max 单日跌幅 | -4.9% | -4.4% | -0.4pp | 几乎相等 |
| panic 阴线数 | 0.33 | 0.48 | **-0.15** ❌ | loser 入场前 panic 更多 (反向) |
| RSI 入场 | **63.6** | 61.1 | +2.5 | winner 入场时 **偏强势** 不是 oversold |
| 距 20 日高 | -1.6% | -2.9% | +1.3pp | winner **距高更近** (横盘高位) |
| 量比异常日 | 0.00 | 0.04 | -0.04 | winner 入场前完全无量异常 |

**结论**: zhuang winner 入场是 "横盘高位偏强势" — 与 capitulation (急跌/oversold/放量) **明确反向**. zhuang sleeve 已 efficient 抓"横盘吃货"逻辑, 不能扩 capitulation.

### #2 — akshare 跌停撬开 4y 历史封死

**测试**:
- `ak.stock_dt_pool_em` (跌停股池): ValueError "只能获取最近 30 个交易日"
- `ak.stock_zt_pool_zbgc_em` (炸板股池): 同 30 日限制
- `ak.stock_zt_pool_em` (涨停股池): 历史日期返回 0 行 (2024-01-08/10/12/02-02 多日测试)

**对比 A1 北向**: 2024-08 同样永久封死 ([[a1_northbound_dead_southbound_alive_2026-06]]). akshare 实时类数据**普遍只保最近 30 日**, 资金流 + 涨跌停板 + 龙虎榜实时指标全适用. 历史 backtest **不可能**.

### #3 — 放量反包变体 sample size 压扁 (script: `scripts/research/capitulation_variant_a_precheck.py`)

**预设**: 改用 daily OHLCV 可推的 "放量大阴 (-7% + 量比>1.5) + T+1 反包 (close > T high) + LHB 机构净买" 触发.

**测试**: HS300 2024 全年扫描:
| 子集 | n | 5d hold mean pnl | 10d win% |
|---|---|---|---|
| panic events 全集 | 264 | -2.17% | 43.9% |
| 反包 | **9** (3.4%) | +0.58% (+2.75pp) | 55.6% |
| **反包 + 机构净买 (T+1~T+5)** | **1** | — | — |

**反包率 3.4%** 远低于 mean reversion 通常 1/3 估计 — A 股 -7% 后下跌惯性强, 没有 V 反.

**4y 估算外推**: ~1000 events, ~36 反包, ~5-12 反包+jg. 即使全 backtest 也 **sample 不足**, 无统计意义.

完美匹配 [[session_2026_06_01_handoff]] paradox 4 风险之 **sample size 压扁** 类.

### #4 — LHB 机构净买滞后 不可作 entry trigger

**关键时序问题**:
- 龙虎榜数据 T 日盘后才公开 (晚 6 点左右)
- 机构净买 LHB 上榜 → 真实交易已发生在 T 日, 公布在 T+1 早 9 点
- 作 entry trigger 只能 T+1 开盘买, 至此机构动作已 1 天历史
- LHB 上榜的标准 = 涨幅/跌幅极值 → 已是 "结果", 不是 "leading 信号"

**结论**: LHB 机构净买仅可作 **confirmation 信号** (验证已建仓正确), 不能作 **entry trigger** (滞后).

## execution alpha vs strategy alpha 矫正

用户 14% 日收益的来源 (推测):
1. **盘中分时图判断** — 大单簇 / 异动 / 分时背离 (需 L2 tick 数据, akshare 无)
2. **极小仓位反复 sweep** — 同股 T+0 通过两笔 (融券 / 提前底仓买回) 实现, 算法很难复制因为信号即时性 + 心理判断
3. **个股 deep familiarity** — 1-2 只熟悉的 ticker, 人脑记忆其分时 pattern 库

系统化做不到因为:
1. **数据**: akshare/baostock 仅 daily 不含分时 tick; L2 数据需 wind/同花顺付费 3-10万/年
2. **T+1 限制**: 系统不能同股 T+0; 人工通过两笔技巧绕过
3. **资金量稀释**: 14% × 你当前小仓位规模 ≠ 14% × 10倍仓位 (信号容量上限低)
4. **Sample 死亡**: 即使有 L2 数据接入, 4y 训练样本仍可能 < 100, 过拟合不可避免

## 替代方案 — dashboard 辅人工

不做 strategy 不进 v5 不动 yaml. 做扫描工具帮你人工 T:

```
scripts/reporting/daily_panic_dashboard.py
  每日扫:
    - HS300 + CSI1000 当日跌幅 ≤ -5% / -7% (panic 候选)
    - 量比 > 1.5 / > 2.0 (放量阴线)
    - 距 20 日高回撤排序
    - 最近 5 日 LHB 机构净买 top 20
    - 反包候选 (前日 -5% + 今日开盘高于昨收 1%)
    - 同 zhuang 当前候选名单重叠标记
  输出: HTML 报告 (沿用现有 report/ 体系)
```

特点:
- **不进 backtest** (避免第 17 条证伪)
- **不影响 v5 / yaml** (不进生产)
- **执行决策仍是用户人工** (execution alpha 保留在用户脑里)
- 工程 1 session, 数据全部 akshare 现成

## paradox 教训累积

本次 + L7A/L7B/L8 + L9-B ROIC + A1' + A2 = **6 次 paradox 模式** (已升级):
- 5 类: 信号互斥 / base rate spurious / sample 压扁 / 数据死亡 / execution-vs-strategy 错配 (本次新增)
- 第 5 类: **某些人工 alpha 是 execution alpha (盘中 / tick 级), 不是 strategy alpha (daily / 因子级), 不应尝试系统化**

## Why
保留是为了**未来不再做** "反向情绪 / 散户收割 / 涨跌停板战法 / 庄股扩入场" 类系统化提议. zhuang sleeve 已抓住"横盘吃货", 其他 capitulation 变体在 akshare + daily 数据下不可能.

## How to apply
- 收到 "做反向情绪 / 题材轮动 / 涨跌停战法 / 庄股扩入场" 类提议:
  1. 跑 [[zhuang_capitulation_entry_precheck]] 模板验 zhuang sleeve 信号方向
  2. 跑 [[capitulation_variant_a_precheck]] 模板验 sample size
  3. 若 user 强坚持 → dashboard 辅人工不进生产
- L2 tick 级数据接入是**唯一**可能复活路径 (但 3-10万/年成本, ROI 需独立评估)
- 不要再做"龙虎榜机构净买作 entry trigger" — T+1 滞后不可用

## 链接
- 上游: [[session_2026_06_01_handoff]] (paradox 4 模式)
- 同模式: [[a2_csi1000_l9b_paradox_falsified_2026-06]] (信号重复)
- 同模式: [[a1_northbound_dead_southbound_alive_2026-06]] (akshare 数据死亡)
- 同模式: [[zhuang_l8_fundamentals_falsified_2026-05]] (信号互斥)
- 同模式: [[a_mr_v2_falsified_2026-05]] (mean reversion sleeve 4y FAIL)
- 关联策略: [[zhuang_optimization_2026-05]] [[a_mr_rebuild_v6_grid_2026-05]]
