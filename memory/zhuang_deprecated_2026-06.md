---
name: zhuang-deprecated-2026-06
description: zhuang 子策略 2026-06-14 弃用决策 — 违反 4 根支柱硬框架（支柱 1 基本面 + 支柱 2 趋势），config disable + 代码归档保留，组合权重 15-25% 暂留现金缓冲
metadata:
  type: project
---

# zhuang 子策略弃用记录 — 2026-06-14

## 决策

**项目北极星 4 根支柱硬框架确立后**（见 [[project-north-star]]），zhuang 同时违反：
- **支柱 1 基本面选标的** — [[zhuang_l8_fundamentals_falsified_2026-05]] 已证伪：庄股 alpha 与 fundamentals 结构性正交
- **支柱 2 技术面只做趋势** — zhuang 本质是 accumulation/distribution 微结构（吃货期识别 + 横盘共振建仓），不是趋势策略

→ **不在硬框架内 = 弃用**。

## 弃用方式（config disable + 代码归档，可逆）

| 改动点 | 状态 |
|---|---|
| `config/zhuang.yaml` 顶部加 DEPRECATED 头 + `markets.a_share.enabled=false` | ✅ |
| `config/intraday.yaml` `zhuang_distribution.enabled=false` | ✅ |
| `deploy/run_daily.sh` zhuang 调用块注释 + 头注释移除 | ✅ |
| `CLAUDE.md` 项目格局表 zhuang 行划掉 + 加 north star 引用 | ✅ |
| `src/quant_system/strategies/zhuang/` Python 包 | 保留（archive） |
| DB 表 `zhuang_trades` / ledger | 保留（历史回溯） |
| frontend zhuang 组件 | 保留（前端会因无数据自动隐藏） |
| v5 组合 zhuang 15-25% 权重 yaml | **不动** — 用户决策：暂留现金缓冲，不重新分配 |

## 实盘后续（人工跟进项）

1. **当前 zhuang 持仓**（豫园 / 创维 / 长电力 3 仓）— 系统不再发新建仓信号，但**已有持仓不会自动平仓**。需要人工决策：
   - 选项 A：让现有持仓走完原 exit 规则（止盈 10% / 止损 ATR×1.5 / max_hold 10d）后自然出场
   - 选项 B：人工立即清仓转现金
   - 当前默认 = 选项 A（被动等出场），因 daily_zhuang 已不跑，实时风控 zhuang_distribution 也已关
2. **实盘账户 zhuang 资金 15-25%** — 出场后转回现金缓冲，**不重新分配给其他腿**（用户决策）
3. **v5 efficient frontier 重做** — 框架变化后 4y/8y grid 需重跑（[[v5_efficient_frontier_2026-05]] 已在 T+1 重校准后失效一次，加上 zhuang 出局是第二次失效）；不急做，等支柱 3 日内做 T 执行层落地后再统一重做

## 重启路径（如未来 4 根支柱演化）

如果硬框架将来扩展（例如承认"非基本面的微结构 satellite 腿"作为例外），重启 zhuang：

1. 把 `config/zhuang.yaml` markets.a_share.enabled 改回 true
2. 反注释 `deploy/run_daily.sh` zhuang 调用块
3. `config/intraday.yaml` zhuang_distribution.enabled 改回 true
4. 更新 `memory/project_north_star.md` 明文写明 zhuang 是支柱 1+2 的承认例外
5. 跑 4y/8y 双窗口验证仍在 efficient frontier 内

**未做这 5 步前禁止重启** — 否则会重蹈"无北极星导致单策略 sweep 局部最优"的覆辙。

## zhuang 6+ 个月研究资源归档

弃用并不否定 zhuang 历史研究价值。所有 zhuang sleeve 级 Sharpe 1.8-2.4 是真实信号，但**在 4 根支柱硬框架下不是 alpha 的形态**。研究成果作为反例归档：

- [[zhuang_optimization_2026-05]] L1-L5 完整迭代
- [[zhuang_l4_experiments_2026-05]] / [[zhuang_l5_experiments_2026-05]] / [[zhuang_l6a_weights_2026-05]] 单变量 sweep
- [[zhuang_l7a_falsified_2026-05]] / [[zhuang_l7b_falsified_2026-05]] / [[zhuang_l8_fundamentals_falsified_2026-05]] 证伪
- [[zhuang_overlay_2026-05]] / [[zhuang_overlay_combo4_2026-05]] 组合层验证
- [[zhuang_market_dispatch_2026-05]] / [[zhuang_hk_research_2026-05]] HK 移植
- [[zhuang_sweep_2026-06-12]] 全维度最终 sweep
- [[zhuang_gap_score_precheck_falsified_2026-06]] 入场过滤证伪
- [[case_2026_06_08_600584_distribution]] 实盘 -14.32% case study

**Why**: 北极星 4 根支柱硬框架确立后，所有不在框架内的策略一次性出清，避免持续消耗研究资源。zhuang 是第一个被出清的子策略；options/US equity 边缘对齐留观察。

**How to apply**: 任何"恢复 zhuang" / "做新的 zhuang 变体" / "庄股 alpha 探索" 类提议，先指向 [[project-north-star]] 4 根支柱验框架内外；框架外直接拒。如果用户要扩框架，走重启路径 5 步硬卡。
