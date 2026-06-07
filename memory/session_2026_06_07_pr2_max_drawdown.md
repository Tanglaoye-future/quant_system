---
name: session-2026-06-07-pr2-max-drawdown
description: PR2 of 持仓 v2 harness — peak DD 真历史 (portfolio_history) 接入 PortfolioRisk + alert + nested portfolio_summary JSON + 前端展示；含 9 case 测试；并行 agent 隔离失败 lesson
metadata:
  type: project
---

# 2026-06-07 Session — PR2 持仓 v2 harness: max_drawdown peak DD 全链路

接续 [[session_2026_06_07_pr1_portfolio_history]]。spec `docs/specs/position_v2_harness.md` §3。

## 范围

读 PR1 portfolio_history 表算真 peak DD → 接 PortfolioRisk + portfolio_drawdown_pct 阈值 → JSON nested portfolio_summary → 前端展示。
**不**改个股层 / **不**改 entry/exit 逻辑。默认 OFF（equity_factor enabled: false）零行为差异。

## 改动落地（branch `pr2/max-drawdown-compute`，未推 origin）

| 文件 | 单元 |
|---|---|
| `src/quant_system/strategies/equity_factor/risk/monitor.py` | `PortfolioRiskConfig` 加 `portfolio_drawdown_pct` + `drawdown_lookback_days`；`PortfolioRisk` 加 `peak_market_value` + `drawdown_from_peak_pct`；新 `compute_peak_drawdown` 纯函数；`_aggregate` 加 `history_market_values` kwarg + alert；`RiskMonitor._fetch_history_market_values` 查 DB |
| `src/quant_system/db/ingest.py` | `list_recent_portfolio_history_mvs` 查 portfolio_history 近 N 天 mv |
| `config/equity_factor.yaml` | `portfolio_drawdown_pct: -0.08` + `drawdown_lookback_days: 60`（enabled: false 不变） |
| `config/zhuang.yaml` | `portfolio_drawdown_pct: -0.10` + lookback 60（zhuang 已 enabled: true） |
| `scripts/daily/daily_equity.py` | JSON 加 nested `portfolio_summary`（含 peak DD 字段） |
| `scripts/daily/daily_zhuang.py` | inline 计算 peak DD（DB 不可达兜底）+ nested `portfolio_summary` |
| `scripts/daily/verify_dualwrite.py` | pop `portfolio_summary` 两策略（derived，不入 DB） |
| `frontend/src/types/index.ts` | 新 `PortfolioSummary` type；`QuantData`/`ZhuangData` 加可选字段 |
| `frontend/src/components/StrategyCard.tsx` | quant + zhuang 块加「组合层回撤 -X.XX% (peak ¥Y)」 |
| `tests/equity_factor/test_portfolio_risk.py` | 9 个 PR2 case（含 compute 纯函数 4 + alert 5） |

## 关键设计决策

### Equity proxy = market_value（spec §3.4）
系统不跟踪 cash 余额，peak DD 用 market_value 作 equity proxy。已知失真：开/平仓阶跃。兜底：`unrealized_pnl_floor_pct` 从 pnl 维度独立判定，不依赖 history。

### `_aggregate` 加 kwarg 不破契约
`history_market_values: Optional[list[float]] = None` 默认 None，旧测试零回归。daily_check 内查 DB；测试可直接传 list。

### enabled=false 跳查 DB
`_fetch_history_market_values` 早返 None；既省 DB 又保持「关掉就完全无副作用」契约。

### zhuang 走 inline（不复用 RiskMonitor）
daily_zhuang.py 现有 alerts 逻辑 inline 实现（不用 PortfolioRisk dataclass），PR2 沿用同模式：导入 `compute_peak_drawdown` + `list_recent_portfolio_history_mvs` 两个 pure 函数，try/except 兜底。架构演化到 zhuang 也走 RiskMonitor 时再统一。

## 验证门（全绿）

- `pytest tests/equity_factor/test_portfolio_risk.py` → 17/17 PASS（含 9 PR2 新增）
- `pytest tests/` → 236/236 PASS
- AST parse 6 个改动 .py OK
- `cd frontend && npx tsc --noEmit` → 0 错误
- 默认 OFF（QUANT_PG_DUALWRITE 关 / equity_factor enabled: false）字节级一致 baseline（仅 JSON 多 nested 字段，不影响 verify）
- verify_dualwrite 拓展 pop `portfolio_summary`（提前避免 06-05 假阳回归）

## 并行 agent 隔离失败 — Lesson 沉淀

**事件**：PR2 进行中同时 spawn PR3 + PR4 agent 用 `isolation: "worktree"`，agent worktree 位于 `.claude/worktrees/agent-<id>/`。但 agent 在主 workspace 写文件（pr3 改了 db/ingest.py + db/models.py + 等 6 个文件 + 创建 alembic migration + 前端组件；pr4 创建测试文件）。agent 自己的 worktree git status 是 clean。

**结论**：`isolation: "worktree"` 没真实切 agent 的 file ops cwd。**不能依赖**它隔离并行 agent 的 file 写。

**应对**：
1. agent 工作已备份 `/tmp/agent-work-pr3/` + `/tmp/agent-work-pr4/`，PR3/4 串行重做时可参考
2. 主 workspace 已 `git checkout HEAD --` revert 干净
3. 未来并行：要么真用独立 clone，要么只跑「读 + 报告」型 agent（Explore），写型一律主线串行
4. 后台 Bash（`run_in_background=true`）不受此问题影响，可继续用作 QA

## 实盘当前状态

- equity_factor `enabled: false` → daily 输出 `portfolio_summary` 有 n_positions/cost_basis 等，`drawdown_from_peak_pct` 仍 None（因 _fetch_history 跳过）
- zhuang `enabled: true` + PR1 起累积 history → 实际 dd 累积到 60d 后才有 alert 触发能力；前 60 天 peak 等于 current（dd≈0）
- 实盘上线 equity_factor 时改 `enabled: true` 即生效

## 推迟

- options 不接 portfolio_history（BCS 单独表 → PR3）
- intraday 真实时（→ PR5 待授权）
- `worst_drawdown_pct`（单只）语义保留，前端两栏并显「单只」+「组合」

## 关联

- [[session_2026_06_07_pr1_portfolio_history]] — PR1 portfolio_history 表基建
- [[feedback_harness_first_pr_split]] — 方法论（本 PR 第二个产物）
- `docs/specs/position_v2_harness.md` §3 — 验收契约
- [[session_2026_06_06_zhuang_risk_parity]] — v1 截止快照
