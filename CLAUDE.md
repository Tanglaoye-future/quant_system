# quant_system — Claude Code 项目规则

## Session 启动

**每次会话开始时，自动读取 `memory/` 下所有文件。** 这些文件是跟随 repo 的持久记忆，包含项目概览、各策略迭代历史、M0–M终里程碑审计标准，是强制性的，不可跳过。

## 项目北极星（4 根支柱硬框架）

**所有 yaml / 策略 / 架构改动前，必须 cross-check 是否落在这 4 根支柱内**。撞框架外的需求 = 默认拒绝或归档，不进 daily / 不进回测主线。完整定义见 `memory/project_north_star.md`。

1. **基本面选标的**（PE/PB/ROE/revenue_growth/...）
2. **技术面价格择时，只做趋势**（regime gate + momentum + 趋势出场）
3. **持仓中日内做 T+0 + 实时风控**（盘中告警 + 日内 T 执行）
4. **每笔完成后交易回溯和总结**（self-learning report，PM 决策不自动改 alpha）

## 项目格局

monorepo，活跃子策略 + 联合日报：

| 子策略 Python 包 | 配置 | daily 入口 | 范围 | 状态 |
|---|---|---|---|---|
| `quant_system.strategies.equity_factor` | `config/equity_factor.yaml` | `scripts/daily/daily_equity.py` | A/HK/US 因子选股 + 择时（中长线） | ✅ 在框架内 |
| `quant_system.strategies.options` | `config/options.yaml` | `scripts/daily/daily_options.py` | QQQ Bull Call Spread（IBKR） | ⚠️ 仅趋势对齐，无基本面 |
| ~~`quant_system.strategies.zhuang`~~ | ~~`config/zhuang.yaml`~~ | ~~`scripts/daily/daily_zhuang.py`~~ | ~~A 股庄股吃货期~~ | ❌ **2026-06-14 弃用**（违反支柱 1+2） |

zhuang 弃用详见 `memory/zhuang_deprecated_2026-06.md`。代码与 DB 表归档保留，daily 已跳过。

报告：`quant_system.report.builder` 读 `report/data/*.json` 出 `report/strategy_report_<date>.html`。

## 开发规范

### 改代码前

1. **先 cross-check 4 根支柱**（见上）— 不在框架内的需求默认拒绝
2. 明确改动落到 **哪个子策略包**（equity_factor / options），不要跨策略修改而不说明
3. equity_factor 的需求要映射到对应 **M 节点**（M0/M1/M2/M3/M4/M5/M终）
4. 打开对应 `config/<strategy>.yaml`，理解现有实现后再修改
5. zhuang 已弃用 — 任何 zhuang 相关需求必须先质疑"是否还要重启 zhuang"，不直接接受

### 改代码后（每次必须执行）

```bash
# 1. 单元测试（针对修改的子策略目录）
pytest tests/equity_factor/        # 或 tests/options/, tests/zhuang/

# 2. equity_factor 短回测验收
python scripts/backtest/backtest.py --start 2026-01-01 --end 2026-02-28 --refresh-days 999

# 3. M0 产物审计
python scripts/backtest/audit_m0_outputs.py data/backtest/<strategy>_<market>_<start>_<end>
```

所有门控必须通过，才算完成。

### 回复格式

每次完成代码变更后，说明：
- 触达哪个子策略 + 哪个 M 节点
- 运行了哪些验收命令
- 输出目录在哪里

## Daily 调度（2026-06-14 起 launchd 自动，迁出 Documents 后恢复）

仓库 2026-06-14 从 `~/Documents/projects/quant_system` 迁至 `~/quant_system`（详见 `memory/migration_out_of_documents_plan.md`），消除 macOS Full Disk Access (TCC) 对 launchd 的拦截。**launchd `com.quant.daily` 每个工作日 16:30 自动跑** `deploy/run_daily.sh --no-options`。

手动跑（带期权扫描 / 临时调试）：

```bash
cd ~/quant_system && ./deploy/run_daily.sh           # 含 IBKR 期权
cd ~/quant_system && ./deploy/run_daily.sh --no-options
```

launchd 状态/日志：

```bash
launchctl list | grep com.quant.daily
tail -f ~/quant_system/logs/launchd_stderr.log
```

intraday loop 从终端 nohup 起：

```bash
cd ~/quant_system && nohup venv/bin/python scripts/intraday/intraday_risk_check.py --loop &
```

## 接美股因子/策略需求前

**强制先读** `memory/sp500_negative_2026-05.md` 与 `memory/us_fundamentals_yfinance_2026-05.md`。
NASDAQ100 / SP500 / fundamentals 微调路径已实验完整 FAIL，不要重做。详见 `.cursor/skills/quant-system-milestones/SKILL.md` "已证伪路径" 段。
