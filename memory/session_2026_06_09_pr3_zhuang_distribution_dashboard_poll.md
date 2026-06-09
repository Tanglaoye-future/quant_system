---
name: session-2026-06-09-pr3-zhuang-distribution-dashboard-poll
description: PR3 of 3 (intraday 实时化收尾) — zhuang 庄股盘中派发预警 + 前端 dashboard 60s auto-poll; spot_em 调用统一 (持仓+候选共用 quote_map); 5 条 backstop 全过; 0 自动平仓
metadata:
  type: project
---

# 2026-06-09 Session — PR3 zhuang 派发预警 + dashboard auto-poll

接续 [[session_2026_06_09_pr2_watchlist_breakout]] (PR2)。3 PR 中 PR3，intraday 实时化 harness 收尾。

## 范围

1. **`zhuang_distribution_warning`** (warning)：持仓 zhuang 股盘中今日大涨 ≥ 4% + 量比 ≥ 2.0 → 推送 "可能进入派发期, 考虑减仓"。永不自动平仓 (Backstop #4)。
2. **PositionSnapshot 扩**：加 `volume_ratio` / `day_change_pct` Optional 字段。现有 alert 不读，零回归。
3. **spot_em 调用统一**：`fetch_realtime_quote_with_vol_ratio_a_share` 扩 `change_pct`；持仓 + 候选共用一次 quote_map (减半 API)。
4. **前端 dashboard auto-poll**：`useReportData` 加 `pollIntervalMs` 默认 60s；`document.visibilityState !== 'visible'` 时清 interval；可见时立即 fetch + 重启。

## 关键设计决策

- **不用 "5min 涨幅" 维度**：用户原始描述 "5min 内涨幅 > 2%"。要持久化跨周期内存状态、增加复杂度；替换为 spot_em '涨跌幅'（今日累计）→ 物理意义更稳：大涨+放量 = 派发概率高。
- **量比 None 保守降级**：缺失字段仍发 alert（message 显示 `量比 N/A`）；防止 akshare 接口偶发字段丢失误判。
- **PositionSnapshot 字段 Optional**：现有持仓 alert（PR1/PR2）不读，零破坏。
- **dedup 沿用 once-per-day**：alerts_sent UNIQUE 不变 → 无 alembic migration。
- **One spot_em call**：从 PR1 简单 price fetch 切到 PR2 quote fetch（扩字段后）；持仓 + 候选共用 quote_map，run_once 中 spot_em 调用 2→1。
- **前端 polling 60s + visibility 守护**：balance UX vs 后端负载；tab 隐藏 0 流量；in-flight ref 防 race condition 叠加 fetch。
- **不写 React 单测**：前端无 vitest 框架（仅 frontend/tests/report/ Python 集成测试）。引入 vitest 是独立 PR scope。`npm run build` 验 TS compile pass。

## 触发条件

`evaluate_alerts` 内部判定，全部满足才出 event：
1. `strategy_name ∈ cfg.zhuang_strategies` (默认 `["zhuang"]`)
2. `day_change_pct ≥ 0.04` (4%)
3. `volume_ratio ≥ 2.0` OR `volume_ratio is None`

## 验收

- `pytest tests/intraday/`：**50 PASS** (42 既有 + 8 zhuang_distribution)
- `pytest tests/`：**365 PASS** (无 regression)
- `npm run build`：7 pre-existing TS errors (verbatimModuleSyntax + 旧 cell schema); stash my changes 后同样 7 个，**PR3 引入 0 个新错误**
- dry-run smoke：统一 quote 单次失败 (本地代理) → 优雅降级 (从 PR2 的 2 次 fetch 降到 1 次)

## Backstop 5 条全过

- #1 17 条证伪：不调 yaml ✓
- #2 双窗口 8y：不改 yaml ✓
- #3 实盘 < 30 笔：不撬 frontier ✓
- #4 PM 决策权：仅推送"考虑减仓"，0 自动平仓 ✓
- #5 采集 ≠ alpha：alert ≠ decision ✓

## 不动

- alembic / alerts_sent schema
- yaml 策略阈值 / 5 因子 / zhuang accumulation 阈值
- daily 决策 / backtest / journal

## 3 PR 全套交付

| PR | merged? | 内容 |
|---|---|---|
| PR1 #21 | 待 | 5min poll + break_stop_loss + break_ma60 |
| PR2 #22 | 待 (base=PR1) | daily watchlist + 候选股盘中突破入场 |
| **PR3 #23** | 待 (base=PR2) | zhuang 派发预警 + dashboard auto-poll |

链式 base：PR2→PR1→main，PR3→PR2→PR1→main。合并顺序应为 PR1→PR2→PR3 (GitHub 在 base PR merge 后自动改 PR3 base 到 main)。

## 用户启用步骤 (3 PR 全 merge 后)

```bash
# 1. 跑一次 daily (产 watchlist)
./deploy/run_daily.sh --no-options

# 2. 后台跑 intraday loop (5min, 含持仓 + 候选 + zhuang + portfolio 全套)
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
nohup venv/bin/python scripts/intraday/intraday_risk_check.py --loop \
    > logs/intraday.log 2>&1 &

# 3. 起前端 dev / 部署 (dashboard 60s 自动刷新)
cd frontend && npm run dev
```

## 后续 (out of this harness, 用户决定)

- 30s/15s 更激进 polling (需评估 spot_em 限流)
- WebSocket / SSE 替代 polling (架构升级独立 PR)
- HK 量比数据源接入 (付费 L1)
- zhuang sleeve 5min 涨幅维度 (持久化跨周期状态独立 PR)
- 前端 vitest 引入 (独立 PR)

## 关联

- [[session_2026_06_09_pr2_watchlist_breakout]] — PR2，本 PR3 续作
- [[session_2026_06_09_realtime_data_intraday_5min]] — PR1，整个 harness 起点
- [[session_2026_06_07_pr5_intraday_telegram]] — PR5 母体
- [[session_2026_06_08_self_learning_pipeline]] — 5 条 backstop 来源
- [[capitulation_strategy_falsified_2026-06]] — 第 16 条证伪 (execution alpha 区分 — 本 PR alert ≠ entry trigger 严守边界)
- [[feedback_harness_first_pr_split]] — 3 PR 全程遵守 spec-first

**Why**: PR3 收尾意味着用户"实时数据 + 分钟监控"诉求的整个 3 PR harness 交付完毕。zhuang 派发预警是 zhuang sleeve 实盘第一次落地的盘中告警通道（PR1/PR2 主要服务 equity_factor sleeve）。dashboard polling 让用户**不用刷新页面就能看到盘中变化**——核心痛点彻底解决。

**How to apply**:
- 用户再提 "盘中告警" 类需求 → 复用 `evaluate_alerts` + AlertEvent 模式；新增 alert_type 不破坏既有
- 任何 spot_em 字段扩展走 `fetch_realtime_quote_with_vol_ratio_a_share` 统一 fetch；不再单独加 fetch fn
- 前端"实时 X"类需求 → 复用 `useReportData` polling 模式（visibility 守护 + in-flight ref）
- zhuang sleeve 新 alert / signal → 复用 `strategy_name in cfg.zhuang_strategies` 过滤模式
