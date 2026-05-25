# quant_system

多策略量化交易 monorepo：

| 子策略 | 标的 | 风格 | 入口 |
|---|---|---|---|
| **equity_factor** | A 股 / 港股 / 美股 | bottom-up 因子选股 + 择时（中长线） | `scripts/daily/daily_equity.py` |
| **options** | QQQ | Bull Call Spread（IBKR） | `scripts/daily/daily_options.py` |
| **zhuang** | A 股 | 庄股吃货期扫描 | `scripts/daily/daily_zhuang.py` |

每日盘后由 `deploy/run_daily.sh` 串行运行三策略，再用 `quant_system.report.builder` 合成一份 HTML 日报。

## 目录结构

```
.
├── src/quant_system/
│   ├── config.py             # 顶层配置加载（PROJECT_ROOT、load_config）
│   ├── strategies/
│   │   ├── equity_factor/    # 中长线因子选股 + 择时
│   │   │   ├── bottomup/     # 因子打分、组合构建
│   │   │   ├── catalyst/     # 催化剂监控
│   │   │   ├── data/         # 行情/指数/成分股加载
│   │   │   ├── engine/       # 回测引擎、绩效指标
│   │   │   ├── journal/      # 交易日志
│   │   │   ├── risk/         # 风控
│   │   │   ├── timing/       # 择时信号、市场状态
│   │   │   ├── topdown/      # 宏观
│   │   │   └── universe/     # 股票池过滤
│   │   ├── options/          # 期权（QQQ Bull Call Spread）
│   │   │   ├── broker/       # IBKR 客户端
│   │   │   ├── engine/       # 持仓监控
│   │   │   ├── iv/           # IV Rank 引擎
│   │   │   ├── signals/      # 动量信号、价差选择器
│   │   │   └── utils/        # 显示辅助
│   │   └── zhuang/           # 庄股吃货期
│   │       ├── data/         # baostock 加载
│   │       ├── engine/       # 回测、仓位、指标
│   │       └── signals/      # 入场/出场/吸筹评分
│   └── report/
│       └── builder.py        # 合并三策略 JSON → HTML 日报
├── scripts/
│   ├── daily/                # 日跑入口：daily_equity / daily_options / daily_zhuang
│   ├── backtest/             # 回测：backtest.py / backtest_zhuang.py / run_experiment_zhuang.py / audit
│   ├── prefetch/             # 行情预取（A / HK / US）
│   ├── demo/                 # M0–M5 验收示例
│   └── powershell/           # Windows acceptance 脚本
├── config/
│   ├── equity_factor.yaml
│   ├── options.yaml
│   └── zhuang.yaml
├── deploy/
│   ├── com.quant.daily.plist # launchd（macOS 每工作日 16:30）
│   └── run_daily.sh          # 联合运行脚本
├── docs/                     # 历史对话与终端记录
├── memory/                   # Claude Code 持久记忆（session 启动自动读取）
├── tests/
│   ├── equity_factor/
│   ├── options/
│   └── zhuang/
├── data/                     # 行情缓存与 backtest 输出（runtime，大部分 gitignored）
├── pyproject.toml
├── requirements.txt
├── README.md
└── CLAUDE.md                 # Claude Code 项目规则
```

## 安装

```bash
python3 -m venv venv      # 注意：用 venv/ 而非 .venv/ —— macOS 对 dot-prefixed 目录自动设 UF_HIDDEN，Python 3.14 site.py 会跳过其下 .pth 文件导致 editable install 失效
source venv/bin/activate
pip install -e ".[dev]"
```

装好后 `from quant_system.strategies.equity_factor.timing.signals import ...` 直接可用，所有脚本无需 `sys.path` 注入。

## 日常使用

```bash
# 单策略日跑
python scripts/daily/daily_equity.py  --market a_share --strategy bottomup_timing
python scripts/daily/daily_options.py --no-ibkr
python scripts/daily/daily_zhuang.py  --top 15 --min-score 45

# 五策略联跑 + HTML 报告
bash deploy/run_daily.sh

# 仅生成报告（已有 JSON 时）
bash deploy/run_daily.sh --report-only

# equity_factor 短回测
python scripts/backtest/backtest.py --start 2026-01-01 --end 2026-02-28

# zhuang 回测
python scripts/backtest/backtest_zhuang.py --config config/zhuang.yaml

# 测试
pytest
```

## 部署（macOS launchd）

```bash
cp deploy/com.quant.daily.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.quant.daily.plist 2>/dev/null
launchctl load   ~/Library/LaunchAgents/com.quant.daily.plist
```

每个工作日 16:30 自动执行。日志在 `logs/`，报告在 `report/strategy_report_<date>.html`。
