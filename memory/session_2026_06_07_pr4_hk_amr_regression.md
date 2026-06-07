---
name: session-2026-06-07-pr4-hk-amr-regression
description: PR4 of 持仓 v2 harness — HK_mom + A_mr 副腿持仓回归 e2e 契约测试, 锁定 06-04/05/06 v1 字段集合在副腿生效 + 三腿 JSON shape 一致; 8 case 全绿; 无 prod patch
metadata:
  type: project
---

# 2026-06-07 Session — PR4 持仓 v2 harness: HK_mom + A_mr 副腿持仓回归

接续 [[session_2026_06_07_pr3_options_positions]]。spec `docs/specs/position_v2_harness.md` §5。

## 范围

验证 06-04 → 06-06 三轮 v1 在 A_mom 主腿落地的字段（safety margin / take_profit / portfolio_alerts）在 HK_mom + A_mr 副腿同等生效，且三腿 JSON shape 完全一致。**纯测试 PR，零 prod patch**。

## 改动落地（branch `pr4/hk-mom-amr-regression`）

| 文件 | 单元 |
|---|---|
| `tests/equity_factor/test_position_v1_regression_secondary_legs.py` | 8 case 副腿回归 + 三腿 JSON shape 一致性 |
| `memory/session_2026_06_07_pr4_hk_amr_regression.md` | 本 session 记录 |
| `memory/MEMORY.md` | 索引 1 行 |

## 8 case 覆盖（spec §5.6）

| Case | 验证 |
|---|---|
| `test_hk_mom_position_has_dist_to_stop` | HK_mom 持仓 dist_to_stop_pct 非 None + 数学正确 |
| `test_hk_mom_position_has_take_profit` | HK_mom take_profit + dist_to_target_pct 非 None + 公式正确 |
| `test_hk_mom_portfolio_alerts_when_enabled` | HK_mom enabled=true 浮亏 -6% < 阈值 -5% → alerts 触发 |
| `test_a_mr_position_has_dist_to_stop` | A_mr 同款 |
| `test_a_mr_position_has_take_profit` | A_mr 同款 |
| `test_a_mr_portfolio_alerts_when_enabled` | A_mr 同款 alerts 命中 |
| `test_a_mr_uses_hedge_yaml_thresholds` | A_mr 当前与 A_mom 共享 portfolio_risk yaml 顶层节（spec §5.9 锁契约 + 留差异化 hook） |
| `test_json_schema_uniform_across_three_legs` | A_mom / HK_mom / A_mr 三腿 JSON `report_positions[i]` dict key set 必须相等 |

## 关键设计决策

### Fixture 走 `_aggregate` 直接喂 PositionRisk
spec §5.8 推荐两种 fixture 思路；选第二条（PositionRisk list + cfg 喂 `RiskMonitor._aggregate`）而不是 SQLite + Journal + daily_check 整 e2e。优势：
- 不依赖网络 / akshare cache / IBKR
- 跑 0.7 秒，快速 CI
- 锁定真核心契约（字段集合 + alert 触发），不被数据噪声干扰

### `_position_to_json` 与 production 同步
helper 函数复刻 `scripts/daily/daily_equity.py:413-430` 的字段拼装逻辑。任一方加 / 漏字段而另一方不跟进 → `test_json_schema_uniform_across_three_legs` 立刻爆 → 防 v1 落地后副腿被静默漏掉。

### A_mr yaml 差异化暂不做（spec §5.9 锁契约）
当前 portfolio_risk 节在 yaml 顶层，**跨策略共享**。如未来想差异化（A_mr hedge 性质允许更宽 floor），方式是把 portfolio_risk 节下沉到 deployments[strategy][market] 二维 + daily_equity:114 改读路径。本 PR 不动 prod，仅锁定"共享 default"契约。

## 复用 PR2 失败 agent 备份

agent 在 PR2 session 跑 PR4 时已完成测试设计 + 写完代码，备份在 `/tmp/agent-work-pr4/`。审核后 **直接 cp 采纳**（零修改），8 case 一开始就绿。证明 agent 在「无 file-write 冲突的纯测试 PR」上能交付高质量产物，但 PR2 session 中 worktree 隔离失败让这价值被冷藏；本 PR 是手术式打捞。

## 验证门（全绿）

- `pytest tests/equity_factor/test_position_v1_regression_secondary_legs.py` → 8/8 PASS
- `pytest tests/` → 260/260 PASS（PR3 后 252 + PR4 8）
- AST parse 测试文件 OK
- 默认 OFF 字节级一致 baseline（仅加测试文件，无 prod 改动）

## 推迟 / TODO

- A_mr 差异化 floor → 单独 PR（需求未明，暂不做）
- E2E daily_equity 真跑 fixture（更重，需要 SQLite + Journal mock）→ 等需求触发再加

## 关联

- [[session_2026_06_07_pr3_options_positions]] — PR3 options 持仓
- [[session_2026_06_07_pr2_max_drawdown]] — PR2 peak DD + agent 隔离 lesson
- [[session_2026_06_07_pr1_portfolio_history]] — PR1 基建
- [[session_2026_06_06_zhuang_risk_parity]] — v1 截止 + 副腿对齐 lesson 源
- [[portfolio_p3_amr_options_baseline_2026-05]] — A_mr 现状（hedge 价值）
- [[a_mr_v2_falsified_2026-05]] — A_mr 不是 alpha 是 noise diversification
- `docs/specs/position_v2_harness.md` §5 — 验收契约
