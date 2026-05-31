---
name: monthly-kpi-scaffold-2026-05
description: v5 实盘月度 KPI 报告脚手架 — 2026-06-30 第一次 checkpoint 用；scripts/reporting/monthly_kpi_report.py + 10 单测 + dry-run；Phase 1 = closed trades 聚合，Phase 2 = 日级 ρ 待补
metadata:
  type: project
---

## 一句话结论

为 2026-06-30 第一次实盘 checkpoint 提前写好脚手架: `scripts/reporting/monthly_kpi_report.py` 读 journal_trades + zhuang_trades 当月 closed, 按 v5 sleeve (HK/A_mom/A_mr/zhuang/QQQ/GLD) 聚合 win rate/PnL/告警, 出 markdown。10 个单测全 pass, dry-run mock 数据渲染验证通过。Phase 1 范围足以驱动月度 PM review, 不阻塞实盘运行。

## v5 sleeve 映射 (脚本固化)

| sleeve | weight | 数据源 | 标识 |
|---|---|---|---|
| HK | 25% | journal_trades | market='hk_share' (任意 strategy) |
| A_mom | 10% | journal_trades | market='a_share' AND strategy='equity_momentum' |
| A_mr | 10% | journal_trades | market='a_share' AND strategy='mean_reversion' |
| zhuang | 40% | zhuang_trades | 全部 |
| QQQ | 5% | 手填 (--qqq-return) | buy-and-hold, 不进 journal |
| GLD | 10% | 手填 (--gld-return) | buy-and-hold, 不进 journal |

## 告警阈值 (脚本固化)

- 任 sleeve win rate < 30% 且 n_closed ≥ 5 → "建议暂停 sleeve"
- 组合月收益 < -2% → "立即触发深度诊断"
- zhuang AUM > 30M RMB → "压回 20-25%" ([[deployment_plan_2026-05]] capacity 铁律)
- 单 sleeve 月收益 < -5% → 暂停 (备注里, 当前未实现具体计算)

来源: [[v5_efficient_frontier_2026-05]] 末尾 "3 月实盘验证 KPI checklist" + [[deployment_plan_2026-05]]

## Phase 1 (当前) 范围

✅ closed trades 当月聚合 (entry/exit 都在月内 或 exit 落在月内)
✅ win rate / sum pnl / mean trade % per sleeve
✅ 组合月收益 = closed pnl / aum + QQQ × 0.05 + GLD × 0.10
✅ 告警评估 (上述 3 条规则)
✅ markdown 输出 → `report/monthly_kpi_<YYYY-MM>.md`
✅ dry-run --mock 模式: 内存 SQLite + 注入 mock trades 验证渲染
✅ 单测 10 个: month parse / 空 journal / 分类 / pnl_pct mean / 告警逻辑 / 渲染段 / E2E

## Phase 2 (TODO, 实盘 1 个月数据沉淀后补)

⏳ 跨账户 60d 滚动 ρ — 需要日级 portfolio equity series
   - 数据源: JournalSnapshot.unrealized_pnl_pct + ZhuangSnapshot
   - 算法: 按 sleeve 聚合 daily MTM → daily return → 60d 滚动 corr
   - 限制: 实盘窗口 ≥60 个交易日才有意义 (= 2026-09 后)
⏳ MTD Sharpe 滚动 30d — 同样需要日级 equity series
⏳ 与回测同期月收益对比 — 需要 backtest v5 月级 PnL 时间序列存档
⏳ 持仓集中度告警 (单股 > 5% 权重)

## 关键设计决定 (Why)

1. **接受 sessionmaker 注入** — 单测内存 SQLite, 不依赖 PG (复用 test_journal.py 模式)
2. **mock 模式独立** — 用户可不连 DB 验证脚本, 也可用作 PM review 培训样例
3. **告警分级 (⚠️ warning vs 🚨 critical)** — markdown 一眼区分严重度
4. **QQQ/GLD 手填而非自动拉** — buy-and-hold sleeve 简单到不值得维护数据源, 月度 PM review 时手填 5 秒
5. **不实现日级 ρ** — 实盘窗口 ≥60 个交易日才有意义, 6/30 第一次 checkpoint 时数据不足, 先空占位

## 使用入口

```bash
# 默认上月报告 (现在 = 5 月底 → 出 4 月报告 = 空 journal)
./venv/bin/python scripts/reporting/monthly_kpi_report.py

# 6 月 checkpoint (2026-07-01 跑)
./venv/bin/python scripts/reporting/monthly_kpi_report.py --month 2026-06 \
    --aum-cny 1000000 --qqq-return 0.02 --gld-return 0.01

# dry-run 看脚本结构
./venv/bin/python scripts/reporting/monthly_kpi_report.py --mock --month 2026-06
```

## 产物清单

- `scripts/reporting/monthly_kpi_report.py` — 主脚本 + mock fn
- `tests/reporting/__init__.py` + `test_monthly_kpi_report.py` — 10 单测
- 输出位置: `report/monthly_kpi_<YYYY-MM>.md`

## 时间成本

- 调研 (journal API / v5 weights / KPI 阈值): ~10 min
- 主脚本: ~25 min
- 单测: ~15 min
- dry-run 验证 + 清理 mock 文件: ~5 min
- 总: ~55 min — 远低于 backlog 预估 "1 session" (~2-3 hr)

**Why:** 6/30 是 v5 实盘第一次 KPI checkpoint, 提前 1 个月写好脚手架, 实盘运行期不被报告工具反向阻塞 PM 决策。延后到 6/30 才写有 KPI 失效风险 — 触发条件来不及响应。
**How to apply:** 2026-07-01 实盘满 1 个月后跑 `--month 2026-06`, 出报告 → 按告警决定 sleeve 暂停/继续/再平衡。Phase 2 待实盘 ≥60 天后补 (= 2026-09 后)。
