---
name: project-north-star
description: quant_system 4 根支柱硬框架（项目北极星）— 每次 session 启动 + 每次 yaml/策略/架构改动前必须 cross-check 的最高级约束；撞框架外的需求默认拒绝
metadata:
  type: project
---

# quant_system 项目北极星 — 4 根支柱硬框架

**确立日期**: 2026-06-14
**优先级**: 最高 — 高于所有 M 节点、所有 18 条证伪、所有 efficient set 同构

---

## 4 根支柱

### 支柱 1 — 基本面或债性条款选标的（2026-06-15 扩展）

策略入场的核心 alpha 来源必须包含**基本面因子或债性条款指标**：
- **基本面因子**（股票类）：PE/PB/ROE/revenue_growth/fcf_yield/ROIC/...
- **债性条款指标**（可转债类）：转股溢价率/纯债溢价率/剩余期限/剩余规模/信用评级/...

**例外**：纯指数标的（QQQ/GLD/IBIT 等）不在选股层，可不带基本面/债性但必须服务于组合层分散。

**扩展驱动**：2026-06-15 用户审计 A 股 sleeve 收益率上限，CB 双低是当前唯一通过 4 支柱 cross-check + 数据 probe + survivorship 验证的新方向。详见 [[convertible-bond-sleeve]] spec。

### 支柱 2 — 技术面价格择时，只做趋势（risk-parity 类资产可豁免，2026-06-15 扩展）

**默认**：入场时机由趋势技术信号决定（regime gate 指数>MA + momentum_3m + breakout + RSI band）。
**禁止**：反趋势（mean reversion 仅作 hedge 不作 alpha）、distribution/accumulation 微结构（庄股类）、capitulation 反向情绪类。
**已证伪**：A_mr v2 (4 路径全死) / capitulation 4 重证伪 / 庄股结构性正交 — 详见各 falsified memory。

**豁免**（2026-06-15 扩展）：**risk-parity 类低波动资产**（CB 双低 / 高息债 / 货币基金类）**可豁免趋势择时**，原因是债底保护下"低估均值回归"不撞"反趋势作 alpha"红线。豁免必须满足：
- 资产 vol 低于股票 sleeve 30%
- 有明确的下行底（债底 / 强赎价 / 回售价）
- 不引入"等回调反弹"逻辑（distribution/accumulation 仍禁止）

### 支柱 3 — 持仓中日内做 T+0 + 实时风控

持仓期间必须有：
- **实时风控告警**（pos-level break_stop / break_ma60 / proximity；portfolio-level peak DD / unrealized floor）—— 当前 ✅ 落地
- **日内做 T 执行**（A 股合规版高抛低吸不增持 / HK/US 真 T+0）—— 当前 ❌ 缺位，最大功能缺口

### 支柱 4 — 每笔完成后交易回溯和总结

closed trade 必须采集 entry_features + exit_features → winner-vs-loser 报表 → PM 决策。
**硬约束**：程序产出报告，不自动改 alpha / 不自动调 yaml（5 条 backstop，见 [[session_2026_06_08_self_learning_pipeline]]）。

---

## Cross-check 流程（每次代码/yaml/策略改动前强制）

1. **支柱归属**：本次改动属于支柱 1/2/3/4 哪一根？跨支柱说明清楚。
2. **框架内验证**：改动后是否仍满足该支柱的核心约束？
3. **撞墙检查**：是否撞 18 条证伪 / efficient set 同构 / 5 条 backstop？
4. **结论**：在框架内 → 继续；框架外 → 拒绝或归档，不进 daily / 不进回测主线。

撞框架外的需求 = 默认拒绝（口头确认用户是否要扩框架后再做）。

---

## 当前活跃子策略对齐度

| 子策略 | 支柱 1 | 支柱 2 | 支柱 3 风控 | 支柱 3 做T | 支柱 4 | 备注 |
|---|---|---|---|---|---|---|
| equity_factor A 股 (equity_momentum) | ✅ | ✅ | ✅ | ❌ | ✅ | 全对齐主腿 |
| equity_factor HK (equity_hk_momentum) | ✅ | ✅ | ✅ | ❌ | ✅ | 全对齐主腿 |
| equity_factor US (equity_sp500_momentum) | ⚠️ weights=0 | ✅ | ✅ | ❌ | ✅ | 基本面 alpha 实测无效，技术面对齐 |
| options BCS (QQQ Bull Call Spread) | n/a 指数 | ⚠️ 方向性看多≈趋势 | ⚠️ 风控 schema 不同 | ❌ | ❌ exit schema 不同 | 边缘对齐，组合层分散价值 |
| **cb_double_low（spec 阶段）** | ✅ 债性条款（扩展后） | ✅ 豁免（扩展后） | ⏳ M5 复用 schema | ⏳ T+0 推迟 | ⏳ closed_trades 复用 | **2026-06-15 立项**，见 [[convertible-bond-sleeve]] |
| ~~zhuang~~ | ❌ | ❌ | n/a | n/a | n/a | **2026-06-14 弃用**，见 [[zhuang-deprecated-2026-06]] |

---

## 最大缺口（按优先级）

1. **支柱 3 日内做 T 执行层** — 零代码，需要从 0 设计 spec（A 股 T+0 合规高抛低吸 / HK/US 真 T+0 执行循环）
2. **支柱 4 样本累积** — 实盘 closed N 太小（A_mom 1 / zhuang 0），首次有效报表 ≈ 2026-09
3. **options 在框架内的定位** — 仅趋势对齐 + 风控 schema 异质，要么演化补齐，要么承认作为"组合层分散资产"例外

---

**Why**: 2026-06-14 用户审计发现 4 根支柱硬框架从未作为刚性记忆每次 session 调用，导致策略迭代容易掉入单策略 sweep 局部最优，偏离顶层目标。zhuang 长期违反支柱 1+2 但因没北极星而继续投入 6+ 个月研究资源。

**How to apply**: 每次 session 启动必读本文件 + CLAUDE.md。任何 yaml / 策略 / 架构改动前，先在脑里把支柱 1-4 跑一遍 cross-check；撞框架外的需求口头确认"是否要扩框架"再做。当 4 根支柱本身需要演化时，更新本文件 + CLAUDE.md 同步。
