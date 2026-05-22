---
name: 实盘部署检查清单 2026-05-15
description: 启动实盘的完整操作清单，含自动化调度配置、第一月 KPI、异常处理
type: project
---

## 第 0 步：系统验证（终端执行）

```bash
# 1. 单策略信号测试
cd /Users/franktang/Documents/workplace/projects/quant_system

python3 scripts/daily_run.py --market hk_share --strategy bottomup_timing --top 5
python3 scripts/daily_run.py --market a_share --strategy bottomup_timing --top 5
python3 scripts/daily_run.py --market a_share --strategy mean_reversion --top 5

# 2. 联合运行脚本
chmod +x run_daily.sh
./run_daily.sh --no-options

# 3. 确认报告生成
ls report/strategy_report_$(date +%Y-%m-%d).html
```

## 第 1 步：券商账户（操作层）

- [ ] A 股账户（hs300 成份）— 20% + 10% 资金
- [ ] A 股账户（zhuang 庄股）— 20% 资金
- [ ] HK 港股账户（hs100 成份）— 20% 资金
- [ ] US 美股账户（QQQ 买入后不动）— 15% 资金
- [ ] US 美股账户（GLD 黄金 ETF 买入后不动）— 15% 资金
- [ ] 或：A 股账户内买 518880（华安黄金 ETF）替代 GLD（避免出境购汇）

## 第 2 步：资金分配

| 账户 | 占比 | 首次买入 |
|---|---|---|
| A 股 / momentum | 20% | 手动分期建仓（3 周，每周 1/3）|
| A 股 / mean-reversion | 10% | 手动分期建仓（同）|
| A 股 / zhuang | 20% | zhuang 信号触发后再建，无信号保持现金 |
| HK 港股 | 20% | 手动分期建仓（同）|
| QQQ | 15% | 一次性买入 |
| GLD / 518880 | 15% | 一次性买入 |

## 第 3 步：启动每日自动化

```bash
# 安装 launchd 定时任务（每个交易日 16:30 执行）
cp com.quant.daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.quant.daily.plist

# 验证已加载
launchctl list | grep com.quant.daily

# 手动触发一次（测试）
launchctl start com.quant.daily
```

**定时规则**：周一至周五 16:30（A 股收盘后 30 分钟，港股收盘后 3 小时，足够获取快照）

## 第 4 步：日常操作

**每日应该做的事**：
1. 16:30 自动跑 `run_daily.sh`（无需手动）
2. 检查 `report/strategy_report_YYYY-MM-DD.html` 生成的报告
3. A 股账户：按报告建议下单（T+1 买卖）
4. HK 账户：按报告建议下单
5. 检查 `logs/` 目录无异常错误

**每月第一天**：
1. 计算各账户上月 YTD Sharpe
2. 计算组合 Sharpe（按 25/25/15/15/20 权重）
3. 与回测基准 1.225 对比

## 第 5 步：风控触发动作

| 触发条件 | 行动 |
|---|---|
| A 股账户 DD > 15% | 暂停该策略 new buys，等 MA 恢复 |
| HK 账户 DD > 15% | 同上 |
| 连续 2 周无任何入场信号 | 检查数据源 / akshare 可用性 |
| 组合 Sharpe < 0.5 连续 3 月 | 暂停全部策略，回测验证 |
| launchd job crash | `launchctl list com.quant.daily` 确认，手动重跑 |

## 第 6 步：季度再平衡

**时间**：3 / 6 / 9 / 12 月最后一个交易日

**操作**：
```
计算各账户市值占比
if |current_w - target_w| > 0.05:
    从超配账户出金 → 入金到 low 配账户
```

**target**: HK 25% / A_mom 25% / A_mr 15% / QQQ 15% / GLD 20%

## 紧急停盘

1. `launchctl unload ~/Library/LaunchAgents/com.quant.daily.plist`
2. 清空所有 pending orders
3. 回测验证当前市场参数
4. 恢复 `launchctl load ~/Library/LaunchAgents/com.quant.daily.plist`

## 联系方式 / 资源

- GitHub: https://github.com/Tanglaoye-future/quant_system
- 回测结果: `data/backtest/`
- 部署计划: `memory/deployment_plan_2026-05.md`
- 策略分析: `memory/` 目录下所有文件

**Why:** 2026-05-15 实盘启动前的操作清单，确保每周部署进展可用。按「测试盘必须先赢」原则，所有启动前置条件已满足（8年回测 Sharpe 1.225）。
**How to apply:** 按 Step 0-6 顺序执行。每天查看 HTML 报告。每季度做一次再平衡。
