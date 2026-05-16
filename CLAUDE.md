# zhuang_system — 开发规范

## 项目定位

A股小盘庄股跟庄策略。识别**吃货期**（主力积累阶段），在积累末段建仓，拉升持仓，动态止盈/止损退出。数据源：**BaoStock**（非营利，无代理问题）。

## 必读：BaoStock 坑

| 字段 | 单位 | 常见错误 |
|------|------|---------|
| `turn`（换手率） | **百分比**（1.5 = 1.5%） | 误当小数，阈值用0.08而非8.0 → 每单持仓2天即出场 |
| `totalShare`（总股本） | **股**（不是万股） | 乘以1e4导致市值虚高10000倍 |
| BaoStock TCP连接 | 长时间批量后会断 | 4858次查询后再查价格全部失败 → 必须logout+login重连 |

## 修改前必读文件

- `config.yaml` — 所有策略参数（改参数只改这里）
- `zhuang_system/signals/exit.py` — 出场优先级（止损/动量早止/时间止损/止盈/派发）
- `zhuang_system/signals/entry.py` — Phase-A 入场（score + 价格位置确认）
- `zhuang_system/data/loader.py` — universe构建 + 日线缓存

## 修改后必须验证

```bash
# 1. 今日扫描（验证数据管道）
.venv/bin/python scripts/scan_today.py --top 15 --min-score 45

# 2. 全量回测（改参数必跑，不得用sample缩减）
.venv/bin/python scripts/backtest.py \
  --start 2022-01-01 --end 2024-12-31 \
  --universe-file data/cache/universe_2026-05-10.csv \
  --refresh-days 9999
```

## 准入门槛

| 指标 | 门槛 |
|------|------|
| Sharpe | ≥ 0.3 |
| 最大回撤 | ≤ 30% |
| 胜率 | ≥ 40% |

## Session 启动

**每次会话开始时，自动读取 `memory/` 下所有文件。**

## 当前基线（v6 L1-E，2020-2026）

Sharpe **1.35** | 年化 **+6.2%** | 回撤 **-3.8%** | 胜率 **50.3%** | 盈亏比 **2.89** | 141笔

参数改动（vs v5）：
- `entry_price_position_min`: 0.5 → **0.4**
- `accumulation_score_entry`: 65 → **70**

## 关键参数（config.yaml strategy 段）

```yaml
accumulation_score_entry: 70     # Phase-A 入场门槛 (v6: 65→70)
max_hold_days: 15                # 基础最长持仓
extend_hold_days: 25             # 浮盈≥5%时延长
extend_profit_pct: 0.05
entry_price_position_min: 0.4    # v6: 0.5→0.4 放宽位置过滤
stop_loss_atr_mult: 2.0
max_stop_loss_pct: 0.06
momentum_stop_pct: 0.05
distribution_turnover_thresh: 8.0
market_trend_filter: true
market_trend_index: sh.000905
market_trend_ma: 60
```

## 反模式（禁止）

- 不得用 akshare（Clash代理封锁 eastmoney 域名）
- 不得用 sample 缩减回测验证（≥300只可做调参快测，但最终必须跑全量3307只）
- 不得改 `distribution_turnover_thresh` 为小数（BaoStock turn 是百分比）
- 每个参数改动单独回测对比，不得同时改多个变量
