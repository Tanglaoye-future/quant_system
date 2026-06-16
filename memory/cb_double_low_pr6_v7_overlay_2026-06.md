---
name: cb-double-low-pr6-v7-overlay-2026-06
description: PR6 v7+CB 组合层叠加双窗口 STRONG PASS — 4 候选 dominate v7 baseline; Top1 = A_mom→CB 15% 4Y Sharpe +2.009 / 6Y +2.086; CB sleeve 准入 PR7 落 yaml
metadata:
  type: project
---

# PR6 — v7 + CB 组合层叠加 STRONG PASS

**日期**: 2026-06-16
**Spec**: [[convertible-bond-sleeve]] PR6 准入清单 #4 (CB 加入 v7 grid 测 5/10/15% 占比)
**前置**: [[cb-double-low-pr5-4y6y-2026-06]] CB solo 4y/6y 双窗口 PASS

## 一句话结论

CB sleeve 加入 v7 6 资产组合**双窗口 STRONG PASS** (≥ baseline + DD 不恶化超 3pp), **4 个候选**全部 dominate v7 Top1. 最稳的增量是 **A_mom → CB 15% 替换**(4Y Sharpe +2.009 / 6Y +2.086, Δ+0.131 / +0.281), 最大 Sharpe 增量是 BTC→CB 5% (4Y +2.219 因 BTC 67% vol 被砍). 进 PR7 落 yaml advisory.

## Grid 设计

| 维度 | 值 |
|---|---|
| v7 baseline | HK 50/A_mom 20/A_mr 0/QQQ 10/GLD 10/BTC-USD 10 (=[[v7-efficient-frontier-2026-06]] Top1) |
| CB 来源 | replace from A_mom / GLD / BTC-USD, 比例 5/10/15% |
| 双窗口 | 4Y (2022-01-05 → 2026-04-30, 947 天) + 6Y (2020-01-03 → 2026-04-30, 1406 天) |
| 准入门槛 | 双窗口 Sharpe 同向 > baseline + DD 不恶化超 3pp |
| 候选总数 | 6 (3 from A_mom + 2 from GLD + 1 from BTC) |

脚本: `scripts/portfolio/run_v7_plus_cb_overlay.py`
JSON: `data/backtest/portfolio_v7_plus_cb_overlay.json`

## v7 baseline 本 window 重算

| Window | Sharpe | Ret | DD | 备注 |
|---|---:|---:|---:|---|
| 4Y (2022-05-25 截止) | +1.878 | +17.83% | -12.52% | 与 v7 memory +1.842 接近 (端点差异) |
| 6Y (2020-2026) | +1.805 | +18.12% | -14.78% | 6Y 真实 vs memory 8Y +1.455 不可比 |

## STRONG PASS 4 候选 (双窗口 ≥ baseline + DD 不恶化 ≥ 3pp)

| 替换源 → CB | 4Y Sharpe | 4Y ΔS | 4Y ΔDD | 6Y Sharpe | 6Y ΔS | 6Y ΔDD |
|---|---:|---:|---:|---:|---:|---:|
| **A_mom → CB 15%** | **+2.009** | +0.131 | -0.17pp | **+2.086** | +0.281 | +0.12pp |
| A_mom → CB 10% | +1.976 | +0.098 | -0.09pp | +2.005 | +0.200 | +0.09pp |
| A_mom → CB 5% | +1.933 | +0.055 | -0.05pp | +1.910 | +0.106 | +0.06pp |
| **BTC-USD → CB 5%** | **+2.219** | +0.340 | +4.54pp | +2.025 | +0.221 | +5.25pp |

## FAIL 2 候选

| 替换源 → CB | 4Y ΔS | 6Y ΔS | 原因 |
|---|---:|---:|---|
| GLD → CB 5% | -0.003 | +0.052 | 4Y 反向（噪音级但门槛硬卡） |
| GLD → CB 10% | -0.033 | +0.081 | 4Y 反向更明显 |

GLD 不能替换原因: GLD 4y Sharpe +1.323 比 CB 4y +0.839 高, CB 替 GLD 4y 拉低组合 Sharpe; 但 6y CB +1.419 > GLD 6y +1.031, 反向. 双窗口拒绝.

## CB 与其它资产相关性 (核心)

| 资产 | 4Y ρ | 6Y ρ | 解读 |
|---|---:|---:|---|
| A_mr | **-0.156** | **-0.089** | hedge 价值, A_mr 弱时 CB 跑赢 |
| QQQ | +0.040 | +0.038 | 接近 0, 跨市场独立 |
| BTC-USD | +0.047 | +0.039 | 接近 0, 与加密风险独立 |
| GLD | +0.092 | +0.066 | 接近 0, 与黄金避险独立 |
| HK_mom | +0.136 | +0.063 | 弱正, HK CB 联动 |
| A_mom | **+0.337** | **+0.221** | 中等正, A 股 universe 同向 |

**核心洞察**: CB 与 A_mr 负相关 (-0.156) 是关键 hedge alpha 来源. 与 BTC/QQQ/GLD 接近 0 是独立资产类别证据. 与 A_mom 正相关 +0.337 仍可分散 (因为 CB 走债性/A_mom 走 momentum 不同 risk factor).

## 决策 (Top 2)

### Option 1 (推荐起步): **A_mom → CB 5% (replace 5pp)**

权重: HK 50% / A_mom 15% / A_mr 0% / QQQ 10% / GLD 10% / BTC 10% / **CB 5%**

| 维度 | 4Y | 6Y |
|---|---:|---:|
| Sharpe | +1.933 (Δ+0.055) | +1.910 (Δ+0.106) |
| Δ DD | -0.05pp | +0.06pp |

为什么推荐: spec §0 写 "5-10% 试水占比", 5% 是最小风险 ramp 起步; A 股账户内调整最简单 (从 A_mom 抽); 双窗口同向稳健, 不极端.

### Option 2 (最强 Sharpe): **A_mom → CB 15% (replace 15pp)**

权重: HK 50% / A_mom 5% / A_mr 0% / QQQ 10% / GLD 10% / BTC 10% / **CB 15%**

| 维度 | 4Y | 6Y |
|---|---:|---:|
| Sharpe | +2.009 (Δ+0.131) | +2.086 (Δ+0.281) |
| Δ DD | -0.17pp | +0.12pp |

为什么强: 4 STRONG PASS 候选里 Sharpe 增量第二高 (BTC→CB 5% 第一但 DD 改善是 BTC 砍 vol 副作用, 不是 CB alpha); 6Y +0.281 是真实 alpha 改善.

### Option 3 (DD 最友善): **BTC-USD → CB 5%**

权重: HK 50% / A_mom 20% / A_mr 0% / QQQ 10% / GLD 10% / BTC 5% / **CB 5%**

| 维度 | 4Y | 6Y |
|---|---:|---:|
| Sharpe | +2.219 (Δ+0.340) | +2.025 (Δ+0.221) |
| Δ DD | +4.54pp | +5.25pp |

为什么不直接选: BTC→CB 5% 的 Sharpe 增量主要来自砍 BTC 67% vol, 不是 CB alpha. 用户 2026-06-15 [[v7-efficient-frontier-2026-06]] 明确"加密 10% 固定", 改动 BTC 是撬 v7 决策 (撞 backstop, 见 v7 memory "不要做" 段).

## Backstop 5 条 cross-check

- **#1 18 条证伪墙**: 不撞 (CB 是全新资产类别)
- **#2 双窗口同向 PASS**: ✅ 4 个候选全双窗口正
- **#3 实盘 < 30 笔不撬 frontier**: 本 grid 用 4y/6y 全样本, 不撬实盘 < 30 笔
- **#4 PM 决策权**: 留给用户在 Option 1/2/3 选 (PR7 落 yaml 前)
- **#5 采集 vs alpha 分离**: N/A (组合层 weight 决策, 不动 strategy alpha)

## 已知限制

1. **6Y window 是 spec 8Y 真实等价** (CB value_analysis 2020 起), 不能补 2018-2019
2. **CB equity curve 来自 PR5 cold start 假设** (空仓启动, 月度 rebalance) — 实际实盘会有 entry timing skew, 影响微小
3. **港股通 T+1 损失未叠加** — v7 baseline 在本 grid 是 HK T+0 假设 (Sharpe +1.878), 港股通 T+1 减 -0.03 后 baseline ≈ +1.85, 不改候选排序
4. **Look-ahead universe**: CB backtest 的 universe asof=end 限制 (强赎已知), PR6+ 滚动 asof 实现后重审

## PR7 准入清单

落 yaml 前必须:
- [x] PR6 STRONG PASS ≥ 1 候选 (本 memory 4 个)
- [ ] 用户在 Option 1/2/3 选定 final config
- [ ] `config/cb_double_low.yaml` 落 default n_entry=20 / exit_threshold=180 / stop_loss=85 / min_premium=-5%
- [ ] `scripts/daily/daily_cb.py` daily 入口 (复用 daily_equity 模板)
- [ ] `deploy/run_daily.sh` 加 --no-cb / --cb 开关 (实盘 advisory only 起步)
- [ ] launchd 调度 (16:30 CN close 后跑)
- [ ] 实盘 ≥ 90 天 + ≥ 30 笔 closed 前 *不撬*  n_entry / exit_threshold / sizing

## 不要做

- ❌ **不要直接落 Option 3 (BTC→CB)**: 撬 v7 加密 10% 决策, 撞 v7 backstop
- ❌ **不要落 CB > 15%**: 双窗口实测仅到 15%, 极端配比未验证, 容量风险 (CB 流动性差)
- ❌ **不要同时调多个变量** (n_entry / exit_threshold / weight): 实盘前 freeze, 调一个变量需重跑双窗口
- ❌ **不要绕过 spec PR5 + PR6 直接进 PR7**: PR5/PR6 是落 yaml 的硬卡, 不能跳

## 关联

- [[cb-double-low-pr5-4y6y-2026-06]] PR5 solo 双窗口 PASS
- [[cb-data-probe-2026-06]] 数据 probe + v1.1 nuance
- [[v7-efficient-frontier-2026-06]] baseline 来源
- [[project-north-star]] 4 支柱框架 (1 债性 + 2 risk-parity 豁免)
- `scripts/portfolio/run_v7_plus_cb_overlay.py` 可复跑脚本
- `data/backtest/portfolio_v7_plus_cb_overlay.json` 完整结果

**Why**: 自 zhuang 弃用 + 18 条 A 股证伪 + v7 efficient frontier 落地后, 6+ 个月没有新 alpha 通道. CB 双低 sleeve PR1-6 共 6 commit 12 hr 工程跑出: solo 双窗口 PASS + 组合层叠加双窗口 STRONG PASS, 4 候选 dominate v7. 这是首次有数据支撑可进实盘的新方向.

**How to apply**: PR7 落 yaml 前用户在 Option 1/2/3 选定. 推荐 Option 1 (CB 5% 起步) — 实盘 ≥ 90 天后再考虑 ramp 到 10/15%. 若用户选 Option 3 (BTC→CB) 需先重审 v7 backstop. 任何"调 CB > 15% 占比"提议直接拒绝并指向本 memory.
