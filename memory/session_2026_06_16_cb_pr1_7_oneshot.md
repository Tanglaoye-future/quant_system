---
name: session-2026-06-16-cb-pr1-7-oneshot
description: 2026-06-16 单 session 完成 CB 双低 sleeve PR1-7 全链路 (立项→spec→loader→strategy→backtester→双窗口 PASS→v7 组合层 STRONG PASS→yaml+daily 落地); 9 commit 推 main; 实盘观察期开始
metadata:
  type: project
---

# 2026-06-16 Session — CB 双低 sleeve PR1-7 全闭环 (one-shot)

## 触发上下文

承接 2026-06-15 立项 (上个 session 由用户审计 A 股 sleeve 收益率上限触发, 写 [[cb-data-probe-2026-06]] + [[convertible-bond-sleeve]] spec + 4 支柱扩展, 落 PR1 待 commit). 本 session 用户开场问 "那现在是什么情况" → 我汇报 PR1 等 commit + PR2-7 backlog → 用户决策 **"做 A"** (按 harness-first 切分 PR1-3 三独立 commit 推 main).

之后用户每次决策都是 "做 B" / "做 PR6" / "做 Option 1" / "按你的计划"，连续推进 PR1→PR7。**单 session 14 hr 完成立项→实盘落地全链路**。

## 9 Commit 全清单 (推 origin/main)

| Commit | PR | 内容 | 验收 |
|---|---|---|---|
| `257df76` | PR1 | spec + memory cb_data_probe + 4 支柱扩展 (支柱 1 加债性 + 支柱 2 risk-parity 豁免) | review only |
| `1016909` | PR2 | CBDataLoader 契约红灯 (7 case NotImplementedError) | pytest 7 failed |
| `cc4aac5` | PR3 | CBDataLoader 实现 (akshare 4 端点 + DuckDB cache) + cb_backfill.py smoke | pytest 8 passed |
| `9233ee1` | PR4 | universe §2 filter + double-low §1+§3 strategy (18 case) | 25/25 passed |
| `a039c8b` | docs | probe v1.1 + spec PR5 补丁 — PR4 smoke 实测 3 个 nuance | review only |
| `dea817f` | fix | loader.load_panel try/except akshare 内部 TypeError (920/946 backfill 卡点) | 8/8 + 26 codes 补完 |
| `1415590` | PR5 | CBBacktester + M0 artifact + 4y/6y 双窗口同向 PASS (Sharpe 0.839 / 1.419) | M0 audit PASS + 38/38 |
| `5e4547d` | PR6 | v7+CB 组合层叠加 sweep — 4 候选 STRONG PASS dominate baseline | 双窗口同向 + DD 内 |
| `df70e4f` | PR7 | yaml + daily_cb.py + run_daily.sh --no-cb 开关 (advisory only) | daily smoke 真 top 10 健康 |

## 关键决策时间线

### 1. 立项 cross-check (上 session 已做)
- 4 支柱框架 cross-check: CB 双低撞支柱 1 (基本面 → 扩为含债性条款) + 支柱 2 (趋势 → risk-parity 豁免)
- 数据 probe: akshare 4 端点 PASS, 含退市债 (113008/113537 验证), 容量 < 100M AUM 安全
- 区别已死 18 条证伪 (hsgt/zt_pool/LHB 全不同)

### 2. Harness-first 三段式 PR1-3 (本 session)
- PR2 红灯先落契约 (NotImplementedError 全失败 = 7 case)
- PR3 实现转绿 (8/8 passed) + 备份完整 loader 临时换 stub → 真 red light → 恢复
- 关键: 不假装 harness-first, 真的 stub → 真的红 → 真的绿

### 3. PR4 smoke 实测 3 个 nuance (改变 PR5/PR6 设计)
PR4 落地后跑 `scripts/research/cb_target_today.py --n 200`:
- **Nuance 1**: asof 当日 panel 覆盖率 59% (后跑 --n 0 全市场是 27%) — 大量 illiquid CB 无当日数据
- **Nuance 2**: 双低 score 中位 138-144 (远高于 spec 假设 100-105, 2024+ 估值整体抬升) → `exit_dual_low_threshold` 默认 150 立刻触发出场, 校准 180
- **Nuance 3**: 入场 #1 是负溢价债 127090 兴瑞转债 (prem=-11.58%) — 通常是强赎尾盘, 加 `min_conversion_premium=-5%` 软底

所有 3 个 nuance 立即:
- 写入 probe memory v1.1
- 修 spec PR5 补丁
- PR5 backtester 设计 + UniverseFilterConfig 默认值都按 nuance 校准

### 4. PR3 backfill bug (loader 修复)
全市场 `--n 0` 跑到 920/946 (97%) 时挂 akshare 内部 `TypeError: 'NoneType' object is not subscriptable` (pd.DataFrame(data_json["result"]["data"])). 原 loader 仅 check 返回值是否 None / empty — akshare 内部解析失败拦不住. 修法: `try/except (TypeError, KeyError, AttributeError, ValueError)` 整个 ak 调用. 加 regression test, push fix commit, 重启 backfill 秒级补完剩余 26 只.

### 5. PR5 — 4y/6y 双窗口同向 PASS
直接用 cache 跑两个窗口:
| | 4Y (2022-01-01 → 2026-05-25) | 6Y (2020-01-01 → 2026-05-25) |
|---|---:|---:|
| Sharpe | **+0.839** | **+1.419** |
| CAGR | +19.50% | +25.13% |
| Max DD | -9.93% | -14.87% |
| Trades | 334 | 503 |

6Y Sharpe 与 v7 6 资产组合 8Y Sharpe (1.455) 几乎持平 + DD 友善 — 这是首次有数据支撑可进 PR6 的信号. M0 audit script 加 cb_double_low strategy 分支 (新 schema bond_code / rebalance_date / 无 exit_layer), 4y + 6y 都 PASS.

### 6. PR6 — v7+CB 组合层叠加 STRONG PASS (4 候选 dominate)
6 候选 (replace from A_mom 5/10/15% + GLD 5/10% + BTC 5%) × 双窗口 = 12 portfolio backtest:
| 候选 | 4Y Sharpe (Δ) | 6Y Sharpe (Δ) | 决策 |
|---|---:|---:|---|
| BTC→CB 5% | +2.219 (+0.340) | +2.025 (+0.221) | Sharpe max 但撬 v7 加密 backstop, **不推荐** |
| **A_mom→CB 15%** | +2.009 (+0.131) | +2.086 (+0.281) | 真 alpha 增量 max |
| A_mom→CB 10% | +1.976 (+0.098) | +2.005 (+0.200) | 中间 |
| A_mom→CB 5% | +1.933 (+0.055) | +1.910 (+0.106) | 最稳起步 |
| GLD→CB 5/10% | -0.003 / -0.033 (4Y 反向) | +0.052 / +0.081 | FAIL 双窗口拒绝 |

CB 与 A_mr 负相关 -0.156 / -0.089 (hedge 价值) — 关键洞察. CB 与 BTC/QQQ/GLD ≈ 0 — 独立资产类别证据.

### 7. PM 决策 Option 1 → PR7 落地
用户选 Option 1 (CB 5% 从 A_mom 抽), v7 实盘配比变更:
**HK 50% / A_mom 15% / A_mr 0% / QQQ 10% / GLD 10% / BTC 10% / CB 5%**

PR7 3 文件 + advisory only:
- `config/cb_double_low.yaml` (含 3 nuance 默认 + portfolio.target_pct=0.05)
- `scripts/daily/daily_cb.py` (input 雷同 cb_target_today.py + 写 JSON + filter_universe 复用避免退市债漏入)
- `deploy/run_daily.sh` (加 `--no-cb` 开关, CB section 在 dashboard 前)

Daily smoke 第一次跑出退市债 `404004 close=55` top1 — 因为 daily 自己 reduce 没走 filter_universe, 立即修 inline 复用 filter chain, 第二次跑健康 top 10 (美锦/上银/镇洋/重银/常银/...).

## 沉淀 4 个 project memory (PR5/6/7 + probe v1.1)

| Memory | 内容 |
|---|---|
| [[cb-data-probe-2026-06]] | v1 数据 probe + v1.1 PR4 smoke 3 nuance |
| [[cb-double-low-pr5-4y6y-2026-06]] | 4y/6y 双窗口结果 + M0 artifact PASS |
| [[cb-double-low-pr6-v7-overlay-2026-06]] | 6 候选 grid + 4 STRONG PASS + 3 Option 推荐 |
| [[cb-double-low-pr7-yaml-daily-2026-06]] | 落 yaml + daily + Backstop |

## 本 session 复用的方法论 (来自前 session feedback memory)

- **[[feedback_harness_first_pr_split]]** — 06-07 起强制, 改动开始前写 spec, 每步独立 PR (本 session PR2 真 stub 红灯 → PR3 实现绿是教科书示例)
- **[[feedback_user_collab_style]]** — yaml/实盘改动前 AskUserQuestion (PR7 落 Option 1 前给用户 3 个 Option 决策表)
- **双窗口同向 PASS 才落 yaml** — 5 条 backstop 严守 (PR5 4y/6y + PR6 4y/6y 全双窗口都跑)
- **不绕过 4 支柱框架** — 任何 yaml/策略改动前 cross-check (CB 立项前先扩支柱 1+2)

## 实盘观察期 Backstop (写入 yaml + 多个 memory)

- **≥ 90 天连续运行 + ≥ 30 笔 closed trades 前不撬**:
  - n_entry / exit_threshold / sizing / weight 任何一个
  - 90 天后跑 retrospective ([[session_2026_06_08_self_learning_pipeline]] L5 pipeline)
  - 看 winner-vs-loser 分布再决定 Option 2 (CB 10%) 升级
- **容量 < 100M AUM** — 本 sleeve 5% 占比 < 5M 安全
- **不引入 binary 杠杆 / 不接付费数据**

## 当前活跃子策略对齐度 (北极星 4 支柱)

更新 [[project-north-star]] 表格 (本 session 不动表格, 但 CB 进入 + zhuang 弃用清楚, 用户可自行 update):

| 子策略 | 支柱 1 | 支柱 2 | 支柱 3 风控 | 支柱 4 | 备注 |
|---|---|---|---|---|---|
| equity_factor A 股 | ✅ | ✅ | ✅ | ✅ | 主腿 |
| equity_factor HK | ✅ | ✅ | ✅ | ✅ | 主腿 |
| equity_factor US (SP500) | ⚠️ weights=0 | ✅ | ✅ | ✅ | 边缘 |
| options BCS | n/a 指数 | ⚠️ | ⚠️ | ❌ | 边缘 |
| **cb_double_low** ⭐ 新 | ✅ 债性 | ✅ 豁免 | ⚠️ 风控 schema | ⚠️ retrospective PR8 | **PR7 落地 advisory** |
| ~~zhuang~~ | ❌ | ❌ | n/a | n/a | 2026-06-14 弃用 |

## 下个 Session 接力点

### 优先级 1 — 实盘观察 + 月初首次 rebalance
- launchd 每工作日 16:30 自动跑, 看 `report/data/quant_cb.json` 累积
- **2026-07-01 (下个月第一个 trading day)**: PM 首次人工 rebalance — A_mom 抽 5pp → CB sleeve 20 只等权
- 实盘 N=0 → 90 天累积 N≥30 后退出"不撬"模式

### 优先级 2 — PR8 候选 (留实盘验证后做)
- 接 journal / portfolio_history 让 CB 持仓上 DB (复用 equity_factor 模板)
- 前端 CBSleeveCard 组件 (复用 OptionsPositionTable 模式)
- 滚动 asof universe 修 look-ahead 限制
- score-weighted / inverse-vol sizing (当前 equal 已 PASS)

### 优先级 3 — 候选诱惑严防 (90 天内不撬)
- 不 ramp 到 Option 2 (CB 10%) — 等 90 天数据
- 不调 exit_threshold / n_entry / min_premium — 当前 default 已 STRONG PASS 验证
- 不加 BTC→CB 替换 — 撬 v7 加密 backstop, [[v7-efficient-frontier-2026-06]] "不要做" 段明文

## 已知限制 (PR8+ 修)

1. **look-ahead universe**: backtester `load_universe(asof=end_dt)` 用 end 当 universe → "未来强赎"被排除. 实盘 daily 走 `asof=today` 不撞.
2. **last_trading_date 作 redeem proxy**: backtest 用 `last_trading_date <= asof` 视为强赎生效 (实际公告通常 1-2 月前). PR3 announcement_date 占位 NaT.
3. **6Y 是 spec 8Y 等价**: value_analysis 早期 2019-2020 起, 不能补 2018-2019.
4. **Equal weight only**: PR5/PR7 仅支持 equal. score-weighted / inverse-vol 留 PR8+.
5. **DuckDB cache 锁**: 一个进程一时, daily 一天一次不撞.
6. **akshare 滞后**: panel value_analysis 是 EOD, 16:30 跑 daily 时今天数据可能未更新, 自动 fall back T-1.

## 本 session 没动的 (确认)

- launchd plist (`com.quant.daily.plist`) — run_daily.sh 自动包含 CB section, 不需要改
- v7 组合权重源数据 (`config/equity_factor.yaml` 等) — Option 1 配比变更只反映在 cb_double_low.yaml `portfolio.target_pct=0.05` 字段, 实盘 PM 人工执行
- equity_factor / options 任何代码 — CB sleeve 严守独立 not 撬现有 strategy
- self_learning_pipeline — 不动 5 条 backstop

## Why this session matters

自 [[v7-efficient-frontier-2026-06]] 落地 + 18 条 A 股证伪后, 项目 6+ 个月没出现新方向. 本 session 8 commit 14 hr 跑出:
- solo 4y/6y 双窗口 PASS
- v7 组合层叠加 STRONG PASS 4 候选 dominate
- 实盘 yaml 落地 advisory only

**这是有数据支撑的首个新 alpha 通道**. 也是 single-session 完整闭环 spec→实盘落地 的方法论 reproduction (前次类似规模是 [[session_2026_06_08_self_learning_pipeline]] 7 PR self-learning).

**如果实盘 90 天后 retrospective 显示 CB sleeve 显著贡献 alpha → ramp Option 2 (CB 10%); 显示无效 → 写 cb_double_low_falsified_2026-09.md 归档, 收回 5% 给 A_mom.**

## 关联

- [[project-north-star]] 4 支柱框架 (本 session 不动)
- [[v7-efficient-frontier-2026-06]] baseline 来源 + Option 1 抽源 (A_mom)
- [[zhuang-deprecated-2026-06]] 同期决策 (A 股 sleeve 空缺驱动 CB 立项)
- [[feedback_harness_first_pr_split]] 方法论
- [[feedback_user_collab_style]] PR7 前 Option 选择套路
- 5 个本 session 沉淀 memory: [[cb-data-probe-2026-06]] + PR5/6/7 memory + 本文件
