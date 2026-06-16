---
name: cb-double-low-pr7-yaml-daily-2026-06
description: PR7 — CB 双低 yaml + daily + run_daily.sh 落地 (advisory only); CB 5% (从 A_mom 抽) Option 1 起步; 实盘 ≥ 90 天 + ≥ 30 笔前不撬阈值
metadata:
  type: project
---

# PR7 — CB 双低 yaml + daily 落地

**日期**: 2026-06-16
**Spec**: [[convertible-bond-sleeve]] PR7 准入清单
**前置**: [[cb-double-low-pr6-v7-overlay-2026-06]] STRONG PASS + PM 选 Option 1

## 一句话结论

`config/cb_double_low.yaml` + `scripts/daily/daily_cb.py` + `deploy/run_daily.sh --no-cb` 全部落地, **advisory only — 不接 journal / portfolio_history**. 每个工作日 launchd 16:30 跑 → `report/data/quant_cb.json`. PM 月初人工 rebalance 参考.

## 落地配置 (Option 1)

| 项 | 值 | 来源 |
|---|---|---|
| n_entry | 20 | spec §3 |
| n_hold_buffer | 1.5 | spec §3 |
| exit_dual_low_threshold | **180.0** | nuance 2 校准 (vs spec 原 150) |
| stop_loss_close | 85.0 | spec §3 |
| min_conversion_premium | -5.0 | nuance 3 校准 |
| min_close | 80.0 | spec §2 |
| min_scale_remain_yi | 1.0 | spec §2 |
| min_years_to_maturity | 0.5 | spec §2 |
| rebalance_freq | monthly | spec §3 |
| weight_scheme | equal | PR5/PR7 仅 equal |
| target_pct | **0.05** | PM Option 1 (CB 5% 从 A_mom 抽) |
| source | A_mom | PM Option 1 |

v7 组合实盘配比 (PR7 起):
**HK 50% / A_mom 15% / A_mr 0% / QQQ 10% / GLD 10% / BTC 10% / CB 5%**

## PR7 产物清单 (all ✅)

- [x] `config/cb_double_low.yaml` — 完整 yaml, 含 北极星 cross-check 注释
- [x] `scripts/daily/daily_cb.py` — daily 入口, advisory only, 输出 top N + 强赎提示
- [x] `deploy/run_daily.sh` — 加 `--no-cb` 开关 (默认 ON), CB section 在 dashboard 前
- [x] `report/data/quant_cb.json` schema 落定 (date/asof_panel/config/universe/filter_stats/entries_top/warn_redeem_near)
- [x] launchd 调度 — **已通过 run_daily.sh 自动包含 CB section, 无需改 plist** (com.quant.daily 已每工作日 16:30 跑)

## PR7 不做 (留后续 PR8+)

- ❌ 不接 journal / portfolio_history (advisory only, PM 人工执行 rebalance)
- ❌ 不接 intraday risk (CB sleeve 月度 rebalance, 日内 T+0 暂不需要)
- ❌ 不接前端 dashboard 组件 (PR8 可加 CBSleeveCard 同 OptionsPositionTable 模式)
- ❌ 不动 launchd plist (已经在跑 run_daily.sh, plist 已设好)
- ❌ 不实现 score-weighted / inverse-vol sizing (PR8+, 当前 equal 已 PASS)

## advisory only 工作流

```
launchd 16:30 → run_daily.sh
              → daily_cb.py 跑出 today 双低 top 20
              → 写 report/data/quant_cb.json
              → 前端 dashboard 读 (PR8 加组件) 或 PM 直接看 JSON
              → PM 月初一日 (每月第一个 trading day) 人工 rebalance:
                 - 把 A_mom 抽 5pp → 买入双低 top 20 等权 1/20 = 0.25% 总资产/只
                 - 月内 buy & hold (除非触发 force exit: 强赎/止损/score>180)
              → 月末复盘
```

实盘验证条件 (Backstop #3):
- **≥ 90 天连续运行** + **≥ 30 笔 closed trades** 后才考虑:
  - ramp 到 Option 2 (CB 10%) 或 Option 3 不撬 v7 backstop 不动
  - 调 n_entry / exit_threshold / 任何阈值
  - 加 score-weighted sizing

## Backstop 严守 (写入 yaml 注释)

1. 实盘 ≥ 90 天 + ≥ 30 笔 closed 前不撬 n_entry / exit_threshold / sizing
2. 容量 < 100M AUM (本 sleeve 5% 占比 < 5M 安全)
3. 不引入 binary 杠杆 / 融资融券
4. 不接付费数据 (akshare 已 probe PASS)
5. 撬 CB > 15% 配比需重跑 PR6 grid

## 北极星 4 支柱对齐 (再确认)

| 支柱 | 对齐 | 备注 |
|---|---|---|
| 1 基本面或债性 | ✅ | 转股溢价率 + 纯债溢价率 + 规模 + 评级 = 债性选标的核心 |
| 2 趋势择时 | ✅ (豁免) | risk-parity 类低波动 + 债底保护; 不撬"反趋势不作 alpha"红线 |
| 3 实时风控 + 日内 T | ⚠️ 部分 | 风控 schema PR5 已复用 force exit, 日内 T+0 PR7 暂未做 |
| 4 trade retrospective | ⚠️ 部分 | closed_trades 管道在 PR5 backtester 已有, daily 实盘版本 PR8 |

## 已知运行风险

1. **DuckDB cache 锁冲突**: cb_cache.duckdb 一次只能一个进程持有锁. 测试时多个 cb_target_today / daily_cb 并发会报 IOException. daily 一天只跑一次不撞.
2. **akshare 滞后**: panel value_analysis 是 EOD 数据, 16:30 跑 daily 时今天数据可能还未更新, daily 自动 fall back 到 T-1 (panel 最新可用日).
3. **panel 覆盖率不齐**: 实测 27-47% (smoke test 4y/6y), daily 输出 entries_top 时实际只在覆盖率内排序; PR8 可加 "覆盖率 < 50% 时 daily 日报标 ⚠ 提示"
4. **首次跑 cold backfill**: 全市场 946 只 panel cold 第一次 ~5 min; 之后 DuckDB cache hit 秒级. daily 第二天起秒级.

## PR7 验收清单

- [x] yaml schema 完整 (data + strategy + filter + account + portfolio + daily 6 块)
- [x] daily_cb.py 跑 --no-write --top 10 smoke 通过 (universe 1012 + active 946 + panel cold + filter + top N)
- [x] run_daily.sh 加 CB section + --no-cb 开关 (位置在 panic dashboard 前)
- [x] CB section 失败不阻塞 daily 主流程 (`|| warn` 不退出)
- [x] launchd com.quant.daily 工作日 16:30 自动跑 (不动 plist)
- [x] memory 完整记录 PR1-7 全链路

## 关联

- [[cb-double-low-pr6-v7-overlay-2026-06]] PR6 组合层叠加 STRONG PASS
- [[cb-double-low-pr5-4y6y-2026-06]] PR5 solo 4y/6y PASS
- [[cb-data-probe-2026-06]] 数据 probe + v1.1 nuance
- [[v7-efficient-frontier-2026-06]] baseline (Option 1 抽源)
- [[project-north-star]] 4 支柱框架
- `config/cb_double_low.yaml`
- `scripts/daily/daily_cb.py`
- `deploy/run_daily.sh`

**Why**: CB 双低 sleeve 自 2026-06-15 立项, 经 PR1-7 共 8 commit 14 hr 工程 + 6 个 backtest sweep, 双窗口 + 组合层 STRONG PASS. PR7 是最后一道工程闸门, 落 yaml 后实盘开始. 用 ≥ 90 天实盘验证替代 "再跑一轮 sweep" 的诱惑.

**How to apply**: PR7 后 90 天内任何"调阈值 / 加因子 / 升 sizing" 提议直接拒绝并指本 memory + Backstop #3. 90 天后实盘 ≥ 30 笔 closed 时, 跑 retrospective (复用 [[session_2026_06_08_self_learning_pipeline]] L5 pipeline), 看 winner-vs-loser 分布再决定 Option 2/3 升级.
