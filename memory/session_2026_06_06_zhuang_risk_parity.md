---
name: session-2026-06-06-zhuang-risk-parity
description: zhuang 持仓表与 equity_factor 风控 v1 字段对齐 — safety margin + 组合层 alerts 全链路;3 commit;沿用 06-04/06-05 JSON+API+前端架构
metadata:
  type: project
---

# 2026-06-06 Session 收工 — zhuang 持仓风控字段与 equity_factor 对齐

接续 [[session_2026_06_04_realtime_risk_v1]] + [[session_2026_06_05_dashboard_oneclick]]。
用户反馈"庄股策略也是只有推荐没有后续买入持仓的一切功能"——
查实是 zhuang 已有 ledger + 建仓闭环（[[project_live_entry_diagnosis_2026-05]]），
但**持仓表只有 5 列**（code/entry_date/hold_days/pnl/action），缺 safety margin / portfolio_alerts。

## 改动落地（3 commit, 已 push origin/main）

| commit | 单元 |
|---|---|
| `1ff760d` | feat(risk): zhuang 持仓 enrich + 组合层 alerts — 与 equity_factor 06-04 对齐 |
| `df66bd0` | chore(zhuang): portfolio_risk yaml 段 + verify_dualwrite 跳 portfolio_alerts |
| `8e7a6d9` | feat(frontend): zhuang 持仓表加距止损/距止盈 + 组合层 alerts banner |

## 关键能力 / 字段

### 持仓 safety margin（与 equity_factor 同公式）

`daily_zhuang.py` Step 1 风控段对每个 open trade 算：
- `stop_loss` = `tr["stop_loss_price"]` (ledger 已有) 或 `max(entry - atr_mult×ATR, entry × (1 - max_stop_pct))`
- `take_profit` = `tr["take_profit_price"]` 或 `entry × (1 + tp_pct)`
- `dist_to_stop_pct` = `(close - stop) / close`
- `dist_to_target_pct` = `(tp - close) / close`
- `current_price` = today_close, `entry_price` = ledger

**注意：zhuang 止损 STATIC** （check_exit_signal 不 trail），所以 ledger.stop_loss_price 就是今日有效止损。
若以后改 trailing 要同步更新。

CLI 持有维持段 = `止损 X.XX (距 +Y%)  止盈 X.XX (距 +Z%)  ⚠ 临界` + 段末 `⚠ N/M 只贴近止损`。
止盈不参与临界判定（接近止盈不是风险，蓝色中性）。

### 组合层 portfolio_alerts（3 阈值，alert-only 不自动平仓）

复用 equity_factor 06-04 决策（[[session_2026_06_04_realtime_risk_v1]]）。
yaml `portfolio_risk:` 默认 `enabled: false`，零行为差异。

阈值（zhuang 6y sleeve 历史驱动）：
- `max_single_weight_pct: 0.30` — tiered sizing 上限 6%×6 仓 = 36%，留 headroom
- `unrealized_pnl_floor_pct: -0.07` — zhuang 6y sleeve DD ≈ -7%（[[zhuang_overlay_combo4_2026-05]]）
- `exit_signal_ratio_max: 0.50` — 一半持仓同时 EXIT = panic

### 前端

- `ZhuangPosition` type 扩 6 字段（与 QuantPosition 同结构）
- `zhuangPositionColumns` 加「距止损 ⚠」「距止盈」2 列，复用 fmtMargin
- `StrategyCard` zhuang 块加红 banner（与 equity_factor 同款）

### verify_dualwrite 回归预防

zhuang ingest 用 catch-all payload（unknown 字段自动 round-trip），新字段无需 DB schema。
**但 `portfolio_alerts` 是 daily 运行时 derived 不入 DB**，verify 必须 pop 否则 MISMATCH。
06-05 quant 加 portfolio_alerts 时漏了这一步真写第一次才暴露；本次提前 pop。

## 验证门

- `pytest tests/zhuang/` → 33/33 PASS
- `pytest tests/` → 191/191 PASS
- daily_zhuang `--dry-run --no-write` → JSON shape 正确 `positions: [], portfolio_alerts: []`
- 合成 fake trade 走 enrich 数学：entry 10 / close 9.5 / stop 9.4 / tp 11 → dist_to_stop +1.05%, dist_to_target +15.79%, pnl -5%（全部正确）
- 前端 `tsc --noEmit` → 0 错误

## 当前 zhuang 实盘状态

`open_trades=0`（市场趋势门 sh.000905 close 10.92 < MA60 11.61 长期未达，never 建仓）。
有持仓后字段才会实际填充；今日 portfolio_alerts=[] 是因为 enabled: false。

## 推迟 / TODO

- 真 `max_drawdown_pct`：接 zhuang_portfolio_history 表（与 equity_factor 06-04 推迟同款），加上后才能算真 peak DD
- options 持仓字段对齐：BCS 结构上没有传统"持仓"概念（spread 而非 stock），用户范围 #1 已明确 zhuang only
- HK_mom / A_mr 也走 equity_factor 同 code path，自动继承
- 实盘上线时改 `enabled: true`（与 equity_factor 同款决策点）

## 关联

- [[session_2026_06_04_realtime_risk_v1]] — equity_factor 风控 v1（safety margin Step 1 + 组合层 alerts Step 2）
- [[session_2026_06_05_dashboard_oneclick]] — 一键 daily + 止盈视图；verify_dualwrite 回归 lesson 本次提前处理
- [[project_live_entry_diagnosis_2026-05]] — zhuang 独立 ledger + 建仓闭环（本次未动 ledger，只补 observability）
- [[frontend_single_pane_2026-06]] — JSON+API+前端组件为唯一新数据通道（本次延续）
- [[feedback_user_collab_style]] — 用户协作风格（yaml/实盘前 AskUserQuestion 本次走过）
