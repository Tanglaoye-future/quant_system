---
name: session-2026-06-09-pr2-watchlist-breakout
description: PR2 of 3 (intraday 实时化) — daily watchlist 写入 + 候选股盘中突破入场告警 (daily_screen_breakout, warning); 与 PR1 持仓告警解耦; 5 条 backstop 全过, 0 自动下单
metadata:
  type: project
---

# 2026-06-09 Session — PR2 watchlist + 候选股盘中突破告警

接续 [[session_2026_06_09_realtime_data_intraday_5min]] (PR1)。3 PR 中 PR2。

## 范围

T 日 EOD daily_equity 跑完写 `data/intraday/equity_watchlist.json`，T+1 盘中 5min cron 读 watchlist → 拉实时报价 + 量比 → 评估突破 → Telegram 推送「可考虑次日开盘建仓」。**永不自动下单**。

## 新增模块/类型

- `src/quant_system/intraday/watchlist.py`：
  - `WatchlistCandidate` dataclass (symbol/name/reference_high/reference_close/entry_sl_tp/factor_score/reasons)
  - `Watchlist` dataclass (asof_date/strategy/market/candidates)
  - `dump_watchlist` / `load_watchlist` / `is_watchlist_stale` 纯函数
- `core.py`：
  - `BreakoutConfig` (enabled/breakout_margin/vol_ratio_min/watchlist_max_age_days/strategies)
  - `BreakoutCandidateQuote` 评估输入
  - `evaluate_breakout_alerts` 纯函数 → warning 级 `daily_screen_breakout` alert

## 关键设计决策

- **解耦 evaluate**：breakout 与持仓告警（PR1 的 evaluate_alerts）走两条独立纯函数。run_once 中也解耦：**无 open_trade 时仍评估候选**（PR1 之前的 hard exit 撤掉）。
- **量比降级**：akshare spot_em '量比' 字段缺失 → vol_ratio=None → **仍发 alert**（保守不挡，message 显示 `量比 N/A`）。
- **dedup once-per-day**：UNIQUE 不变，**无 alembic migration**。`alerts_sent.asof_date` 是 intraday 触发日 (T+1)，与 `watchlist.asof_date` (T) 解耦。
- **dry-run / no-write 不写 watchlist**：daily 干跑不产生副作用文件。
- **stale noop**：watchlist > 5 自然日 → intraday 不消费（用户没跑 daily 自然降级）。
- **仅 equity_factor + A 股**：mean_reversion 是 bottom-fish 反向逻辑、HK spot_em 没量比，都不进 watchlist。zhuang 留 PR3。

## 触发条件

全部满足：
1. `current > reference_high × (1 + breakout_margin)` (默认 margin=0.005)
2. `volume_ratio is None OR volume_ratio ≥ vol_ratio_min` (默认 1.2)
3. `symbol ∉ journal open` (`open_symbols` 过滤)
4. `watchlist.asof_date` 在 `max_age_days=5` 内

## 验收

- `pytest tests/intraday/`：**42 PASS** (28 既有 + 14 新增：7 breakout trigger + 5 watchlist roundtrip + 2 cfg)
- `pytest tests/`：**357 PASS** (无 regression)
- dry-run smoke：synthetic watchlist 验证 `breakout alerts: 0 (watchlist asof=2026-06-09, n_cand=1)` — 路径通畅，仅本地 akshare 代理拦截不出真 alert

## Backstop 5 条全过

- #1 17 条证伪：不调 yaml ✓
- #2 双窗口 8y：不改 yaml ✓
- #3 实盘 < 30 笔：不撬 frontier ✓
- #4 PM 决策权：仅推送"可考虑"，0 自动下单 ✓
- #5 采集 ≠ alpha：alert ≠ decision ✓

## 不动

- alembic / alerts_sent schema
- yaml 策略阈值 / weights / factors
- daily 决策权（T+1 是否真买仍是人工）
- backtest / journal

## PR

- PR2: https://github.com/Tanglaoye-future/quant_system/pull/22 (base = PR1 branch)
- spec: `docs/specs/pr2_intraday_watchlist_breakout.md`
- 前置: PR1 #21 (pr1/intraday-5min-breach)

## PR3 预告

- zhuang 候选股 watchlist (盘中异动 — 量比/拉升)
- 前端 dashboard 30s/1min 自动刷新持仓现价 + 浮盈

## 关联

- [[session_2026_06_09_realtime_data_intraday_5min]] — PR1，本 PR2 续作
- [[session_2026_06_07_pr5_intraday_telegram]] — PR5 母体
- [[session_2026_06_08_self_learning_pipeline]] — 5 条 backstop 来源
- [[feedback_harness_first_pr_split]] — 每 PR 独立 spec + 单测 + 验收门

**Why**: PR2 是用户"盘中实时监控买入点"诉求的核心交付件。watchlist 抽象解耦了 daily 决策（基本面 alpha）与 intraday execution timing（盘中突破），后续可扩 zhuang/HK/options。

**How to apply**: 任何"daily 输出 → intraday 消费"类需求都走 watchlist 模式：daily 写一个 JSON state，intraday 读 + evaluate 纯函数，主脚本编排 I/O 推送 + dedup。不要把决策逻辑直接耦合进 intraday 主脚本。
