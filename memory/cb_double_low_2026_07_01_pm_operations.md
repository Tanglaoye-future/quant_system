---
name: cb-double-low-2026-07-01-pm-operations
description: 7/1 月初 CB 双低 sleeve 首次实盘 rebalance PM 操作手册 — 从 6/30 pre-flight 到 7/2 录入 20 笔到 7/3+ 日常 maintenance 全流程; gap 处理 + 异常 fallback + 工具 cheat sheet
metadata:
  type: project
---

# 2026-07-01 — CB sleeve 首次实盘 rebalance 操作手册

**日期**: 2026-07-01 (Wed, A 股 trading day, 不撞节假日)
**目标**: PM 7/2 完成 20 笔 CB 双低实盘建仓 + 录入 journal_trades, 让 PR8-PR12 全链路真接通实盘数据
**前置**: PR1-PR12 + ETF probe + admin CLI 全部上 main (2026-06-18)

## 一句话流程

`6/30 pre-flight → 7/1 16:30 launchd 自动跑 → 7/2 早盘前重跑拿 T 数据 → 7/2 盘中下单 20 笔 → 7/2 盘后批量 record_cb_trade.py 20 次 → 7/3 起 daily_cb holdings=20 mode=maintenance + intraday 15 min 评估`

## 北极星 backstop 提醒 (操作前/后都看)

- **≥ 90 天连续运行 + ≥ 30 笔 closed 前不撬** n_entry / exit_threshold / stop_loss_close / min_conversion_premium / sizing / weight (任一)
- **PM 决策权 unchanged** — 程序产出 advisory, **不自动下单 / 不自动改 yaml**
- **CB 不做 T+0** — risk-parity 豁免, 告警 only "考虑减仓" advisory, 不引日内执行循环

详 [[project-north-star]] + [[cb-double-low-pr7-yaml-daily-2026-06]] 5 条 Backstop.

## Phase 0 — 6/30 (Tue) pre-flight checklist

- [ ] `launchctl list | grep com.quant.daily` 确认 launchd Job exit_code=0
- [ ] `./deploy/run_daily.sh --no-options --no-cb` 单测一次保证主流程不挂 (CB section 单独后面 trial run)
- [ ] `venv/bin/python scripts/daily/daily_cb.py --top 10 --no-write` dry-run 看 BUY 候选 list 是否合理
  - 期望: panel 覆盖 > 50/全市场 (akshare 数据完整时), 否则数据滞后, 7/1 跑可能仍 sparse
  - 若 mode=rebalance 提示 7/2 执行, 标记日历
- [ ] `venv/bin/python scripts/admin/close_cb_trade.py --list-open` 期望 "无 open trades ✅"
- [ ] 准备一个空 excel/txt 记 7/2 实际成交清单, columns 至少: bond_code / bond_name / 成交净价 / 张数 / dual_low_score / conversion_premium / rank
  - 这份清单 = `record_cb_trade.py` 输入

## Phase 1 — 7/1 (Wed) launchd 自动跑

**16:30 launchd 自动触发** `./deploy/run_daily.sh` (不带 --no-cb), 预期:

```
▶ [cb_double_low] CB 双低 advisory...
  [3/5] current_holdings (from journal): 0 只
  [4/5] compute_target_portfolio (holdings=0)...
  [5/5] 今日双低 top 20: ...
  📋 mode=rebalance (月初执行)
     HOLD=0  SELL=0 (urgent 0)  BUY=20 (deferred 0)
  🟢 BUY (立即):
     ... 20 只 ...
[db] portfolio_history UPSERT (cb_double_low/cb_a, n=0) ok
[report] quant_cb.json → report/data/quant_cb.json
```

**已知 gap**: akshare value_analysis EOD 数据延迟 1-2 小时, 16:30 跑可能 panel_max_date=6/30 (T-1), BUY 20 list 用 T-1 数据算 — **当参考清单, 不当最终成交清单**

**操作员动作**: **晚 23:00 前** review `report/data/quant_cb.json` 字段:
- `rebalance.mode == "rebalance"` ✓
- `rebalance.buy` 含 20 个 codes ✓
- 强赎临近 `warn_redeem_near` 列表 (这些慎重, 可能持仓即赔)
- 任何 `rebalance.sell[*].urgent == true` (advisory_only 期 N=0 应无, 反常报警)

如果 launchd 没触发 / daily_cb 挂 → 见 Phase 4 异常处理.

## Phase 2 — 7/2 (Thu) 早盘前数据刷新

A 股 9:30 开盘前:

```bash
cd ~/quant_system && ./deploy/run_daily.sh --no-options 2>&1 | tee logs/manual_run_2026-07-02.log
```

**目的**: 重新拉 panel, 此时 akshare value_analysis 应当已更新到 7/1 EOD, panel_max_date=7/1, BUY 20 list 用 T-1=7/1 数据算 — **这份是最终成交清单**

观察 `report/data/quant_cb.json`:
- `asof_panel` 字段是否 = `2026-07-01` (若仍是 6/30, 说明 akshare 当日数据仍未更新, 用 6/30 数据下单)
- `rebalance.buy` 20 个 codes 整理到 Phase 0 准备的 excel/txt

## Phase 3 — 7/2 盘中下单

**9:30 - 15:00** 通过券商 (券商 APP / 量化交易接口) 下单 20 笔, 每笔:

- 资金分配: v7 配比 CB 5%; 假设总资 100 万, CB sleeve = 5 万, 每只 = 2500 元 (= 25 张净价 100 附近)
  - 实际张数: `张数 = ⌊CB_sleeve / 20 / entry_price⌋`, 取整到张数 (CB 100 元 1 张为最小单位)
- 成交时机: **不追高**, 用限价单挂在 daily ranked 出的净价附近 ± 0.5%. 不成交的留到下一日补
- 风控: 任一 bond 流动性差 (今日成交量 < 10 万张) 跳过, 用 daily 给的 21-22 名替补 (rank 给到 top 30 都在 PR9 n_hold_buffer 容差内)

**实时填表**: 每笔成交后立即更新 excel/txt:
| bond_code | bond_name | 成交净价 | 张数 | dual_low_score | conversion_premium | rank |
|---|---|---|---|---|---|---|
| 113008 | 电气转债 | 108.45 | 23 | 128.42 | 19.92 | 3 |

## Phase 4 — 7/2 (Thu) 盘后批量 record

A 股 15:00 收盘后, 假设 20 笔全成交, **批量录入 journal_trades**:

### 选项 A — 手抄 20 次 (最简)

```bash
cd ~/quant_system
# 先 dry-run 验证 1 笔
venv/bin/python scripts/admin/record_cb_trade.py \
    --code 113008 --bond-name "电气转债" \
    --entry-date 2026-07-02 --entry-price 108.45 --entry-size 23 \
    --dual-low-score 128.42 --conversion-premium 19.92 --rank 3 \
    --dry-run

# OK 后去 --dry-run, 真写一笔
venv/bin/python scripts/admin/record_cb_trade.py --code 113008 ... (略 --dry-run)

# 重复 20 次
```

### 选项 B — Shell loop 读 excel (推荐)

把 excel 另存为 `7_02_rebalance.tsv` (tab 分隔, 第 1 行 header), 然后:

```bash
cd ~/quant_system
tail -n +2 7_02_rebalance.tsv | while IFS=$'\t' read -r code name price size score prem rank; do
  venv/bin/python scripts/admin/record_cb_trade.py \
      --code "$code" --bond-name "$name" \
      --entry-date 2026-07-02 \
      --entry-price "$price" --entry-size "$size" \
      --dual-low-score "$score" --conversion-premium "$prem" --rank "$rank"
done | tee logs/record_cb_2026-07-02.log
```

### 录入完毕验证

```bash
venv/bin/python scripts/admin/close_cb_trade.py --list-open
# 期望: CB sleeve open trades: 20
```

也可直接 SQL:

```sql
SELECT COUNT(*), SUM(entry_price * entry_size) AS cost_yuan
FROM journal_trades
WHERE market='cb_a' AND strategy='cb_double_low' AND exit_date IS NULL;
-- 期望: count=20, cost ≈ 5 万
```

## Phase 5 — 7/3 (Fri) 起日常 maintenance

### 5.1 daily_cb 行为变化

16:30 launchd 跑 `daily_cb`:
- `current_holdings` 反查 = 20 codes
- `is_rebalance_day(2026-07-03) = False` (day=3 ≤ 5 实际仍 True, 7/6 起 False — 5 天 buffer 是有意为之)
- `mode == "maintenance"` (7/6 起) → BUY 信号 deferred 不立即执行; SELL 仍触发 (urgent 不等月初)
- `HOLD/SELL/BUY` 真数据 diff
- `portfolio_history` n=20 + cost/mv/pnl 真实

### 5.2 intraday_risk_check (15 min cadence)

`nohup venv/bin/python scripts/intraday/intraday_risk_check.py --loop &` 已在背景跑 (PR10 落地), 评估 CB 每 15 min:

- close 击穿 stop_loss_close=85 → Telegram 🛑 `cb_break_stop_loss` critical
- 强赎 last_trading_date ≤ 30d → Telegram ⏰ `cb_redeem_imminent` critical

收到 critical 告警后, PM 立即:
1. 评估出场 (不是必须, "考虑减仓" advisory)
2. 若决定出场, 走 [Phase 6 close](#phase-6-close-cb-trade-出场)

### 5.3 每月初再次 rebalance (8/1)

A 股 8/1 是 Sat, 不交易. **launchd 8/3 (Mon) 16:30 跑首次 8 月 advisory**:
- `today=2026-08-03`, day=3 ≤ 5, `is_rebalance_day=True`
- daily_cb 反查 20 holdings, `compute_target_portfolio` 出:
  - `kept` (rank<30 buffer + score<180 + close>=85 的 CB)
  - `exited` (rank>30 漂移 / score>180 / close<85)
  - `entered` (替补)
- 控制台 SELL N 条 + BUY M 条, advisory 给 PM

**PM 8/3 - 8/5 内**: 卖 SELL 那些 (`close_cb_trade.py --exit-reason out_of_top_band` 或 `dual_low_too_high`), 买 BUY 那些 (`record_cb_trade.py`), 净 holdings 仍 ≈ 20

## Phase 6 — close CB trade 出场

任何时候发现需要出场 (8/3 rebalance / intraday 告警 / 强赎临近), 走 `close_cb_trade.py`:

```bash
# 1. 查 trade_id
venv/bin/python scripts/admin/close_cb_trade.py --list-open
# 找到要出场的 id, 例如 113008 是 id=42

# 2. dry-run 看 pnl
venv/bin/python scripts/admin/close_cb_trade.py \
    --trade-id 42 --exit-date 2026-08-03 --exit-price 125.0 \
    --exit-reason score_over_180 --dry-run

# 3. 真写
venv/bin/python scripts/admin/close_cb_trade.py \
    --trade-id 42 --exit-date 2026-08-03 --exit-price 125.0 \
    --exit-reason score_over_180
```

### exit_reason 枚举对照 — 选对很重要, 影响 PR12 retrospective 分桶

| 真实出场情景 | --exit-reason | PR12 cb_exit_type |
|---|---|---|
| score 越线 180 | `score_over_180` | SCORE_EXIT (winner 候选) |
| 月度 rank 漂移到 30+ | `out_of_top_band` | REBALANCE |
| 净价跌破 85 止损 | `stop_loss` | STOP_LOSS (loser) |
| 公司公告强赎 | `redeem_announced` | FORCE_REDEEM |
| 强赎临近告警执行 | `cb_redeem_imminent` | FORCE_REDEEM |
| 该债退市 / 被砍出 filter | `out_of_universe` | DELISTED |
| 其他 (临时调仓) | `manual` | OTHER |

## 异常处理

### A. 7/1 launchd 没跑

```bash
launchctl list | grep com.quant.daily
# 看 exit_code, 不是 0 → 看 logs/launchd_stderr.log
# 手动重启:
launchctl unload ~/Library/LaunchAgents/com.quant.daily.plist
launchctl load   ~/Library/LaunchAgents/com.quant.daily.plist
# 立即手跑一次:
cd ~/quant_system && ./deploy/run_daily.sh --no-options
```

### B. daily_cb 挂在 akshare 网络

PR8 `load_panel` 有 per-code retry, 一般挂少数 code 不拖死 panel. 全部挂网络:
```bash
ping -c 3 akshare.akfamily.xyz  # 测连通
# Clash 代理 issue 已修, 见 intraday/akshare_cffi_patch.py
# 真挂: 17:00 后重跑, 通常 akshare 节流过了
```

### C. record_cb_trade 拒绝 "已存在 open"

重复防御触发 (同 code 已 open). 检查:
- 是否 7/2 不小心跑了两次同一笔? 用 `close_cb_trade --list-open` 看
- 如果是重复录, 手动 SQL 删 (谨慎):
```sql
DELETE FROM journal_trades WHERE id = <重复 id>;
```

### D. close_cb_trade 拒绝 "不属 CB sleeve"

PM 不小心传了 equity trade_id. `--list-open` 不带 filter 看全部:
```bash
venv/bin/python -c "
from quant_system.strategies.cb_double_low.journal import Journal
for t in Journal().list_open():
    print(t['id'], t['symbol'], t['market'], t['strategy'])
"
```

### E. intraday 15 min cadence 没告警, 但实际 close 跌破 85

```bash
ps aux | grep intraday_risk_check
# 没跑 → nohup 启动:
cd ~/quant_system && nohup venv/bin/python scripts/intraday/intraday_risk_check.py --loop &
# 跑了但没告警 → log:
tail -f /tmp/intraday_*.log
# 单跑一次 dry-run 看评估结果:
venv/bin/python scripts/intraday/intraday_risk_check.py --dry-run
```

## 工具 cheat sheet

| 工具 | 用途 | 触发 |
|---|---|---|
| `./deploy/run_daily.sh` | 联合 daily (5 个子策略 + CB) | launchd 每工作日 16:30 自动 + PM 手跑 |
| `scripts/daily/daily_cb.py` | CB 单跑 advisory | run_daily 内部调用 + PM 单独 --top N |
| `scripts/intraday/intraday_risk_check.py` | 15 min loop 风控 | `nohup ... --loop &` |
| **`scripts/admin/record_cb_trade.py`** | **PM 录入 CB entry** | 7/2 盘后 20 次 / 月初 rebalance 时 |
| **`scripts/admin/close_cb_trade.py`** | **PM 录入 CB exit** | 月初/告警/强赎触发时 |
| `scripts/research/learn_from_trades.py --since 2026-07-01` | retrospective 报表 | 9 月 ≥30 笔后首次有意义 |
| `python -m quant_system.report.builder --date 2026-07-XX` | standalone HTML report (CB section) | PM 邮件场景 |

## 验收日历

- **7/1**: launchd 自动 + `quant_cb.json` 含 `mode=rebalance BUY=20`
- **7/2**: 20 笔录入完, `close_cb_trade --list-open` 显示 20 行
- **7/3**: daily_cb 反查 holdings=20, mode=maintenance
- **7/3+**: intraday log 有 CB 评估行 (无告警是正常, 有告警立即处理)
- **8/3**: 月度 rebalance signal 出 SELL/BUY diff (期望 rank 漂移 1-5 个换仓)
- **2026-09-30**: 累计 closed ~30 笔, 首次跑 `learn_from_trades --since 2026-07-01` 出 retrospective
  - PM 看 winner-vs-loser 分布差: dual_low_score / conversion_premium / scale / rating 哪些指标显著
  - cb_exit_type 桶分布: SCORE_EXIT 占比 (winner 主力) / STOP_LOSS 占比 (loser 主力) / FORCE_REDEEM 占比
  - alpha α (本 PR12 留 None, L5.1 接 baostock CB index 替代) — 暂手算 ≈ avg_pnl_pct - CSI500 avg_return

## 9 月后决策点

按 [[cb-double-low-pr12-self-learning-2026-06]] 末尾时间线, 9/30 retrospective 后 3 选 1:

| 决策 | 触发条件 | 操作 |
|---|---|---|
| **Option 2 升级** | 双窗口同向 PASS (与 [[cb-double-low-pr6-v7-overlay-2026-06]] 比 alpha 增量 > 0.1) + retrospective 显示 winner 集中 SCORE_EXIT | CB 从 5% → 10% (再 A_mom 抽 5pp), 改 `config/cb_double_low.yaml` portfolio.target_pct=0.10. 走 AskUserQuestion 人工确认 |
| **维持 5%** | retrospective 中性或弱正, 但 alpha α > 0 | yaml 不动, 继续观察 12 月底 |
| **归档** | retrospective 显示 N≥30 但 avg α < 0 / loser 集中 SCORE_EXIT (出场太晚) | 写 `cb_double_low_falsified_2026-09.md`, 改 `daily.enabled: false`, 把 5% 还给 A_mom |

## 关联

- [[cb-double-low-pr7-yaml-daily-2026-06]] daily 入口 + advisory_only 决策
- [[cb-double-low-pr8-journal-portfolio-2026-06]] journal_trades schema (复用 equity 表族)
- [[cb-double-low-pr9-rebalance-signal-2026-06]] rebalance signal + mode 判定
- [[cb-double-low-pr10-intraday-risk-2026-06]] 实时风控 (close<85 + 强赎临近)
- [[cb-double-low-pr11-closed-trades-html-2026-06]] cb_exit_type + close_cb_trade
- [[cb-double-low-pr12-self-learning-2026-06]] retrospective 9 月触发
- [[cb-double-low-pr6-v7-overlay-2026-06]] STRONG PASS baseline (Option 2 升级阈值)
- [[project-north-star]] 4 支柱 backstop
- [[deployment_plan_v7_2026-06]] v7 组合层配比来源 (HK 50% / A_mom 15% / A_mr 0% / QQQ 10% / GLD 10% / BTC 10% / CB 5%)
