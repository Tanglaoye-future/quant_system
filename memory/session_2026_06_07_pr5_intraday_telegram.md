---
name: session-2026-06-07-pr5-intraday-telegram
description: PR5 of 持仓 v2 harness — Step 3 盘中实时风控 cron + Telegram 推送; alerts_sent dedup 表; 4 阈值 (用户授权 Telegram/15 min); 21 case 测试; 默认 OFF + 凭证走 env
metadata:
  type: project
---

# 2026-06-07 Session — PR5 持仓 v2 harness: 盘中实时 + Telegram 推送

接续 [[session_2026_06_07_pr4_hk_amr_regression]]。完成持仓 v2 harness 5 个 PR 的最后一个。spec `docs/specs/position_v2_harness.md` §6。

## 用户授权（2026-06-07）

[[session_2026_06_04_realtime_risk_v1]] 明确 Step 3 必须用户授权。本 session AskUserQuestion 三连：
- 启动 PR5：**现在启动**
- 推送通道：**Telegram bot**（凭证走 env）
- 频率：**15 min**
- 触发阈值：**全 4 项**（距止损 < 0.5% / 距止盈 < 0.5% / 组合浮亏 < -5% / peak DD < -7%）

## 范围

新增 4 个 layer，完全独立于 daily 路径（daily 一不动）：
1. **DB 层**：alerts_sent 表（dedup unique index = asof_date+strategy+symbol+alert_type）
2. **通道层**：notify/telegram.py（urllib + env 凭证，0 SDK 依赖）
3. **评估层**：intraday/core.py（纯函数 `evaluate_alerts` + `is_in_trading_window`）
4. **入口脚本**：scripts/intraday/intraday_risk_check.py（cron / loop / dry-run）

## 改动落地（branch `pr5/intraday-risk-telegram`）

| 文件 | 单元 |
|---|---|
| `alembic/versions/e3f4a5b6c7d8_add_alerts_sent.py` | DDL migration (head = e3f4a5b6c7d8) |
| `src/quant_system/db/models.py` | `AlertsSent` ORM（dedup unique + payload JSONB + delivered/error） |
| `src/quant_system/db/__init__.py` | export `AlertsSent` |
| `src/quant_system/notify/__init__.py` + `telegram.py` | 新 `TelegramSender`，env 读凭证，0 外部 SDK |
| `src/quant_system/intraday/__init__.py` + `core.py` | 纯函数 evaluate_alerts + IntradayConfig + AlertEvent + is_in_trading_window |
| `scripts/intraday/intraday_risk_check.py` | 主脚本（--loop / --dry-run）：journal → realtime price → snapshots → evaluate → dedup → Telegram → 写 alerts_sent |
| `config/intraday.yaml` | yaml 配置（默认 enabled: false） |
| `tests/intraday/test_intraday_risk_check.py` | 21 case（6 trigger + 5 window + 3 safety + 2 yaml + 3 telegram + 2 misc） |

## 关键设计决策

### 凭证全走 env，不入 yaml
TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID 读 os.environ；TelegramSender 未配 → `(False, "...not set")` 不抛错。即使 yaml 不小心 commit 到公网也不泄露 token。

### evaluate_alerts 纯函数
不读 DB / 不读 akshare / 不发推送 → 单测全 mock 可跑（21 case 0.03s）。主脚本负责 I/O 编排。

### dedup 数据库 UNIQUE 兜底 + 提前 check
alerts_sent (asof_date, strategy, symbol, alert_type) UNIQUE → 即使应用层 race condition 也保证 DB 不重；`_already_sent_today` 提前查避免重复 Telegram API 调用。DB 不可达时偏保守"当作已发"（容错优先于通知频率）。

### A 股交易时段 + 周末判定
`is_in_trading_window` 算 9:30-11:30 / 13:00-15:00；周末永远 False。节假日靠 akshare 拉不到数据时上层 noop（log 不报错）。HK / US 时段后续扩。

### nohup 守护 vs launchd
launchd 因 macOS TCC 阻塞（[[session_2026_05_27]]）。yaml 注释明确：要启用走 `nohup ... --loop &`。

### 不依赖 PortfolioHistory + cash 跟踪
组合层浮亏算法：sum(current) / sum(entry) - 1（持仓平均权重）。严格起见应入 size，留 TODO；当前简化与 spec §3.4 equity proxy 一致（已 documented 失真模式）。

## 验证门（全绿）

- `pytest tests/intraday/` → 21/21 PASS
- `pytest tests/` → 281/281 PASS（PR4 后 260 + PR5 21）
- `alembic heads` → 单 head `e3f4a5b6c7d8`，linear 6 个 revision
- AST parse 8 个改动 .py OK
- 默认 OFF（intraday_alerts.enabled=false）整脚本 noop 零行为差异
- Telegram 未配 env → 不抛错，仅返 (False, "...not set")

## 启用步骤（用户操作）

```bash
# 1. 拿 bot token + chat_id（@BotFather / @userinfobot）
export TELEGRAM_BOT_TOKEN="123456:ABC-..."
export TELEGRAM_CHAT_ID="123456789"

# 2. 翻 yaml enabled
sed -i '' 's/enabled: false/enabled: true/' config/intraday.yaml  # 仅顶层节，谨慎

# 3. 干跑一次验证（不推不写 DB）
venv/bin/python scripts/intraday/intraday_risk_check.py --dry-run

# 4. nohup 后台守护
nohup venv/bin/python scripts/intraday/intraday_risk_check.py --loop \
    > logs/intraday.log 2>&1 &
echo $! > /tmp/intraday.pid
```

## 已知 TODO

- HK / US 时段扩 + realtime price source（仅 A 股 akshare 接入）
- PortfolioSnapshot 加 size 字段消除 equity proxy 简化偏差
- options 持仓盘中接入（spec §6.8 推迟）
- 监控自身可观察（health check endpoint / 心跳）

## 持仓 v2 harness 5 PR 全部完成

| PR | merged | 内容 |
|---|---|---|
| #1 PR0 | ✓ | spec + methodology |
| #3 PR1 | ✓ | portfolio_history 基建 |
| #4 PR2 | ✓ | max_drawdown peak DD |
| #5 PR3 | ✓ | options BCS 持仓 |
| #6 PR4 | ✓ | HK_mom/A_mr 回归 |
| 本 PR PR5 | 待 review | intraday + Telegram |

## 关联

- [[session_2026_06_04_realtime_risk_v1]] — Step 1/2 落地 + Step 3 用户授权门
- [[session_2026_06_07_pr1_portfolio_history]] - [[session_2026_06_07_pr4_hk_amr_regression]] — 前 4 PR
- [[session_2026_05_27]] — launchd TCC 阻塞决策（影响 PR5 选 nohup）
- [[feedback_harness_first_pr_split]] — 方法论（5 PR 全程遵守）
- `docs/specs/position_v2_harness.md` §6 — 验收契约
