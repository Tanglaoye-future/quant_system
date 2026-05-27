# quant_system — Claude Code 项目规则

## Session 启动

**每次会话开始时，自动读取 `memory/` 下所有文件。** 这些文件是跟随 repo 的持久记忆，包含项目概览、各策略迭代历史、M0–M终里程碑审计标准，是强制性的，不可跳过。

## 项目格局

monorepo，三个子策略 + 联合日报：

| 子策略 Python 包 | 配置 | daily 入口 | 范围 |
|---|---|---|---|
| `quant_system.strategies.equity_factor` | `config/equity_factor.yaml` | `scripts/daily/daily_equity.py` | A/HK/US 因子选股 + 择时（中长线） |
| `quant_system.strategies.options` | `config/options.yaml` | `scripts/daily/daily_options.py` | QQQ Bull Call Spread（IBKR） |
| `quant_system.strategies.zhuang` | `config/zhuang.yaml` | `scripts/daily/daily_zhuang.py` | A 股庄股吃货期 |

报告：`quant_system.report.builder` 读 `report/data/*.json` 出 `report/strategy_report_<date>.html`。

## 开发规范

### 改代码前

1. 明确改动落到 **哪个子策略包**（equity_factor / options / zhuang），不要跨策略修改而不说明
2. equity_factor 的需求要映射到对应 **M 节点**（M0/M1/M2/M3/M4/M5/M终）
3. 打开对应 `config/<strategy>.yaml`，理解现有实现后再修改

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

## Daily 调度（2026-05-27 起手动）

launchd 自动调度因 macOS Full Disk Access（TCC）阻塞已停用（详见 `memory/session_2026_05_27.md`）。**每天手动跑**：

```bash
cd ~/Documents/projects/quant_system && ./deploy/run_daily.sh --no-options
```

去掉 `--no-options` 会带 IBKR 期权扫描。脚本启动时自动 chflags strip macOS UF_HIDDEN flag（修 venv editable install 失效）。

## 接美股因子/策略需求前

**强制先读** `memory/sp500_negative_2026-05.md` 与 `memory/us_fundamentals_yfinance_2026-05.md`。
NASDAQ100 / SP500 / fundamentals 微调路径已实验完整 FAIL，不要重做。详见 `.cursor/skills/quant-system-milestones/SKILL.md` "已证伪路径" 段。
