# Spec — schema fix: journal_trades.exit_reason VARCHAR(32) → VARCHAR(255)

## 背景

2026-06-08 daily 实盘 A_mom 在 close_trade 这一步直接抛
`psycopg.errors.StringDataRightTruncation: value too long for type character varying(32)`,
原因是 `JournalTrade.exit_reason: String(32)` 容不下 trailing_stop 信号文本
`"trailing_stop: close=24.54 <= stop=24.55"` (42 char)。

阻塞链条：
- 06-05 601066 中信建投触发 trailing_stop → close_trade() 抛 → daily 整段挂
- 06-05/06-08 两次 daily 都挂在同一处 → A_mom 全市场扫描 / portfolio summary / report JSON 三天没更新
- zhuang 的 ZhuangTrade.exit_reason 是 String(64) 没事，仅 equity 侧受影响

## 改动范围（最小）

| 文件 | 改动 |
|---|---|
| `src/quant_system/db/models.py` L139 | `String(32) → String(255)` |
| `alembic/versions/f4a5b6c7d8e9_widen_journal_exit_reason.py` | 新 migration，alter column type 到 VARCHAR(255)，down_revision = `e3f4a5b6c7d8` (现 head) |
| `tests/equity_factor/test_journal.py` | 加 1 case：`close_trade` 用 50 char reason 不抛错 |

## Migration 细节

- 上：`op.alter_column('journal_trades', 'exit_reason', type_=sa.String(255), existing_nullable=True)`
- 下：`op.alter_column(... type_=sa.String(32) ...)`（下迁逆操作，因为 schema 改动是扩容，downgrade 在 length 缩回时若有真实数据已超 32 会失败，但当前 DB exit_reason 全 NULL，无风险）
- VARCHAR(255) 而非 TEXT：保留长度上限（防御性），255 足够任何 `<exit_type>: <details>` 信号串

## 验收

- 改前：`pytest tests/equity_factor/test_journal.py` 现有用例 pass
- 改后：
  - 新 case 用 50 char reason 走 close_trade 成功，DB 落地完整字符串
  - 全量 `pytest tests/` 不回归（基线 281/281）
  - `alembic heads` 单 head = `f4a5b6c7d8e9`，linear 7 个 revision

## Ops 操作（非代码 — 用户授权后跑）

1. `venv/bin/alembic upgrade head`
   - 一次性 apply：`c1d2e3f4a5b6` (portfolio_history, PR1) + `d2e3f4a5b6c7` (options_positions, PR3) + `e3f4a5b6c7d8` (alerts_sent, PR5) + 本次 `f4a5b6c7d8e9` (exit_reason)
   - 等于同时解 Bug B（持仓 v2 五个 PR 启用）+ Bug A（schema 扩容）
2. 重跑 daily：`./deploy/run_daily.sh --no-options`
   - HK / A_mom / A_mr / zhuang 全跑通，A_mom 处理 trade 2 (601066 中信建投) 退出
3. 检查 trade 2 状态
   - 若 06-09 收盘 close ≤ stop 24.55 → 自动触发 trailing_stop，写入 exit_date=2026-06-09
   - 若已反弹 close > stop → 仍 HOLD，stop 已上调到 24.55，距止损极近
   - **不 retroactive 把 exit_date 改回 06-05**：实盘没法逆向交易，用户实际是否在 06-05 卖出是人工动作，由用户对账

## 不做（明文）

- 不改 zhuang ZhuangTrade.exit_reason（VARCHAR(64) 当前没受害，留作未来必要时单独 PR）
- 不在本 PR 改 close_trade 调用方逻辑（exit_reason 字符串构造方式不变）
- 不补写 trade 2 退出的 retro 数据
- 不改前端 / JSON / report builder（exit_reason 不在前端展示路径）

## 关联

- [[session_2026_06_04_realtime_risk_v1]] — Step 1/2 当前已实现但因 Bug B 未启用
- [[session_2026_06_07_pr5_intraday_telegram]] — PR5 alerts_sent 表同样 dormant，本次 ops 一起 apply
- [[project_live_entry_diagnosis_2026-05]] — 用户"程序有没有在监控"实际答案 = 因 Bug A 三天没监控
