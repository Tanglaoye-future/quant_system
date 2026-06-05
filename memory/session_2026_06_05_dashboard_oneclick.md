---
name: session-2026-06-05-dashboard-oneclick
description: dashboard 一键跑 daily + 持仓表加止盈/距止盈 + MA60 列去前端 + 顺手修 daily API zombie + verify_dualwrite 回归；5 commit；接续 06-04 实盘风控 v1
metadata:
  type: project
---

# 2026-06-05 Session 收工 — dashboard one-click daily + 止盈视图

接续 [[session_2026_06_04_realtime_risk_v1]] 的实盘风控 v1。

## 改动落地（5 commit, 已 push origin/main）

| commit | 单元 |
|---|---|
| `7d0df44` | feat(daily+frontend): dashboard 一键跑 daily — POST /api/daily/run + 状态轮询按钮 |
| `f5e80f4` | feat(risk): 持仓表加止盈/距止盈 + 修 daily API zombie + verify 跳 portfolio_alerts |
| `77736d8` | refactor(frontend): 持仓表去掉「距 MA60」列 — 仅后端用于临界判定 |
| `6539240` | fix(frontend): 「黑框」实为自家日志面板自动展开 + Tailwind 位置漂位 |

## 关键能力 / 数据

### dashboard 一键跑 daily

之前每天手动 `./deploy/run_daily.sh --no-options`，现在 web 上点按钮即可。

- 后端 `src/quant_system/report/api/daily.py`：
  - `POST /api/daily/run` `{skip_options: bool}` → `subprocess.Popen` 非阻塞起 `run_daily.sh`，立即返回 `job_id`
  - `GET /api/daily/status` → idle / running / success / failed + log_tail 末 200 行
  - In-memory `_state` 状态机 (`process` 句柄保留)；用 `Popen.poll()` 检测退出（**不要用** `os.kill(pid, 0)`，对 zombie process 返 True，会卡 running 状态）
  - detach 三道保险：`nohup` + `preexec_fn` 走 fork+exec 路径 + `os.setsid()` + `SIGHUP IGN`
  - 并发保护：已在跑时 POST → 409
  - 安全 TODO：API 起在 `0.0.0.0:8000`（见 `deploy/start_api.sh`），LAN 任何机器可触发；本地单机开发可接受，公网部署前需 auth + 收紧 host
- 前端 `frontend/src/components/DailyRunButton.tsx`：
  - 按钮状态 idle/running/success/failed
  - 3s 轮询；running → 终态时回调 `onComplete` 自动刷 dashboard data
  - "查看日志" 悬浮面板用 **inline style** 锁定 `position:fixed / right:16 / bottom:16`（Tailwind `bottom-4` 被父元素 transform 重新定义 containing block，漂到右上）
  - **不**自动展开日志面板（用户希望后台静默跑，要看自己按"查看日志"）

### 持仓表加止盈 / 距止盈

公式 `take_profit = entry_price + atr_target_mult × ATR` (默认 `4×ATR`)，与 `exit_signal.take_profit` 路径同步。

- `monitor.PositionRisk` 加 `take_profit / dist_to_target_pct`
- `daily_check` 内 `enrich(px)` 一次拿当日 ATR
- CLI 持有维持段追加 `止盈 X.XX (距 +Y%)`
- JSON `report_positions` 加 2 字段
- 前端 `tableColumns` 加「距止盈」列（蓝色中性；止盈不参与 ⚠ 临界判定）
- `partial_exit / runner / regime filter` 状态当前不在 PG snapshots，monitor 沿用 base TP 路径显示；策略层真正 partial 后剩余目标不在本视图

### MA60 列前端隐藏

用户决策：MA60 距离对操盘人是噪音，只关心止损 + 止盈两个明确触发线。

- `tableColumns` 去掉「距 MA60」列
- 但保留：`PositionRisk.dist_to_ma_long_pct` 字段 + JSON 输出 + CLI 持有维持段 `MA60 距 +X%`（终端 operator 排查用）+ 临界 ⚠ 检测逻辑（`< 1%` 仍触发）

### 顺手修两个隐患

1. **daily API zombie**：原用 `os.kill(pid, 0)` 检测子进程死活，未 reap 的 zombie 仍返 True → daily 跑完 status 卡 running。改 `subprocess.Popen.poll()` 自动 reap + 准确 exit code。
2. **verify_dualwrite portfolio_alerts 假阳**：Step 2 (`da83722`) 加 `portfolio_alerts` 到 JSON 但未同步 DB schema → 每次 daily 真写就 MISMATCH。`alerts` 是 PortfolioRiskConfig 运行时 derived，本就不该入 DB；verify 在 quant kind 归一化时 `payload.pop("portfolio_alerts", None)`。
   - **回归 lesson**：Step 2 当时跑 verify 是用 06-04 旧 JSON（前端 Phase 3 之前的版本，没 alerts 字段）所以 4/4 一致；06-05 真写第一次才暴露。下次给 JSON 加 derived 字段要同步检查 verify_dualwrite。

## 用户实盘当前持仓快照 (2026-06-05, 与 06-04 一致)

| symbol | 名 | entry | 当前止损 | 浮盈 | safety margin | take_profit | 距止盈 |
|---|---|---|---|---|---|---|---|
| 601939 | 建设银行 | 10.10 | 10.00 | -0.69% | 距止损 +0.30% ⚠ | 10.76 | +7.28% |
| 601066 | 中信建投 | 23.72 | 24.55 ↑ | +5.69% | 距止损 +2.09% | 26.34 | +5.06% (最接近) |
| 600919 | 江苏银行 | 11.39 | 11.19 | -1.32% | 距止损 +0.45% ⚠ | 12.02 | +6.94% |
| 601838 | 成都银行 | 19.31 | 18.79 | -2.49% | 距止损 +0.16% ⚠ | 20.37 | +8.20% (最远) |

06-05 因 A 股仍交易中，daily 跑出来的"06-05"数据实际等于 06-04 收盘（盘中拉数据 cache 到上个交易日）。

## 推迟 / TODO

- `run_daily.sh` 加 `--asof <date>` 参数（当前 dashboard 按钮只能跑当天；要 backfill 必须 CLI 手动串）
- options toggle UI（当前硬编码 `--no-options`，要带 IBKR 需改 RunRequest）
- 真 `max_drawdown_pct`（接 portfolio_history 表，见 06-04 handoff）
- Step 3 盘中实时仍推迟，等用户 Step 1/2 实盘体验积累

## 关联

- [[session_2026_06_04_realtime_risk_v1]] — 实盘风控 v1（safety margin Step 1 + 组合层 alerts Step 2）
- [[frontend_single_pane_2026-06]] — JSON+API+前端组件为唯一新数据通道
- [[feedback_screenshot_first]] — 本次"黑框" misdiagnose 教训沉淀
- [[feedback_user_collab_style]] — 用户协作风格
