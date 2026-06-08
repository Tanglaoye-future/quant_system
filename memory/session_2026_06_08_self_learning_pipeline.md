---
name: session-2026-06-08-self-learning-pipeline
description: 2026-06-08 实盘 "亏损" 反馈触发的 7 PR 大 session — Bug A (exit_reason VARCHAR) + Bug B (alembic 没 upgrade) 修 + DuckDB stale-flock 防御 + self-learning pipeline L1-L5 全链路落地; 程序产出 winner-vs-loser 报告给 PM 看, 永不自动改 yaml
metadata:
  type: project
---

# 2026-06-08 Session — 实盘反馈 → 7 PR 收尾 + Self-learning pipeline

## 触发上下文

用户报告"实盘运行下来都是亏损的, 要你基于实盘反馈找问题 + 迭代策略"。

诚实诊断（按 4 步框架）:
1. **量级**: 实盘真亏 ≈ -0.59% (A_mom 80 万 +0.30% / zhuang 38 万 -2.30%, 67/33 加权)。**单日波动级**, 不是策略坏
2. **真问题不是 alpha**: 是 **3 个系统 bug + 部署偏差**:
   - Bug A: `journal_trades.exit_reason VARCHAR(32)` 容不下 trailing_stop reason (42 char) → 06-05/06-08 daily 挂 3 天没监控
   - Bug B: PG alembic head 停在 `b2c3d4e5f6a7`, PR1/2/3/5 dormant 全没启用 (用户 06-04/06-07 工作的能力 0 启用)
   - Bug C: DuckDB stale-flock — daily_zhuang 异常退出 fd 残留, 下次启动撞自己留下的 lock
   - 部署偏差: v5 5 条腿只上 A_mom + zhuang (HK gate=OFF / A_mr 不自动开仓 / QQQ+GLD 不在系统)
3. **集中度**: A_mom 4 仓全是大金融银行 → momentum 抓上 5 月底大金融轮动正常
4. 用户进一步把实盘视作 RL fine-tuning → "程序有从最近失败交易中学到什么吗" → **诚实答案**: 没有, 而且当前架构不学 (frozen-policy + entry feature 是 TEXT 不结构化 + N=8 太小)

## 7 PR 全清单（顺序）

| # | 内容 | 关键决策 |
|---|---|---|
| #8 | `exit_reason VARCHAR(32)→255` + alembic migration | 同时 ops 一次性 apply PR1/3/5 dormant 一并 启用 → 解 Bug A + Bug B |
| #9 | DuckDBStore atexit auto-close (WeakSet) | 异常退出释放 flock; 不解 SIGKILL; 不强制 get_default_store 单例 (留未来) |
| #10 L1 | `entry_features` + `exit_features` JSONB 列 | nullable + 既有 daily 不写 → 既有行为零变化; alembic head `a6b7c8d9e0f1` |
| #11 L2 | A_mom + HK_mom daily 采集 (helper 在 daily_equity) | 零修改 signals.py; 重 enrich + fail-soft; sector_sw1 留 None |
| #12 L3 | zhuang daily 采集 (helper 在 daily_zhuang) | 复用 `accumulation_score_detail` 拿 5 分量; zhuang ledger 完全隔离 |
| #13 L4 | exit_features 采集 (close_trade **内部自动**) | 设计差异 vs L2/L3: 调用方零改动, Journal own snapshots 自家算 max DD/profit + `exit_layer_from_reason` 解析 |
| #14 L5 | retrospective 报表 `scripts/research/learn_from_trades.py` | 17 falsified manifest + MWU 自实现 (math.erf, 不引 scipy) + N<10 强 warn + footer 强制双窗口纪律 |

7 个 PR 全程严守 06-07 harness-first: spec 先写 + 每步独立 PR + 禁止流式 commit。

## Self-learning pipeline — 5 条硬性 Backstop

写进每个 PR header + 报表 footer + 17 manifest, **永不撞**:

1. **17 条证伪 + 四层 efficient set 同构是硬墙** — L5 manifest 17 条 keyword cross-check
2. **双窗口 4y+8y Sharpe 同向 PASS 才落 yaml** — L5 footer 强制写 "yaml 调参须先 backtest 同向 PASS"
3. **实盘 < 90 天 / < 30 笔 closed 不能撬 frontier** — L5 N<10 强 warn 拒分布差
4. **PM 决策权 — 程序产出报告, 不自动改 alpha** — 报表零写 yaml / 零触发 daily / 零调参建议
5. **采集与 alpha 决策完全分离** — features nullable + 既有 daily 不写 → 既有行为零变化; L5 不引 scipy 等新依赖

**Why**: 用户提"自我学习"易滑向"实盘小样本撬 8y frontier"(paradox 第 5 类 execution-vs-strategy 错配, [[capitulation_strategy_falsified_2026-06]]) 或"自动调参"(撞 17 条证伪 4 次同模式打脸, [[session_2026_06_01_handoff]])。5 条 backstop 是 deliberate over-engineering 的纪律边界。

**How to apply**: 任何"让程序自动 X" 提议（X = 调参 / 选股 / 改 yaml / 起 backtest）前必须先 cross-check 5 条 backstop; 撞了直接拒。任何 yaml 改动仍走 AskUserQuestion 人工通道。

## L5 实盘 dry-run 现状 (2026-06-08)

```bash
venv/bin/python scripts/research/learn_from_trades.py --since 2026-05-22
```

输出 `logs/learn_2026-06-08.md`:
- A_mom: N=1 closed (601066 中信建投, 06-05 trailing_stop pnl +3.46%) → **强 warn 拒分布差**
- HK_mom: N=0
- zhuang: N=0 (3 仓全 open 中, 实盘启动以来无 exit 落地)
- Footer 强制 "Backstop #2 双窗口 + #1 SOFT-FALSIFY"

**首次有效报表估计 ≈ 2026-09** (实盘 ≥ 30 笔 closed)。

## L5.1 backlog（实盘 ≥30 笔后再做）

- chi-square p-value (categorical features, 需 scipy)
- 完整 regex / 阈值 falsified matcher (当前 keyword substring stub)
- markdown 报表接入 dashboard 前端组件
- sector_sw1 接入 (akshare 申万一级行业数据)
- market_cap_band 接入 (zhuang loader filtered_universe 加 cap 字段)

不做（明文写在 spec）:
- 自动 yaml 调参 / online gradient — 永远不做 (Backstop #4)
- mean_reversion exit 采集 (A_mr by design 不自动平仓)
- options exit 采集 (持仓 v2 PR3 schema 不同)

## 已知未修（用户决策项）

1. **实盘部署偏差** — v5 5 条腿只上 A_mom + zhuang
   - HK 25%: gate=OFF (HSI<MA200), by design 等开门, 不用改
   - A_mr 10%: by design 不自动开仓, 可像 zhuang 06-05 补建仓闭环但未做
   - QQQ 5% / GLD 10%: 用户需真去外部账户买, 否则 ρ≈0 分散不存在
2. **集中度 sector cap** — A_mom 4 仓全大金融板块; 加 sector cap 是 alpha-adjacent 改动, 需先 8y 回测验证
3. **trade 2 (601066 中信建投) 退出补回** — Bug A cascade 时 daily 没卖, 用户实际是否在 06-05 真卖了未知 (人工对账)

## 关联

- [[project_live_entry_diagnosis_2026-05]] — 4 步诊断框架; 本 session 实盘 -0.59% 量级校准用了同款
- [[session_2026_06_07_pr5_intraday_telegram]] — Bug B 受害者 (alerts_sent 表 dormant)
- [[session_2026_06_07_pr2_max_drawdown]] — Bug B 另一受害者 (portfolio_history 表 dormant)
- [[session_2026_06_04_realtime_risk_v1]] — 06-04 风控 v1 + 06-07 持仓 v2 工作的能力 Bug B 修后才真启用
- [[session_2026_06_01_handoff]] — 17 条证伪 + 4 次同模式打脸纪律, Backstop #1+#2 来源
- [[capitulation_strategy_falsified_2026-06]] — paradox 第 5 类 execution-vs-strategy 错配, Backstop #3 来源
- [[v5_efficient_frontier_2026-05]] — Backstop #1 守墙
- [[monthly_kpi_scaffold_2026-05]] — 06-30 月度 KPI 与本 pipeline 并行
- [[feedback_harness_first_pr_split]] — 7 PR 全程遵守

**Why**: 用户提"实盘亏损"是 system 诊断 + RL framing 校准 + 7 PR 工程交付的三合一 session, 影响未来所有"程序自我学习" 类提议的边界。
**How to apply**: 未来用户再提 "让程序自动 X" 类需求时, 先读本文件 + 验 5 条 backstop; 撞墙直接拒并指向证伪文档。
