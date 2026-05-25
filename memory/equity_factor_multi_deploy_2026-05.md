---
name: equity-factor-multi-deploy-2026-05
description: 2026-05-25 Phase 1-B — 放开 equity_factor 一市多策略限制；加 raw["deployments"] 二维索引；equity_momentum 同时部署 a/hk/us 三市场 (hk/us 默认 enabled=false)
metadata:
  type: project
---

## 背景

[[strategy_market_decouple_2026-05]] Phase 1a 装配器把 "一市多策略" 显式抛错（"Phase 1a 仅支持一市一策略"）。这阻止了 [[options_decouple_2026-05]] 之后用户提出的"每市场都能应用 3 个子策略"诉求：equity_momentum 想同时部署到 hk_share / us_share 跑 cross-market 实验时会撞抛错。

Phase 1-B 解开此限制，但保留 equity_hk_momentum / equity_us_momentum 作为"市场原生最优参数"对照（hk_share 上 equity_momentum 跑 A 股最优参数 vs equity_hk_momentum 跑 HK 调优参数）。

## 数据结构改造

**装配后 `cfg.raw`**:
```
raw["markets"][mname]                # 旧接口 (向下兼容下游 14 处 cfg.get("markets", market))
  → 一市多策略时优先存 enabled=True 的 entry; 都 enabled=True 时取第一个 + warning
raw["deployments"][sname][mname]     # 新二维索引 — 精确 (策略, 市场) lookup
  → 所有 deployment 都进, 不论 enabled
```

**resolve_strategy_params(cfg, market, strategy_name=None)**:
- `strategy_name=None` → 走 markets[market] 旧路径 (向下兼容)
- 显式传 → 走 deployments[strategy_name][market] 精确取参

**resolve_strategy(cfg, strategy_arg, market_arg=None)**:
- 反查 deployments 二维索引而非 markets dict (Phase 1a 实现只看 markets[m].strategy_name 反查, 多策略部署时漏看)
- 多 deployment 且只有 1 个 enabled=True 时自动推 (向后兼容旧 cron / launchd 不带 --market 调用)

## 关键设计决策

**1. markets[mname] 占位优先 enabled=True**
- 装配阶段, equity_momentum (deployment hk_share, enabled=false) 先加入; 后来 equity_hk_momentum (enabled=true) 应"替换"前者占位 raw["markets"]["hk_share"]
- **Why**: 不然 hk_share 实盘日报会查到 equity_momentum (enabled=false) → 跳过运行
- **How to apply**: 装配同名 market 第二次出现时, 用 `not prev.enabled and entry.enabled` 替换; 都 enabled 时取第一个 + warning

**2. enabled=true 单一时自动推 (向后兼容)**
- equity_momentum 现部署 3 市场, 旧调用 `--strategy equity_momentum` 不带 --market 时若不自动推会破坏向后兼容
- **Why**: 用户可能有 cron / launchd 直接跑 `--strategy equity_momentum` 不带 market; Phase 1-B 不能破坏此调用
- **How to apply**: enabled=True 的 deployment 数 == 1 时自动推; > 1 时仍要求 --market 显式指定

**3. hk_share / us_share 默认 enabled=false**
- equity_momentum.yaml deployments 列了 a/hk/us 三市场, 但 hk/us 都 enabled=false, capital_pct=0.0
- **Why**: 这只是为命令行 cross-market 实验解锁; 不能让 equity_momentum 跑到 hk_share 实盘 (会跟 equity_hk_momentum capital 冲突 + transferability 差)
- **How to apply**: 跑 cross-market 用 `python scripts/backtest/backtest.py --strategy equity_momentum --market hk_share`; daily_run 不会被影响

**4. 不下沉 timing_overlay (推到 Phase 2)**
- 原 task 描述含"设计 timing 参数分层 (策略基线 + 市场 overlay)", 但 Phase 1-B 没做
- **Why**: 重构成本高 (要分清"算法通用"vs"市场敏感"字段); 也不是本阶段必需 — 当前 equity_momentum 跑 hk_share 直接用 A 股 L7-C3 + L8D2 参数硬跑, 表现弱也算正常实验结果
- **How to apply**: 未来想做"通用 momentum 算法跑赢 3 市场"再 Phase 2 设计 timing_overlay; 现在保留 equity_hk_momentum / equity_us_momentum 做对照即可

## 验收记录

- pytest 全套件 **84/84 通过** (含 11 个新 test_deployments_multi_market.py: 二维索引装配 / enabled 优先占位 / resolve_strategy 多场景 / 向后兼容自动推)
- 命令行验证:
  - `--strategy equity_momentum` (无 --market) → 自动推 a_share ✅ 向后兼容
  - `--strategy equity_momentum --market hk_share` → 进入 build_strategy + Backtester (印花税 0% 正确, 取 hk_share market.fees); 后续因 HSCHK100 基准 lookback 数据问题中断 — 不归 Phase 1-B
  - `--strategy equity_hk_momentum` (无 --market) → 自动推 hk_share, timing.m2_regime_ma_days=200 正确

## 不要做

- 不要让 equity_momentum 在 hk_share/us_share 默认 enabled=true → 实盘 daily_run 会跟 equity_hk_momentum 抢 capital + 资源
- 不要靠 enabled 优先占位机制解决 raw["markets"][mname] 多策略二义; 这只是"代表性 entry", 精确参数永远要走 deployments[sname][mname]
- 不要在 daily_equity.py / backtest.py 改用 raw["markets"][market] 拿参数 (旧路径仅向下兼容)；新代码必须传 strategy_name 走 resolve_strategy_params 精确路径

**Why:** equity_factor 包真正达到了"1 策略 → 多市场部署"诉求; cross-market 实验解锁, 实盘组合不受影响.
**How to apply:** 改 equity_momentum 参数前明确"是算法基线 (写 strategies/) 还是 market 调优 (将来 Phase 2 写 markets/<m>.timing_overlay)"; cross-market 实验脚本用 `--strategy <name> --market <m>` 强制指定; daily_run 保持原命令不变.
