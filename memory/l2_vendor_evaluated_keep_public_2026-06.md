---
name: l2-vendor-evaluated-keep-public-2026-06
description: 2026-06-11 用户提"数据层限制策略层"诉求 → TradingView 否决 + L2 vendor 7 家决策表（Tushare/JQData/RQData/通联/iFinD/Wind/Futu）→ 用户决定先用公开数据；记录 vendor 价格区间 + 复活路径条件，未来同类需求直接引用
metadata:
  type: project
---

## 一句话结论

用户问"TradingView/L2 数据能否解放策略层" → 拉完 7 家 vendor 决策表后用户选择**继续用公开数据**（baostock + akshare）。**L2 付费数据路径暂封**，复活条件：先用 JQData 免费版做分钟级 precheck，winner/loser 在分钟特征上出现 daily 看不到的可分离 effect 才考虑付费升级。

## Vendor 决策表（2026-06 调研快照）

| Vendor | 个人可购 | A 股分钟 | A 股 L2 tick | HK 分钟/tick | 价格/年 |
|---|---|---|---|---|---|
| Tushare Pro | 是 | 全历史 | 仅期货 | HK 日线 ¥1000 | ¥3k-15k |
| JQData | 是 | 1min 全 | ❌ | ❌ | **免费** (日 100 万条) |
| RQData | 是 | 1min + 实时 | ❌ | 有限 | 询价 ¥1-3 万 |
| 通联 DataYes | 是（商城）| ✅ | ⚠️ L2 加购 | ✅ A+HK 全 | 询价 ¥1-5 万 |
| 同花顺 iFinD | **机构邮箱**门槛 | ✅ second-level | ✅ L2 全 | ✅ HK L2 全 | ¥8k-¥39.8k/模块 |
| Wind 万得 | **机构**门槛 | ✅ tick | ✅ HK L2 含 | ✅ 全 | 单终端 ¥39.8k，全 ~¥18 万 |
| Futu OpenAPI | 是 | 历史短 | ❌ | **历史 tick 是 1min K 模拟，假的** | 免费 |

## TradingView 否决理由

1. 没公开 historical API（只卖 B 端 charting library ¥15k+/年）
2. 第三方爬虫 (tvDatafeed) 违反 ToS + IP 封锁，不能做生产
3. 数据源同源 — 它的上证分时来自交易所 + 同花顺/Wind，不会多出 1.6y 历史突破 Backstop #2

## 复活路径条件（封不死的口子）

L2 付费数据**唯一可能复活**的路径（per [[capitulation_strategy_falsified_2026-06]]）：先做 0 元 precheck。

**判定门**：
1. 用 JQData 免费版拉 zhuang 现有 57 trades 的入场 T-1 ~ T+5 分钟级数据
2. 复跑 `zhuang_capitulation_entry_precheck.py` 用分钟特征（盘中放量时序、分时背离、尾盘吸筹）
3. winner vs loser 分钟级特征 → 反向 / 无差异 → **第 17/18 条证伪 + 永久封死 L2 路径**
4. winner vs loser 分钟级特征 → 可分离 → 才上 C/D 档付费（¥3-18 万）

## 推荐 vendor 排序（如未来真要付费）

- B 档 ¥3-8k：**Tushare Pro** — A 股全频率 + HK 日线，工程理性，但不破 efficient frontier
- C 档 ¥3 万：**通联 DataYes** — HK 分钟级唯一可负担入口（重启 [[zhuang_hk_research_2026-05]] 死路）
- D 档 ¥4 万+：**iFinD（需机构邮箱）/ Wind ¥18 万** — 真 L2 tick，capitulation 复活唯一路径

**不推荐**：Futu（HK tick 是 1min K 模拟，假数据回测会得到假 alpha）、JQData 升级版（HK 不覆盖）

## Why

下次用户再提"实时/L2/TradingView/分钟级"类诉求，直接引用本表 + 复活路径条件，省 1-2 hr 重做 vendor 调研。本次决策 = 数据层非瓶颈，瓶颈在 alpha 通道本身（17 条证伪累积证明 daily 频率不缺信号缺 alpha）。

## How to apply

- 用户问"TradingView/同花顺/Wind/L2 能不能用" → 引本表 + 否决理由 + 复活路径
- 用户坚持要付费 → 先要求跑 0 元 JQData 分钟级 precheck，门没过不付钱
- 不要再做 vendor 价格调研（除非 1y 后情况变化或用户明确要更新）
- vendor 价格快照可能 6-12 月失效，关键链接：tushare.pro/document/1?doc_id=290 / mall.datayes.com

## 链接

- 上游: [[session_2026_06_09_realtime_data_intraday_5min]] — 之前已侦察 baostock/akshare 分钟数据
- 上游: [[capitulation_strategy_falsified_2026-06]] — 第 16 条 + "L2 是唯一复活路径" 来源
- 关联: [[v5_efficient_frontier_2026-05]] — 数据非瓶颈的基础判断
- 关联: [[zhuang_hk_research_2026-05]] — HK 数据死路 + 通联是唯一可负担破口
- 方法论: [[feedback_harness_first_pr_split]] — 付费前必须 precheck
