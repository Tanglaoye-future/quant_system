---
name: session-2026-06-04-realtime-risk-v1
description: 实盘风控 v1 落地 — 用户实盘"大幅回撤"焦虑触发的 audit 与端到端修补；safety margin (Step 1) + 组合层 alerts (Step 2) 全链路接入；max DD + 盘中实时 (Step 3) 推迟；4 commit
metadata:
  type: project
---

# 2026-06-04 Session 收工 — 实盘风控 v1

## 触发上下文（不要忘）

用户首次正式实盘（4 只 A_mom 银行股，总成本 ≈ 79.7 万），盘后向我反馈 **"现在这么大幅度的回撤，很多持仓都是亏损状态，为什么没有触发卖出信号或者给一个继续持仓原因，整个程序有做到实时监控已有持仓吗？"**

诊断后系统层面真相：
- 06-04 收盘 A_mom 组合层浮盈 **+0.30%**，最差单只 -2.49% —— 系统数据本身不大回撤
- 但 4 只里 **3 只距离止损只剩 0.16-0.45%**：601939 +0.30% / 600919 +0.45% / 601838 +0.16%；只有 601066 (+5.69%) 离止损 +2.09% 安全
- 用户的"贴线焦虑"是对的，**系统也是对的**；**问题是 daily report 没暴露 safety margin** → 操盘人无法肉眼判断"再跌多少就触发" → 产生"系统沉默 = 一切正常"的误判

→ 这次落地的不是策略改动，是 **observability + 组合层 alert 通道**。

## 架构现状（audit 结论；下次别再确认一次）

**调度**：
- daily 是 **EOD 批跑**，不是盘中实时。`RiskMonitor.daily_check` 一天 1 次。
- launchd 因 macOS TCC blocked，现在 **手动跑** `./deploy/run_daily.sh --no-options`（详见 [[session_2026_05_27]]）。

**个股层出场规则**（`signals.py:692-787` `exit_signal_from_enriched`，按优先级）：
1. `close ≤ trailing_stop` (entry - 2×ATR，只上调) → `trailing_stop`
2. `close < MA60` → `break_ma60`
3. `close ≥ entry + 4×ATR` → `take_profit` (或 partial / runner promote)
4. `RSI ≥ 80` → `overbought`
5. `持有 ≥ 60 天` → `time_stop`
6. 都不触发 → HOLD，`reason="持有"`

**组合层风控**：`monitor.py:14-15` 明文 "行业集中度 / VaR / Beta 暂不实现"。本次之前**只算不停**：PortfolioRisk 算 max_single_weight / n_at_risk / worst_drawdown_pct 但没阈值、没动作。

## 这次落地（4 commit, 已 push origin/main）

`e7e7e32` **fix(frontend): vite proxy 修回 8000** — `3ce0f05` 把 proxy 误带成 `127.0.0.1:8002`（commit msg 没提，疑似本地排冲突临时改没回滚），dashboard 全 502；改回 `localhost:8000`，6 个真实端点验过。

`231cdab` **Step 1 CLI safety margin** — `PositionRisk` 加 `ma_long / dist_to_stop_pct / dist_to_ma_long_pct`；`daily_equity` 持有维持段每行追加 `(距 +X%) MA60 距 +Y%`；< 1% 加 `⚠ 临界`；段末 `⚠ N/M 只贴近触发线` 汇总。

`8288506` **Step 1 JSON + 前端** — `report_positions` JSON 加 5 字段（current_price / stop_loss / ma_long / dist_to_stop_pct / dist_to_ma_long_pct）；`QuantPosition` type 扩展；`positionColumns` 加「距止损」「距 MA60」两列，< 1% 红字 + ⚠；verify_dualwrite 4/4 一致。

`da83722` **Step 2 组合层 alerts** — 3 阈值，**alert-only 不自动平仓**（用户决策，AskUserQuestion 已问过）：
- `max_single_weight_pct`（建议 0.30，因当前 601066 = 26.3%）
- `unrealized_pnl_floor_pct`（建议 -0.05；账户层 stop alarm）
- `exit_signal_ratio_max`（建议 0.50；一半持仓同时 EXIT 时 panic 信号）

`PortfolioRisk.alerts: list[str]`；`daily_equity` 组合摘要 ⚠ 行；JSON `portfolio_alerts`；API `/report/quant` 合并多策略时加 `[<source>]` 前缀；前端 `StrategyCard` 红色 banner（按 sourceLabel filter）；yaml `portfolio_risk:` 段 **默认 enabled: false**（实盘 noop）；新增 `tests/equity_factor/test_portfolio_risk.py` 8 个契约测试。

**验证门**：pytest 93/93 / 短回测 2026-01..02 Sharpe +1.43 / DD -5.11% / Calmar +5.29 PASS / M0 audit PASS / 默认 OFF 时 daily 输出与 baseline 完全一致。

## 推迟的事（**别在没用户授权下自行启动**）

1. **`max_drawdown_pct`（真历史 peak DD）** — journal 当前只有个股层 snapshots，无 `portfolio_history` 表；用 `unrealized_pnl_floor_pct` 作账户层 stop alarm 兜底。yaml 已留 TODO 注释。下个 phase 加 `portfolio_history` 表后才能算真 peak。
2. **Step 3 盘中实时（intraday cron + 推送）** — 用户明确要等 Step 1/2 跑一段实盘体验后再决定要不要做。技术路径：N 分钟 cron 拉最新价比对 stop_loss，触发 email/Slack/桌面通知。**未授权前不要自启动。**
3. **个股出场规则不动** — 用户今天的"贴线"是 entry 后 2-13 天 ATR-stop 还没上移到舒服位置，属于策略 by design，不是 bug。

## 默认阈值依据（实盘当日数据驱动）

- `max_single_weight_pct: 0.30` ← 当前 A_mom 单只最大 26.3% (601066)，给 3.7% headroom
- `unrealized_pnl_floor_pct: -0.05` ← v5 deployment_plan 5-asset 历史 -7.94% DD ([[v5_efficient_frontier_2026-05]])，留单策略层 -5% 比较保守
- `exit_signal_ratio_max: 0.50` ← 一半持仓同时 EXIT 时市场已 panic，应当通知

用户上线时改 `config/equity_factor.yaml` 的 `portfolio_risk: enabled: true` 即可生效。

## 用户实盘状态（写入时点）

| symbol | 名 | entry | 当前止损 | 浮盈 | safety margin |
|---|---|---|---|---|---|
| 601939 | 建设银行 | 10.10 | 10.00 | -0.69% | 距止损 +0.30% / MA60 +4.21% |
| 601066 | 中信建投 | 23.72 | 24.55 ↑ | +5.69% | 距止损 +2.09% / MA60 +10.25% |
| 600919 | 江苏银行 | 11.39 | 11.19 | -1.32% | 距止损 +0.45% / MA60 +2.00% |
| 601838 | 成都银行 | 19.31 | 18.79 | -2.49% | 距止损 +0.16% / MA60 +4.80% ← 最危险 |

zhuang / HK_mom / A_mr / options 全 0 持仓。

## 关联

- [[frontend_single_pane_2026-06]] — phase 3 后 strategy HTML 报告已停产，dashboard JSON 唯一入口；本次扩展沿用同一架构（JSON → API → 前端 component）
- [[db_decouple_phase0_2026-05]] — Journal 走 Postgres（不是 SQLite），portfolio_history 表加在 PG side
- [[deployment_plan_2026-05]] — 5-asset 配比（v5 efficient frontier）；本次默认阈值与 v5 历史 DD 对齐
