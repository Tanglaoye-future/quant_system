---
name: cb-double-low-pr10-intraday-risk-2026-06
description: PR10 — CB sleeve 实时风控接 intraday_risk_check (close<85 + 强赎临近 ≤30d 推 Telegram); 不实时算 dual_low_score (慢信号 PR9 daily 覆盖, 实时拉 premium 成本不划算); 复用 AlertEvent + alerts_sent + Telegram 通道, 不重复造管道
metadata:
  type: project
---

# PR10 — CB sleeve 实时风控

**日期**: 2026-06-17
**前置**: [[cb-double-low-pr9-rebalance-signal-2026-06]] schema + signal 接通
**Why**: 北极星支柱 3 = 持仓中实时风控 + (日内做 T+0). CB 在 risk-parity 豁免下不做 T+0, 但实时风控告警仍是支柱 3 硬需求. PR8/PR9 已通"schema + daily signal", PR10 补"实时告警"最后一块.

## PR10 scope (减法决策)

**做的**:
- `cb_break_stop_loss` — close < stop_loss_close (85) → critical (债底信号失守)
- `cb_redeem_imminent` — last_trading_date ≤ N (30) 天 → critical (强赎临近, 避免强赎价 ~100 损失)

**不做的** (留 PR11+ 或不做):
- `cb_dual_low_exit` (score > 180): 慢信号, [[cb-double-low-pr9-rebalance-signal-2026-06]] daily rebalance signal 已覆盖. 实时算 conversion_premium_rate 需要 panel value_analysis 每 code 1 次 API (~10 min/全市场), cost/value 不划算.
- portfolio 层 (unrealized_floor / peak_drawdown): 需要 CB current mv 算法, 留 PR11+ 接 spot 全市场汇总.
- 日内执行 (T+0): 北极星 2026-06-15 risk-parity 豁免明文不做. 告警 only "考虑减仓" advisory (与 zhuang_distribution_warning 同 Backstop #4).

## 关键设计 — 共享管道 + sleeve 独立 evaluation 模块

### 共享部分 (不重复造)
- `AlertEvent` dataclass — `quant_system.intraday.core.AlertEvent`
- `alerts_sent` 表 + UNIQUE (asof_date, strategy_name, symbol, alert_type) 去重
- Telegram channel + `TelegramSender`
- trading window 判定 (`is_in_trading_window`) — CB 与 A 股同窗口

### CB 独立部分 (不塞进 PositionSnapshot)
- `CBPositionSnapshot` (bond_code / bond_name / current_close / redeem_last_trading_date)
- `CBIntradayConfig`
- `evaluate_cb_alerts()` 纯函数评估
- `fetch_cb_realtime_close()` akshare bond_zh_hs_cov_spot 拉全市场 spot
- `build_cb_position_snapshots()` journal rows + spot + redemption → snapshots

**为什么不复用 PositionSnapshot**: equity 语义 (entry_price/stop_loss/take_profit/ma_long/vol_ratio/day_change_pct/vwap_today) 与 CB 不重合, 硬塞 → 字段膨胀且语义错位 (CB 没 take_profit, "stop_loss" 是 close 绝对位 85 而非相对入场价).

## stop_loss_close 单源

`config/cb_double_low.yaml` strategy.stop_loss_close (PR7 落地 85.0) 是唯一定义.
`config/intraday.yaml` cb_double_low 不重复定义, 而是 `CBIntradayConfig.from_yaml_dict` 接 cb_strat_yaml 参数, 自动取 cb_double_low.yaml 的值.

**Why**: PM 改阈值时只改一处, 避免 daily 出场规则 vs intraday 告警阈值不一致 (撞 self_learning Backstop #5 类型问题).

## fail-soft

- intraday yaml 缺 cb_double_low section → 不启动 (与 enabled=false 等价)
- journal DB 挂 → 整体 intraday 早就挂了 (CB 独立失败也无意义)
- akshare spot 挂 → log warn + 跳过 CB 评估 (不阻断 equity)
- redemption 拉失败 → log warn + 仅评估 stop_loss (不阻断)

CB 评估整体 try/except 兜底, 任何环节挂都不阻断 equity 评估 (主流程不变).

## 文件清单

| 文件 | 内容 |
|---|---|
| `src/quant_system/strategies/cb_double_low/risk/__init__.py` | 新 package (空) |
| `src/quant_system/strategies/cb_double_low/risk/intraday.py` | CBPositionSnapshot + CBIntradayConfig + evaluate_cb_alerts + fetch_cb_realtime_close + build_cb_position_snapshots |
| `config/intraday.yaml` | 加 cb_double_low section (enabled=true / poll 15 min / redeem 30d) |
| `scripts/intraday/intraday_risk_check.py` | import CB + 加 `_evaluate_cb_risk(journal, asof)` helper + run_once 末尾 `events.extend(cb_events)` |
| `tests/cb_double_low/test_intraday_risk.py` | 14 case: config 单源 / 4 阈值 case (break/redeem/both/none) / 4 snapshot builder case (filter market / spot miss / notes 优先 / redemption attach) |
| `memory/cb_double_low_pr10_intraday_risk_2026-06.md` | 本文件 |

## 验收

| 命令 | 结果 |
|---|---|
| `pytest tests/cb_double_low/test_intraday_risk.py -v` | **14/14 PASS** |
| `pytest tests/cb_double_low/ tests/db/ tests/equity_factor/test_journal.py tests/intraday/ -q` | **178/178 PASS** 全 CB + db + equity_journal + intraday 无回归 |
| `python scripts/intraday/intraday_risk_check.py --dry-run` | CB advisory_only 期 holdings=0 → "CB intraday: no open holdings, skip"; equity 评估不受影响 |

## 实盘 UX 时间线

- 现在 (2026-06-17): CB holdings = 0, intraday CB 分支静默 noop
- 7/1 PM 月初首次 rebalance 录 20 笔 journal_trades (market=cb_a, strategy=cb_double_low)
- 7/2 起 intraday 每 15 min 一次评估 20 只 CB 的 close + 强赎日期
- 任一只 close 击穿 85 或强赎临近 30d → Telegram 立即推送, alerts_sent 去重当日不重发

## 北极星支柱进度更新

| 支柱 | 状态 |
|---|---|
| 1 债性条款选标的 | ✅ |
| 2 risk-parity 豁免 | ✅ |
| **3 实时风控** | ✅ → PR8 schema + PR9 daily signal + **PR10 实时告警 close<85 + 强赎临近** 三连闭环 |
| 3 日内做 T+0 (CB) | n/a (risk-parity 豁免) |
| 4 retrospective | ⏳ → PR11/PR12 待做 |

CB sleeve 在支柱 3 上已达到与 equity_factor a_share 同等水位 (差 T+0, 但 CB 豁免). 实盘等 7 月首次 rebalance 验证.

## "≥ 90 天 + ≥ 30 笔不撬" backstop 兼容性

PR10 **未撬任何参数** (n_entry / exit_threshold / stop_loss / sizing / weight 全部不动). 唯一新增配置 `redeem_within_days=30` 是新维度 (PR7 之前不存在), 不算撬已有参数. 与 backstop 不冲突.

## 关联
- [[cb-double-low-pr8-journal-portfolio-2026-06]] schema 前置
- [[cb-double-low-pr9-rebalance-signal-2026-06]] daily signal 前置 (覆盖 dual_low_score 慢出场)
- [[project-north-star]] 支柱 3 实时风控完整闭环
- [[session_2026_06_07_pr5_intraday_telegram]] equity 的 intraday 通道 baseline
- [[session_2026_06_04_realtime_risk_v1]] intraday spec 起源
