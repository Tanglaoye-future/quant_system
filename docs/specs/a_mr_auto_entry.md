# Spec — A_mr auto-entry 闭环（M1）

## 背景

v5 部署计划（[[deployment_plan_2026-05]]）A_mr 配比 10%，但 `daily_equity.py` 对 `kind=mean_reversion` 路径明文 "暂不支持自动开仓，请手动处理" (L384-386)。

后果：实盘启动 (2026-05-22) 以来 A_mr **0 仓位**，10% 资金从未真正部署 — v5 的多 sleeve hedge 设计跑了 60% 的腿（A_mom + zhuang）。

## 改动范围

| 文件 | 改动 |
|---|---|
| `scripts/daily/daily_equity.py` | 去掉 L384-386 `elif args.kind == "mean_reversion"` block；`list_open(market=, strategy=)` 加 strategy filter（A_mom / A_mr / HK_mom 三 sleeve 不互挤 slot） |
| `tests/equity_factor/test_a_mr_auto_entry.py` | 新 case：mean_reversion path 走通 hits → open_trade，A_mr 持仓与 A_mom 隔离 |

## 不做（Backstop 严守）

- ❌ **不改 `MeanReversionStrategy.screen()` 的 alpha 逻辑**（Backstop #1: A_mr 4 路径全 falsified —— v1/v2/v6 grid/regime overlay。本 PR 不撬 frontier）
- ❌ 不改 yaml 因子权重 / entry threshold（Backstop #2: 不动双窗口验证过的参数）
- ❌ 不加 sector cap / 新 filter（Backstop #5: 0 新计算）
- ❌ 不改 A_mom / HK_mom 路径（仅 mean_reversion 入场闭环 + strategy filter 复用）

## list_open 隔离决策（重要）

- **sleeve 内 same symbol 不重开**：`list_open(strategy=eff_strategy)` filter → A_mr 自己不会同时持有两个 601939
- **跨 sleeve 允许 same symbol**：A_mr 可以入场 601939 即使 A_mom 已持有 — v5 设计是分账户, 不block; PM 视情况手工处理
- 现状（无 filter）会让 A_mr 跑时把 A_mom 4 仓视为"占用 slot"，max_positions=6 时 A_mr 只剩 2 slot；本 PR 修复

## 验收

- pytest tests/ 不回归（base 313）
- A_mr daily 跑时不再打印 "暂不支持自动开仓"，转而走 open_trade
- A_mr 信号触发时 `journal_trades.strategy='mean_reversion'` 落地，与 A_mom 完全隔离
- 既有 A_mom + HK_mom path 行为零变化（list_open filter 是新约束, 不挤旧 sleeve）

## Ops（合并后）

- 用户决定何时启用：默认 daily 跑 (`./deploy/run_daily.sh`) 会调 `daily_equity --strategy mean_reversion`，merge 后立即生效
- 真要等条件成熟再上：A_mr 入场需要先 yaml 改 `markets.a_share.mean_reversion.enabled=true` 类配置（如有）；若 yaml 已 enable 则本 PR merge 即生效

## 关联

- [[deployment_plan_2026-05]] — v5 10% A_mr 配比
- [[a_mr_rebuild_v6_grid_2026-05]] — A_mr v1/v6 grid 证伪（不撬 frontier 的边界）
- [[a_mr_v2_falsified_2026-05]] — A_mr v2 buffer/slope 证伪
- [[project_live_entry_diagnosis_2026-05]] — A_mr by design 不 auto-entry 是 deployment gap
