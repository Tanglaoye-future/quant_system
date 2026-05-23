---
name: strategy-market-decouple-2026-05
description: 2026-05-22~23 equity_factor 子策略包内"策略-市场解耦"四段改造的设计决策与背景；以策略为主轴而非市场，让算法可独立迭代后部署到任意支持市场
metadata:
  type: project
---

## 背景：用户的原始痛点

equity_factor 子策略包原本以**市场**为主轴：`markets.a_share.timing`、`markets.hk_share.timing`、`markets.us_share.timing` 三套参数共享同一个 `BottomupTimingStrategy` 类名但参数全然不同 — 想改"动量策略"得同时改三处，且每次实验都耦合在某个市场上下文里。

用户原话："把策略分开迭代，然后迭代好策略再把策略分别应用于不同的市场而不是依赖市场的策略"。

## 解耦方向

颠倒索引：从 **"market → strategy params"** 翻成 **"strategy → market deployments"**。

- 算法层（timing / factors.weights / hedge / admission）→ `config/strategies/<name>.yaml`，**自包含**完整算法
- 市场环境层（universe / benchmark / 数据源 / fees）→ `config/markets/<m>.yaml`
- 账户层（资金 / commission / position_max / m4）→ 入口 `equity_factor.yaml`，跨策略共享
- 策略文件用 `deployments:` 列出可部署到哪些市场

## 关键设计决策（why）

**1. 算法层"自包含"而非"基底 + 覆盖"两层**
- 策略文件直接写满 timing 所有字段，不依赖全局默认
- **Why**: 用户要"独立迭代"。如果继续走 `merge(global_default, strategy_override)`，那"动量策略 v10"和"全局默认"仍耦合，改全局会影响所有策略
- **How to apply**: 写新策略时直接复制现有策略 yaml 改名，不要建 base 文件继承机制（YAGNI；3 个策略文件 + 30 个 timing 字段 = 90 行重复，可接受）

**2. m4 / 账户层留在入口共享**
- factors.m4 / strategy.{position_max_count, single_position_pct_max} 仍在入口 yaml
- **Why**: `backtest.py` 从全局读 m4，且这些是"账户/组合层"属性，跨策略共享更符合直觉
- **How to apply**: 如未来 zhuang/momentum 要不同 m4，再下沉到策略文件；现在共享是对的

**3. 保留 `self.market: str` 字段（与 `self.market_ctx: MarketContext` 并存）**
- Phase 2a 引入 MarketContext 后，策略类既有 `market` str 也有 `market_ctx`
- **Why**: `loader.get_daily(market, code)` 内部按市场名 dispatch 数据源（akshare A 股 vs akshare HK vs 美股 CSV），这是合理的 multi-tenant 数据抽象，不是泄漏
- **How to apply**: market_ctx 只承载"行为分支"能力（universe_filter / industry_concentration / fees）；market str 只用于 loader 数据源 dispatch。两者职责分离

**4. CLI `--strategy` 同时支持策略名和工厂 kind**
- `--strategy equity_momentum` 是策略名（新模式，自动推 market）
- `--strategy bottomup_timing --market a_share` 是工厂 kind（旧模式，向下兼容）
- **Why**: 切 CLI 一次性会破坏所有现有命令习惯；保留 kind 模式让旧实验脚本（run_l7_*.py 等）继续工作
- **How to apply**: `quant_system.config.resolve_strategy()` 自动判定输入是策略名还是 kind

**5. 一市多策略目前显式抛错**
- 装配 loader 检测到两个策略同部署到同 market 时 `raise ValueError`
- **Why**: 当前没有"两个策略同市场跑对照实验"场景；显式失败比静默覆盖好
- **How to apply**: 未来要做对照实验时再解除限制（需要回测 output_dir 改用 `<strategy>_<market>` 双索引，已经是这样）

## 顺手修复的两个回归 bug

**1. `daily_equity.py` 漏 merge `markets.<m>.timing`**
- Phase 1b 前 daily_equity 只读全局 `strategy.timing`，没合并市场覆盖 → **a_share L7-C3 出场优化（atr_stop_mult=1.5 / m5_regime_exit / partial_exit）实盘 daily_run 一直未生效**
- 修复后 daily_run a_share 终于会用上 L7-C3
- **How to apply**: 如未来发现 daily 跑出来的策略行为与 backtest 不一致，第一时间查 daily 端是否也走 `resolve_strategy_params()`

**2. `backtest.py` output_dir path bug**
- `Path(__file__).resolve().parents[1]` 解析到 `scripts/` 而不是 repo root → 回测产物错落到 `scripts/data/backtest/`
- Phase 1b 修为 `parents[2]`

## 未来扩展指南

- **加新策略**（同算法 kind 不同参数变体）：新建 `config/strategies/<name>.yaml`，在入口 `equity_factor.yaml` 的 `strategies:` 加一行
- **加新市场**：新建 `config/markets/<m>.yaml`（universe/benchmark/fees/universe_filter/industry_concentration），在入口 `markets:` 加一行；`data/loader.py` 加该 market 的数据源 dispatch 分支
- **一市多策略对照**：先在装配 loader 解除显式抛错限制（搜 "一市多策略" 注释）；输出目录 `<strategy>_<market>_<start>_<end>` 天然支持
- **zhuang / options**：暂未拆，它们天生单市场（A 股小盘 / QQQ 期权）无解耦诉求；若未来 zhuang 要跑 HK 小盘股，可按本次模板拆分

## 不要做

- 不要把 `loader.get_daily(market, code)` 内的市场分支也解耦 — 那是数据层的合理 dispatch，不是策略层泄漏
- 不要为"假设的未来需求"建 base 策略继承机制
- 不要在策略文件里写 `extends: base.yaml` 之类的引用 — 当前 3 策略 90 行重复完全可接受，继承会引入排错复杂度

**Why:** 解耦完成后用户可专注"算法迭代"而非"找哪份配置该改"；scripts 入口 `--strategy <name>` 配合 deployments 自动推导让命令行也匹配这个心智模型.
**How to apply:** 改 equity_factor 算法前先确认要触达的策略文件；新策略实验从 copy 一份 strategies/ yaml 开始；daily 与 backtest 共享 resolve_strategy_params 是参数一致性的核心保证.
