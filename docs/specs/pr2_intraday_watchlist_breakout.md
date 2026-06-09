# PR2 — daily screen 候选股盘中突破入场告警 (daily_screen_breakout)

**接续** [[pr1_intraday_5min_breach]]。3 PR 中 PR2。

## 范围

1. `daily_equity.py` 跑完候选筛选后，写 `data/intraday/equity_watchlist.json`（asof_date + top N candidates + reference_high/close + entry/sl/tp 建议）
2. 新增模块 `src/quant_system/intraday/watchlist.py`：`WatchlistCandidate` dataclass + `load_watchlist`/`dump_watchlist`
3. `src/quant_system/intraday/core.py` 加 `evaluate_breakout_alerts` 纯函数 + `BreakoutSignal` 输入 dataclass
4. `scripts/intraday/intraday_risk_check.py` 集成：读 watchlist → 拉实时报价（含量比）→ 过滤已持仓 → 评估突破 → Telegram + 写 alerts_sent
5. `config/intraday.yaml` 加 `breakout:` 节（breakout_margin / vol_ratio_min / enabled）

**不在范围**：
- 自动下单（永远不做，Backstop #4）
- zhuang 候选股 watchlist（PR3）
- HK / US 候选股（仅 A 股，HK 量比字段不在 spot_em）

## 数据流

```
T 日 EOD                  T+1 09:30~15:00 (5min 频率)
──────                    ───────────────────────────
daily_equity.py:          intraday_risk_check.py:
  scan_today_entries        load_watchlist(equity)
  hits 排序                 filter 已持仓
  fetch high/close          fetch_realtime_quote (含量比)
  写 equity_watchlist.json  evaluate_breakout_alerts
                            push Telegram
                            写 alerts_sent
```

## Watchlist 文件格式

`data/intraday/equity_watchlist.json`：

```json
{
  "asof_date": "2026-06-09",
  "strategy": "equity_factor",
  "market": "a_share",
  "candidates": [
    {
      "symbol": "601939",
      "name": "建设银行",
      "reference_high": 10.15,
      "reference_close": 10.10,
      "entry_price_suggested": 10.10,
      "stop_loss_suggested": 9.50,
      "take_profit_suggested": 11.00,
      "factor_score": 0.625,
      "reasons": ["MA60 OK", "RSI 58", "..."]
    }
  ]
}
```

- `asof_date` = daily 跑的那天（T）
- `reference_high` = T 日 high（T+1 突破基线）
- 文件**覆盖式写**（每次 daily 完整重写；T 日只保留最新一次结果）
- 文件不存在 / asof_date > 5 个自然日前 → intraday 视为 stale，noop

## 触发条件 (daily_screen_breakout)

**全部满足**：
1. `current_price > reference_high × (1 + breakout_margin)`
   - 默认 `breakout_margin: 0.005` (0.5%)
2. `volume_ratio ≥ vol_ratio_min`
   - 默认 `vol_ratio_min: 1.2`
   - akshare spot_em "量比" 字段；缺失 / None → skip vol 过滤（保守降级，仍发 alert）
3. `symbol` 不在 journal_trades open（已持仓不再报）

**alert_type**: `daily_screen_breakout`
**severity**: `warning`
**message**: `📈 [候选] {symbol}({name}) 突破 T 日高 {pct:.2%}, 量比 {vr:.2f} ｜ 可考虑次日开盘建仓（非自动下单）`

## Dedup

沿用 alerts_sent UNIQUE `(asof_date, strategy_name, symbol, alert_type)`。同一只候选股一天 1 次（首次突破即告警；次日 watchlist 重写后又是新候选）。

**注意**：`asof_date` in alerts_sent 是**intraday 触发日**（T+1），不是 watchlist 的 asof_date（T）。两者解耦。

## 配置 (config/intraday.yaml 新增 breakout 节)

```yaml
breakout:
  enabled: true
  breakout_margin: 0.005       # 突破 T 日 high 的最小幅度
  vol_ratio_min: 1.2           # 量比下限；spot_em "量比" 字段
  watchlist_max_age_days: 5    # asof_date 超过 N 天视 stale
  strategies: ["equity_factor"]  # PR2 仅 equity_factor; zhuang/PR3
```

## 验收门

1. `pytest tests/intraday/` 全绿（28 既有 + ≥ 6 新增 breakout case）
2. `pytest tests/` 全绿
3. daily_equity dry-run 不写入 watchlist（dry-run 模式不应产生副作用文件）
4. daily_equity 正常 run 后 `data/intraday/equity_watchlist.json` 存在且 schema 合法
5. intraday dry-run + mock watchlist → breakout alert 触发

## 不动

- alembic / alerts_sent schema
- yaml 策略阈值 / weights
- daily 决策 (T+1 开盘是否真买仍是用户人工)
- backtest / journal

## Backstop 兼容

- #1 17 条证伪：不调 yaml ✓
- #2 双窗口 8y：不改 yaml ✓
- #3 实盘 < 30 笔：不撬 frontier ✓
- #4 PM 决策权：仅推送 "可考虑"，0 自动下单 ✓
- #5 采集 ≠ alpha：alert ≠ decision ✓

## 后续

- PR3: zhuang 候选股 watchlist + 盘中异动报警 + dashboard 1min 刷新
