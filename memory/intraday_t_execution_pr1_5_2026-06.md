---
name: intraday-t-execution-pr1-5-2026-06
description: 2026-06-14/15 北极星支柱 3 后半段日内做 T 执行层 spec→code 5 PR 全链路落地 — A 股 advisory only / 3 层综合触发 (价格网格+VWAP+量价) / 25 case 测试 / yaml disabled 默认 noop / API + 前端组件 / 6 条不变量代码层强制
metadata:
  type: project
---

# 持仓中日内做 T 执行层 PR1-5 — 北极星支柱 3 闭环（2026-06-14/15）

## 触发

2026-06-14 北极星 4 根支柱审计后，支柱 3 = 持仓中日内做 T+0 + 实时风控；实时风控已落，**日内做 T 执行是零代码最大缺口**。用户决策"按计划做"5 PR 一次性落地。

## 5 PR 全链路 (harness-first)

| PR | 内容 | 文件 |
|---|---|---|
| **PR1** | spec + 25 case 红灯测试 | `docs/specs/intraday_t_execution_a_share.md`, `tests/intraday/test_t_signals.py` |
| **PR2** | `evaluate_t_signals` 纯函数 + `PositionSnapshot.vwap_today` 字段 → 25/25 绿 | `src/quant_system/intraday/core.py` |
| **PR3** | `config/intraday.yaml::t_signals` 段 + `TSignalConfig.from_yaml_dict` + 调度脚本 5min 轮询 | `config/intraday.yaml`, `scripts/intraday/intraday_t_signals.py` |
| **PR4** | alerts_sent 文档扩 (alert_type String(32) 无 enum, alembic 不需要); Telegram 集成已在 PR3 完成 | `src/quant_system/db/models.py` docstring |
| **PR5** | API endpoint `/api/report/t_signals` + `TSignalCard.tsx` 前端组件接入 DashboardPage | `src/quant_system/report/api/routes.py`, `frontend/src/components/TSignalCard.tsx`, `frontend/src/api/client.ts`, `frontend/src/hooks/useReportData.ts`, `frontend/src/pages/DashboardPage.tsx`, `frontend/src/App.tsx`, `frontend/src/types/index.ts` |

405/405 pytest 全绿。TypeScript 编译过。

## 设计 — 3 层综合触发

| 层 | 作用 | 默认阈值 |
|---|---|---|
| §3.1 价格网格 base | 浮盈 +5% 触发 SELL；浮盈 [+2%,+5%) 且当日已有 SELL → BUY；浮亏 ≤ -3% 全禁 | `qty_ratio_base=0.5` |
| §3.2 VWAP 偏离 boost | 价 > VWAP×1.02 → SELL qty +0.2；价 < VWAP×0.985 → BUY qty +0.2 | `vwap_qty_ratio_boost=0.2` |
| §3.3 量价 anti-distribution | 放量上涨 (day_change ≥ 4% + vol_ratio ≥ 2) → SELL qty ×0.7；缩量回调 (≤ -2% + ≤ 0.7) → BUY qty ×1.3 | factor 0.7 / 1.3 |
| clamp | qty ∈ [0.2, 0.7]，永不卖光底仓也永不超 70% 调仓 | min 0.2 / max 0.7 |

合成顺序：base → VWAP add → vol_price multiply → clamp。confidence = active_layers (3 high / 2 medium / 1 low)。

## 6 条不变量（spec §14 强制 + 代码层验证）

1. **当日净持仓量永不变** — BUY 必须 sent_today 有 SELL 记录（无前置 SELL 即使 unrealized 在 BUY 区间也跳过）
2. **qty_ratio ∈ [0.2, 0.7]** — `max(min, min(max, qty))` 兜底
3. **不改 stop_loss / take_profit** — 函数只读 PositionSnapshot 不回写
4. **break_stop_loss 触发后 T 全面禁用** — sent_today 含 `break_stop_loss` → continue
5. **advisory only** — 函数纯返事件 list，IO 在调度脚本，不下单
6. **strategy 白名单** — zhuang / mean_reversion / non-a_share 直接 skip

每条都有专属测试 case。

## Backstop 全过

- #1 18 条证伪墙：T 是执行层不是 alpha 信号源，不撞 [[tp_runner_sweep_falsified_2026-06]] 或 momentum/regime 类 ✓
- #2 双窗口同向 PASS：advisory 阶段不撬 yaml 不动回测 ✓
- #3 实盘 <30 笔不撬 frontier：不改 5 腿配比 / 组合权重 ✓
- #4 PM 决策权：advisory only, Telegram 推送人工下单 ✓
- #5 采集 vs alpha 分离：T 信号独立 alerts_sent `t_signal_sell` / `t_signal_buy` enum，不污染 entry_features/exit_features ✓

## 数据流（PR3 调度脚本）

```
journal.list_open()
  → 过滤 (market=a_share, strategy in cfg.strategies)
  → spot_em 一次拉 (price + 量比 + 涨跌幅)
  → 1min K 累计 VWAP (fail-soft None)
  → PositionSnapshot list
  → alerts_sent 当日 query → sent_today dict
  → evaluate_t_signals (纯函数)
  → TSignalEvent list
    → Telegram send (失败 stdout fallback)
    → alerts_sent INSERT (payload JSONB 含 side/qty/reason/confidence)
```

## 启用步骤（用户授权后）

1. 设环境变量 `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`（PR5 已有）
2. `config/intraday.yaml::t_signals.enabled` 改 `true`
3. `nohup venv/bin/python scripts/intraday/intraday_t_signals.py --loop &`
4. dashboard 自动显示 TSignalCard（仅当 today.length + history.length > 0）

不启用就保持 yaml `enabled: false`：调度脚本 dry-run 验证 `t_signals disabled in yaml; noop`，前端 0 信号不显示卡片。**零行为差异**。

## 默认参数依据（不是 alpha 来源是合理范围）

| 参数 | 默认 | 理由 |
|---|---|---|
| sell_unrealized_pct_min | 5% | A 股 30 天底仓持有期内 5% 浮盈频次约每 3-5 天一次，与 1 卖/日上限匹配 |
| buy_unrealized_pct_min | 2% | 卖后回买阈值留 3pp 缓冲避免高频反复 |
| no_t_unrealized_pct_max | -3% | A 股 momentum 止损 ATR×1.5 平均 -5% 区间，-3% 留 2pp 缓冲不与止损路径打架 |
| qty_ratio_base | 50% | 永远保留底仓的 50% 防"卖飞" |
| qty_ratio clamp | [20%, 70%] | 极端调整后仍留 ≥ 30% 底仓 |
| VWAP premium/discount | 2% / 1.5% | A 股日内 VWAP 偏离 2%+ 属强信号 |
| vol_price suppress | day_change ≥4% + vr ≥2 → ×0.7 | 防误杀拉升初期的真趋势 |
| max 1/day SELL+BUY | 单日合规上限 | A 股当日净持仓量不变 + 防过度调仓 |

参数本身不撬 alpha，**advisory 阶段 90 天后看 retrospective 报表（PR6+）再 PM 决策是否调**。

## 未做（明文 out-of-scope）

- auto-execute（PR7+ 实盘验证 6+ 月 alpha 显著后才考虑接券商 API）
- HK / US 扩展（PR1 only A 股；HK 实盘账户未开通；US baseline 负 Sharpe 不上实盘）
- T 信号 retrospective 报表（PR6，等实盘 ≥30 笔 closed 后）
- entry_features 加 t_signal_count（pollute 因子层，spec §11 反对）
- options BCS T 信号（schema 不同，spec §11 反对）

## 关联

- [[project_north_star]] 支柱 3 后半段 — 本 PR 落实
- `docs/specs/intraday_t_execution_a_share.md` — 14 段完整 spec
- [[session_2026_06_07_pr5_intraday_telegram]] — Telegram + alerts_sent 复用模板
- [[session_2026_06_06_zhuang_risk_parity]] — PositionSnapshot 扩展模板
- [[tp_runner_sweep_falsified_2026-06]] — 出场层 alpha 饱和 → 增量在 T 执行层（本 PR 闭环）
- [[zhuang_deprecated_2026-06]] — strategy 白名单 zhuang skip 来源
- [[feedback_harness_first_pr_split]] — 5 PR 拆分纪律

**Why**: 北极星 4 根支柱审计后支柱 3 后半段是项目最大代码缺口；一次性 5 PR 闭环让"持仓 30 天底仓 + 日内 1 卖 1 买锁利回买"的 advisory 工作流可启用，为后续实盘验证 alpha 留下纯采集数据。

**How to apply**: 任何"改 T 信号阈值 / 加新 signal 层 / 扩 HK/US / 接 auto-execute"类提议，先指本 memory 6 条不变量 + Backstop 5 条；任何不满足的拒。advisory ≥ 90 天 + ≥ 30 笔 closed 前不撬阈值。
