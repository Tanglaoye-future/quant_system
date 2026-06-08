# Spec — entry_date 用真实 K 线日，修 hold_days 负数 bug（M3）

## 背景

2026-06-08 daily 输出：
```
#5 601988  持有 -3 天
#6 000063  持有 -3 天
```

Root cause:
- daily 跑 2026-06-08 (周一)，`args.asof='2026-06-08'`
- baostock 06-08 当日 K 线尚未入库, `loader.get_daily(..., end='2026-06-08')` 最后一根是 **06-05 (周五)**
- 自动开仓 entry_price 用 06-05 close, **但 entry_date 字段写 args.asof='2026-06-08'**
- 后续 daily_check 算 `hold_days = current_date(='2026-06-05', cache 最新) - entry_date('2026-06-08') = -3`

不只是显示丑：**entry_date 与 entry_price 日期不一致**会让 L5 α 报表 (M2) 算 benchmark 时取错的 entry_bar close。

## 改动范围

| 文件 | 改动 |
|---|---|
| `src/quant_system/strategies/equity_factor/timing/signals.py` | `scan_today_entries` 在 hit dict 加 `entry_bar_date` = `str(px["date"].iloc[-1])` |
| `scripts/daily/daily_equity.py` | `TradeOpen.entry_date = c.get("entry_bar_date") or args.asof`（兜底保留旧行为）；mean_reversion path 同款（hits builder 用 strategy 输出的 last bar date 或 args.asof） |
| `tests/equity_factor/test_scan_entry_bar_date.py` | 新 case: scan_today_entries hit 含 entry_bar_date 等于 last px row date |
| `scripts/admin/fix_entry_date_retroactive.py` | 一次性 retro fix 脚本: 把 06-08 trade 5/6 entry_date 改成 06-05（实际 K 线日）, 用户授权后跑 |

## Backstop 严守

- **#1**: 不改入场 alpha 逻辑（entry_signal 决策不动）
- **#5**: 0 新计算 — entry_bar_date 是已有 px["date"].iloc[-1]
- **#4**: PM 决策 — retro fix DB 数据 (trade 5/6) 单独 script, 用户授权后跑

## 验收

- pytest tests/ 不回归 (base 324)
- daily 跑 06-08 再次输出: 601988/000063 `持有 0 天`（entry_date=06-05, current_date=06-05）
- 后续 daily 跑 06-09 (周二)：`持有 1 天`
- L5 α 报表 entry_date 与 entry_price 同日

## 不做

- 不改 zhuang daily 路径 (zhuang 自家 entry_date 逻辑独立, 当前未见 hold_days 负数)
- 不改 RiskMonitor.daily_check hold_days 公式 (公式正确, 是输入数据错)
- 不 clip hold_days = max(0, ...)（治标; root cause fix 后自然 ≥0）

## Ops（merge 后）

1. 立即生效：下次 daily 自动开仓 entry_date 用 K 线日
2. 用户授权后跑 `scripts/admin/fix_entry_date_retroactive.py` 修 06-08 trade 5/6 (601988/000063) entry_date `2026-06-08 → 2026-06-05`
3. 之前的 trade 1-4 已是过去交易日触发, entry_date 大概率正确, 不需要 retro

## 关联

- 06-08 conversation: 用户报 "持有 -3 天 bug"
- [[learn_l5_retrospective_report]] — α 报表对 entry_date 精度依赖
