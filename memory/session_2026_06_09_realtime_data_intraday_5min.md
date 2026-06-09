---
name: session-2026-06-09-realtime-data-intraday-5min
description: 用户提"实时数据 + 分钟监控"诉求 — 侦察 akshare/baostock 分钟数据后撞 Backstop #2 8y 同向不可达，改走 PR5 扩展 (5min poll + break_stop_loss + break_ma60 critical 告警)；3 PR 中 PR1 落地
metadata:
  type: project
---

# 2026-06-09 Session — 实时数据 + 分钟监控诉求 → PR5 扩展

## 触发上下文

用户："整个项目的数据能做到实时更新，现在每天收盘之后在拉数据在运行策略太慢了，我希望能自动在白天就时时跟新数据，然后策略时时运行监控买入和卖出点，把颗粒度细化到分钟线，我相信网上一定有开源的api接口的，不行你就去上交所的接口去拉取，不要说做不到"。

## 侦察硬数据（决定不撬墙的关键）

| 数据源 | 频率 | 历史长度 | Backstop #2 (8y) |
|---|---|---|---|
| akshare (eastmoney) | 1min | **5 天** | ❌ |
| akshare (eastmoney) | 5–60min | **30 天** | ❌ |
| **baostock** | **5min** | **6.4y (2020-01 起, ~75k rows/股)** | ❌ 差 1.6y |
| baostock | 60min | 6.4y, HS300 全集 ~34min serial | ❌ |
| akshare | daily | 23y (2001-) | ✅ 当前已用 |
| 付费 L2 tick | tick | wind/同花顺 | ✅ 但 3-10万/年 |

第 16 条证伪 [[capitulation_strategy_falsified_2026-06]] 已明文：execution alpha (盘中/tick 级) 不应系统化。本次重述：**5 因子 (PE/PB/ROE/RevGrowth/3M-Mom) 是季报+日 K 频率，分钟级 backtest 等价于日 K 重复采样，不产生新 alpha**。

## 用户决策路径

1. AskUserQuestion 一次：用户选 "A 股分钟线 backtest pipeline 建立"
2. 侦察后给硬数据 GO/NOGO 报告（baostock 6.4y < 8y 撞 Backstop #2，会立 18 条证伪 / 不能改 yaml）
3. AskUserQuestion 二次：用户改选 "实时监控+报警路径 (PR5 扩) - 最推荐"

正确的 backstop 守墙：用户初选撞墙，硬数据摆事实后 ta 自己改选。

## PR 拆分计划

| PR | 范围 | 状态 |
|---|---|---|
| **PR1** | poll 15→5min + break_stop_loss + break_ma60 (critical) | ✅ #21 (2026-06-09) |
| PR2 | daily watchlist 候选股盘中突破入场报警 | TODO |
| PR3 | zhuang 庄股盘中异动 + dashboard 1min 刷新 | TODO |

## PR1 关键设计决策

- **break_* 在 *_proximity 之前评估**：物理互斥（穿越后 dist 转负，proximity 天然不触发）
- **MA60 用 T-1 baseline**：盘中 T 日价不进 SMA 窗口；start = T-90 自然日 buffer 覆盖非交易日
- **dedup 沿用 once-per-day**：alerts_sent UNIQUE 不变 → 无 alembic migration；首次告警充分提醒，重推刷屏
- **akshare daily 调用频率**：4 持仓 × 240 min / 5 min ≈ 192 次/天，无缓存层（intraday 轻量）

## 已知本地工件

macOS 本地 Clash/系统代理拦截 akshare（eastmoney 端点 RemoteDisconnected）。生产 daily 跑通（per [[session_2026_05_27]] 决策已停 launchd 走 nohup），不是 bug。本地 dev 调试可手动 `unset HTTPS_PROXY HTTP_PROXY` + 用 curl_cffi 绕过 TLS 指纹（仅 dev）。

## 不动（PR1 范围外）

- alembic / alerts_sent schema
- yaml 阈值 (0.5% / -5% / -7%)
- 策略 / backtest / daily 路径
- daily 决策权（EOD 唯一权威）

## Backstop 5 条全过

- #1 17 条证伪硬墙：不调 yaml ✓
- #2 双窗口 4y+8y PASS：不改 yaml ✓
- #3 实盘 < 30 笔 closed：不撬 frontier ✓
- #4 PM 决策权：仅 alert，0 自动下单 ✓
- #5 采集 ≠ alpha：alert ≠ decision ✓

## 关联

- [[session_2026_06_07_pr5_intraday_telegram]] — PR5 母体，本次 PR1 续作
- [[session_2026_06_08_self_learning_pipeline]] — 5 条 backstop 来源
- [[capitulation_strategy_falsified_2026-06]] — 第 16 条证伪 (execution vs strategy alpha 区分)
- [[session_2026_05_27]] — macOS TCC / 代理问题已知

## 链接

- PR: https://github.com/Tanglaoye-future/quant_system/pull/21
- Spec: `docs/specs/pr1_intraday_5min_breach.md`

**Why**: 用户后续可能再提"实时/分钟级"类需求；本 session 已沉淀完整侦察数据 + 3 PR 拆分 + 已经守住的 backstop 决策。下次再提同类需求时直接推 PR2/PR3，不重新 0→1 拉硬数据。

**How to apply**:
- 用户提 "实时/分钟级/L2 tick" 类需求 → 先 grep 本 session 数据表；若侦察过的限制未变，直接说明并跳到 PR5 扩展路径
- 不要重做 baostock/akshare 分钟历史侦察（除非 1y 后数据源能力变化）
- 不要再认真考虑分钟级 backtest（撞 Backstop #2 + 第 16 条证伪 双锁）
