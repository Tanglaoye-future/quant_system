# quant_system

多市场（A 股 / 港股 / 美股）量化策略系统：bottom-up 选股 + 择时 + 风控。

## 目录结构

```
.
├── src/quant_system/    # Python 包（核心库）
│   ├── bottomup/        # 因子打分、组合构建
│   ├── catalyst/        # 催化剂监控
│   ├── data/            # 行情/指数/成分股加载
│   ├── engine/          # 回测引擎、绩效指标
│   ├── journal/         # 交易日志
│   ├── risk/            # 风控
│   ├── timing/          # 择时信号、市场状态
│   ├── topdown/         # 宏观
│   └── universe/        # 股票池过滤
├── scripts/
│   ├── daily/           # 日报流水线（生产）
│   ├── backtest/        # 回测、产物审计
│   ├── prefetch/        # 行情预取（A/HK/US）
│   ├── demo/            # M0–M5 验收示例
│   └── powershell/      # Windows acceptance 脚本
├── report/              # HTML 报告生成器（builder.py），运行时数据 gitignored
├── deploy/              # launchd plist + run_daily.sh
├── docs/                # 历史对话、笔记
├── memory/              # Claude Code 持久记忆（每次 session 自动读取）
├── tests/               # pytest
├── data/                # 行情缓存与 backtest 输出（大部分 gitignored）
├── config.yaml          # 主配置
├── pyproject.toml       # 包元数据
└── CLAUDE.md            # Claude Code 项目规则
```

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -e ".[dev]"   # 含 pytest
```

`pip install -e .` 后，所有脚本可以直接 `from quant_system.xxx import ...`，无需 `sys.path` 注入。

## 日常使用

```bash
# 单策略日跑
python scripts/daily/daily_run.py --market a_share --strategy bottomup_timing

# 三策略联跑 + 生成 HTML 报告
bash deploy/run_daily.sh

# 短回测验收
python scripts/backtest/backtest.py --start 2026-01-01 --end 2026-02-28

# M0 产物审计
python scripts/backtest/audit_m0_outputs.py data/backtest/<strategy>_<market>_<start>_<end>

# 测试
pytest
```

## 部署（macOS launchd）

```bash
cp deploy/com.quant.daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.quant.daily.plist
```

每个工作日 16:30 自动执行。
