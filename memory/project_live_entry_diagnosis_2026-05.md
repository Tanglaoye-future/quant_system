---
name: project-live-entry-diagnosis-2026-05
description: 实盘已开仓(equity_factor journal 有真实持仓);"持仓都在亏"诊断框架 + journal 入场归因数据缺口(entry_score=0/只填 timing)待查
metadata:
  type: project
---

2026-05-29 用户问"为什么我的持仓股票都是亏损的"。查了 PG journal + 报表 JSON + DuckDB/parquet 价格层后的诊断结论(供未来同类问题复用)。

## 诊断框架(用户问"为什么在亏"时按此拆)

1. **先校准量级**:浮亏常常很小且很新。当时两笔 A 股持仓合计约 -1.3%、都还在止损上方、持有仅 2-5 个交易日。equity_factor 设计持有期 **20-60 天**,几天后判盈亏太早 —— 先纠正"在亏=策略坏了"的前提。
2. **分 beta vs 选股**:查报表 JSON 的 `market_gate` / `market_gate_msg`。当天 HS300 收 4914 > MA60 4708 且比入场时还高 → 大盘在涨,**不是 beta 拖累,是个股/择时问题**。
3. **看入场机制**:A 股 momentum 是追突破(金叉+RSI+量比+20日新高)。典型失败模式 = 买在短期高点后短期均值回归(本次 601066 在 +5.6%、放量 4-5 倍的大阳线收盘被追入,次日即回吐)。这是 A 股 momentum 的机制性弱点(**8y Sharpe ~0.36、低胜率,靠少数大赢家**),多数新仓先浮亏属预期行为,不是 bug。
4. **看集中度**:journal 当时只有 2 只、且都是大金融(601939 建行 + 601066 中信建投)→ 同板块同涨同跌 → "整页飘绿"。v5 部署计划的多腿分散(zhuang/HK/GLD/QQQ,相关性≈0)才是避免"全红"的手段。

**Why**: 用户已进入实盘阶段、会盯真实浮亏并担心;这套"量级→beta/选股→入场机制→集中度"四步能快速给出诚实诊断而非安抚。
**How to apply**: 下次问"为什么亏/为什么没涨",按四步查 journal+报表+价格,区分"正常短期回撤"与"真问题";不要默认是策略坏了。关联 [[deployment_plan_2026-05]] [[equity_factor_l9_partial_regime_2026-05]]。

## entry_score=0 已查清(2026-05-29):不是 bug

PG `journal_trades` 两笔 `entry_score=0` + 只有 `reason_timing` —— 查代码后确认**不是故障**:
- 回测 (`BottomupTimingStrategy.screen`) 与 daily_equity 用**同一套选股**:先全市场扫 timing 突破命中 → 只对命中集 `hit_codes` 做 z-score 排序 (`score_universe`)。
- z-score 在「当天只命中 1 只」时退化为 NaN→`fillna(0)`(`bottomup/factors.py` zscore),所以 `entry_score=0` 多半就是"当天只命中它一只"。因子分只是「同日多只命中抢槽位」的次级排序;**实盘 A 股 momentum 实质=纯择时突破入场**,因子层几乎不起作用 —— 这与回测一致。
- `reason_bottomup` 等三栏 None 是 daily_equity 写 journal 时只传 `reason_timing`(by design),非漏写。

**Why**: 避免未来把这条当未修 bug 重查。真正的"问题"在 momentum 策略本身弱(8y Sharpe~0.36)+ 实盘只上了这一条腿。
**How to apply**: 不要再去"修 entry_score";要提升实盘质量是策略层(入场过滤/换策略)或组合层(上其它腿)的事。

## 真问题 + 已修(2026-05-29):实盘账本 ≠ 回测的 6-asset 组合

查 `strategy_runs`:五条腿(equity_momentum/mean_reversion/zhuang/equity_hk_momentum/QQQ)daily 都在跑,但**只有 A_mom 真正持有仓位**(2 只大金融)。原因:
- HK momentum:市况门 OFF(恒指<MA200),正确空仓。
- **zhuang(目标 40%,组合 Sharpe 引擎):原 `daily_zhuang.py` 只是候选扫描器,不建仓不跟踪** → 这条腿实盘等于没上。
- mean_reversion:daily_equity 里明确"暂不支持自动开仓"。

**已修**:给 zhuang 补了建仓闭环 —— 新建独立 ledger 表 `zhuang_trades`/`zhuang_snapshots`(与 equity `journal_trades` 完全隔离,因 zhuang 出场规则不同,不能让 equity RiskMonitor 评估它);`daily_zhuang.py` 改为 Step1 对 open 仓位 `check_exit_signal`+盯市快照(advisory,不自动平,与 equity 一致)/ Step2 扫候选 / Step3 `check_entry_signal` Phase-A + 市场趋势门 + tiered sizing 自动建仓。用 `--capital`(zhuang≈40% 传 400000)。

**Why**: 用户核心痛点是"实盘≠回测",而承载 alpha 与熊市压舱的 zhuang 40% 根本没建仓。
**How to apply**: "journal_trades 里只有 A 股"不再等于"其它腿没在跑";zhuang 持仓现在在 `zhuang_trades`。zhuang 出场是 advisory(不自动平),持仓满 6 仓后停开 —— 与 equity 同款行为。关联 [[deployment_plan_2026-05]]。
