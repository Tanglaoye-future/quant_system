---
name: zhuang-hk-research-2026-05
description: 2026-05-25 Phase 1-D — HK 小盘股 zhuang 回测可行性调研结论；不接入 provider；记录已踩的坑供未来重启时复用
metadata:
  type: project
---

## 背景

[[zhuang_market_dispatch_2026-05]] 完成 zhuang 架构拆 markets/ 后，Phase 1-D 原计划接入 HK provider + 跑 4y/8y 双窗口回测验证 zhuang 算法对 HK 庄股的有效性。

实操遇到的现实约束让 ROI 不成立 → 退回"先调研不接入"。架构占位 (`config/markets/hk_small.yaml` enabled=false + ZhuangDataLoader hk_akshare NotImplementedError) 保留，未来重启时直接基于本调研落地。

## 数据源现状（2026-05-25 调研）

| Provider | HK universe | HK 日线 | 历史市值 | 换手率 | 用户网络可达性 |
|---|---|---|---|---|---|
| akshare.stock_hk_spot (sina) | ✅ 2760 只 | ❓ | ❌ | ❌ | ✅ |
| akshare.stock_hk_main_board_spot_em | ✅ 含市值 | - | ❌ | - | ❌ ProxyError (push2.eastmoney.com 在用户网络连不通) |
| akshare.stock_hk_hist (em) | - | ✅ daily/weekly/monthly | - | ❓ | ❌ ConnectionAborted |
| yfinance 0700.HK 形式 | ❌ 没 universe 接口 | ✅ history(start,end) | ❌ .info 只有当前快照 | ❌ 不提供 turnover_rate 字段 | ✅ |

**关键 blocker**:

1. **akshare 全 eastmoney HK 接口在用户网络不通**: `81.push2.eastmoney.com` 一直 ConnectionAborted。试过 unset HTTP_PROXY / NO_PROXY=*；都失败。Sina 接口 (`stock_hk_spot`) 可达但缺市值字段
2. **yfinance 无 universe**: 必须自己枚举 ticker list (HSI 50 + HSCEI 50 + 自定义中盘约 100 只) 才能拉数据；2760 只全枚举 1-2 小时
3. **历史市值不可得**: 任何来源都只给当前 .info 市值。要按"当年市值 10-30 亿 HKD 小盘"动态筛 universe 拉不到历史
4. **换手率字段缺失**: yfinance 不提供 turnover_rate。zhuang accumulation_score 5 维信号里第 4 维 `turnover_decline_score` 在 HK 上必然无效化（代码已经 graceful: 缺列返回 0）

## 为什么 ROI 不成立 (退回先调研的理由)

即使强推 yfinance HK 路径跑回测，结果不可信：

1. **静态 universe + survivorship bias**: 只能用 2026 当前 universe 跑 2018-2026 回测，已倒闭/退市的"成功庄股"全缺；幸存者偏差严重高估收益
2. **accumulation 信号降级**: 5 维降 4 维（缺 turnover），评分阈值 70/75 校准失效
3. **HK 庄股语义本身存疑**: HK 市场结构（外资盘多、可裸卖空、无 T+1、无涨跌停）跟 A 股庄股操盘模式不同；算法对 HK 庄股有效性先验低
4. **Sharpe 任何结果都难解读**: Sharpe < 0.3 → 不知道是 (a) 算法不成立 (b) bias 抵消太狠 (c) 数据降级；Sharpe > 0.5 → 不可信 (survivorship-bias 注水)

→ 工程投入 (1-2 天) 换不到可信结论 → 退

## 未来重启 1-D 的前置条件

要让 HK 回测结论可信，必须先解决：

1. **网络打通 eastmoney**: 用户切换网络 / 用国内云服务器 / 代理白名单允许 push2.eastmoney.com → 才能用 akshare stock_hk_main_board_spot_em 拿含市值的 spot, 用 stock_hk_hist 拿日线
2. **历史市值快照**: Wind / Choice 等付费数据源 (有月度市值历史快照) 或自己实现"市值×流通股反推 (price × shares_outstanding 历史) "
3. **HK 换手率数据**: 港交所 OR 万得 (vendor 接入); akshare/yfinance 都不提供
4. **HK 小盘股基准选型**: HSI/HSCEI 都是大盘；恒生小型股指数 (HSI Smallcap) / 恒生综合中小型股指数 (HSCMI) 才是合适基准 → 需要确认 baostock/akshare/yfinance 哪个能拉

## 未来重启的实施路径 (如上述前置满足)

1. ZhuangDataLoader 加 `_fetch_universe_hk(asof)`: akshare stock_hk_main_board_spot_em 拿全量 + 市值; 按 markets.hk_small.universe.market_cap_min_hkd/max_hkd 筛
2. `_fetch_daily_hk(code)`: akshare.stock_hk_hist 拿日线 (含 turnover 字段确认后)
3. config/zhuang.yaml `markets.hk_small.data_provider`: hk_akshare → 删除 ZhuangDataLoader 里的 NotImplementedError 分支
4. benchmark 字段填实际 HK 小盘指数 ticker
5. 跑 4y (2022-2026) 验证算法 — Sharpe 阈值 >=0.5 才考虑接入实盘 6-asset overlay (当前 [[zhuang_overlay_combo4_2026-05]] 6y Sharpe 2.35 的 a_share zhuang 是高标)
6. 双窗口 8y (2018-2026) 验证 (按 [[feedback_user_collab_style]] 第 3 条)

## 不要做

- 不要用 yfinance 强推 (即使能跑) — survivorship-bias 注水让结论不可信，浪费回测时间
- 不要把 `markets.hk_small.enabled` 改 true 直到 provider 真接入且 4y/8y 双验通过
- 不要假设 zhuang 算法在 HK 庄股有效 — 市场结构差异先验是负面的

**Why:** 退回先调研让 Phase 1 在没浪费工程的情况下确定 HK 验证暂不可行；架构占位 ([[zhuang_market_dispatch_2026-05]]) 让未来网络/数据条件改善后能快速重启.
**How to apply:** 用户网络通了 eastmoney 或买了历史市值数据源后, 直接基于本 memory 的"未来重启实施路径"恢复 1-D; 不要重新踩 yfinance survivorship-bias 的坑.
