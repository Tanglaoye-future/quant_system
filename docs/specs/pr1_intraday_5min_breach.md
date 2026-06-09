# PR1 — intraday 5min poll + 跌穿告警 (break_stop_loss / break_ma60)

**触发**：session 2026-06-09，用户提"实时数据 + 分钟监控"诉求。侦察后选 PR5 扩展路径（[[session_2026_06_07_pr5_intraday_telegram]] 续作）。

## 范围

1. `config/intraday.yaml` poll_interval 15 → **5 分钟**
2. 新增 alert_type **`break_stop_loss`**（current_price < stop_loss）
3. 新增 alert_type **`break_ma60`**（current_price < MA60）
4. `PositionSnapshot` 加 `ma_long: Optional[float]` 字段
5. `intraday_risk_check.py` 加 MA60 拉取 helper（akshare daily history → SMA(60)）

**不在范围**：
- daily screen 候选股入场报警（PR2）
- zhuang 庄股盘中异动（PR3）
- 前端 dashboard 自动刷新（PR3）
- dedup 频率升级 / alerts_sent schema 改动（沿用 once-per-day per (date, strategy, symbol, alert_type)）

## 设计决策

### dedup 沿用一天一次
- 跌穿后用户已被首次告警提醒，5min 一次重推会刷屏
- alerts_sent UNIQUE 约束 `(asof_date, strategy_name, symbol, alert_type)` 不变 → 无 alembic migration
- 同股同类型一天 1 次 critical 推送

### `break_*` vs `*_proximity` 互斥
| 状态 | 触发 |
|---|---|
| current ≥ stop_loss + threshold | 无 |
| stop_loss ≤ current < stop_loss × (1 + threshold) | `stop_loss_proximity` (existing) |
| current < stop_loss | `break_stop_loss` (new, **critical 高于 proximity**) |
| current ≥ ma60 | 无 |
| current < ma60 | `break_ma60` (new) |

`break_stop_loss` 触发时**不再触发** `stop_loss_proximity`（按现有 `negative_dist_to_stop_does_not_trigger` 测试逻辑天然成立）。

### MA60 数据源
- akshare `stock_zh_a_hist(period='daily', adjust='qfq')` 拉 (asof - 90 日) → asof-1 日的 close
- 取最后 60 条算算术 SMA
- 不足 60 条 → ma_long=None，不触发 break_ma60
- intraday cron 一次 run 拉一次（4 持仓 × 0.5s = 2s 可接受）；不引入缓存层（保持 intraday 轻量）

### MA60 baseline 用 T-1 而不是 T
- intraday 时 T 日还在交易中，MA60 包含 T 日不稳定
- 用 [T-90, T-1] 计算 MA60，再跟 T 日 current_price 比，物理意义清晰：当前价跌破"昨日为止的 60 日均线"

## 验收门

1. `pytest tests/intraday/` 全绿（既有 21 case + 新增 ≥ 4 case）
2. `pytest tests/` 全绿（不破坏 281 既有 case）
3. dry-run 跑通：`venv/bin/python scripts/intraday/intraday_risk_check.py --dry-run`
4. mock 网络的 break_stop_loss / break_ma60 case 至少各 1 条 PASS

## 不动

- alembic head（不加 migration）
- yaml 阈值（不改 0.5% / -5% / -7%）
- 策略 / backtest / daily 路径（zero touch）
- daily decisions（仍是 EOD 唯一权威）

## Backstop 兼容性

- **#1 17 条证伪硬墙**：不涉及 yaml 调参 / efficient set ✓
- **#2 双窗口 4y+8y PASS**：不改 yaml ✓
- **#3 实盘 < 30 笔不能撬 frontier**：不撬 ✓
- **#4 PM 决策权**：仅 alert 推送，0 自动下单 ✓
- **#5 采集与 alpha 分离**：alert ≠ decision ✓

## 后续 PR

- PR2: daily watchlist + 候选股盘中突破入场报警
- PR3: zhuang 盘中异动 + dashboard 1min 刷新
