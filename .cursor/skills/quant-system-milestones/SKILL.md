---
name: quant-system-milestones
disable-model-invocation: false
description: >-
  Quant system (quant_system) roadmap M0–M终、整体目标与按里程碑的代码审计标准。
  Auto-relevant in this repo for strategy, backtest, daily_run, DataLoader, universe filter, timing/M2,
  config.yaml, diagnostics, M0/M1/M2/M3, 验收, 无黑盒, 可追溯, 无未来函数, audit_m0_outputs.
---

# Quant system — 里程碑与审计 Skill

## 何时使用

- 用户要改策略、universe、择时、回测输出、准入门槛或 `config.yaml`。
- 用户提到某 **M 节点**、验收、压测、无未来函数、可追溯、审计。
- 实现新功能前：先对照本 skill 判断属于哪一节 M，再查 **审计标准**。

## 项目整体目标（不可妥协）

1. **绩效方向（研究目标，不是单次回测硬凑）**  
   - 胜率 **> 45%**、Sharpe **> 0.8** 作为长期目标；通过 **样本外 / 多区间 / 全市场对照** 验证，禁止单靠一段短区间曲线拟合。

2. **科学与合规**  
   - **无未来函数**：财务、公告、指数、量价用于决策时，一律 **`<= asof` 截断**；raw 价等配置与文档一致。  
   - **无黑盒**：关键决策必须有 **可落盘、可复跑** 的中间产物（见 M0）。

3. **工程**  
   - **可复现**：同 config + 同缓存策略 + 同代码版本 → 同一 `run_id` 语义下的产物可对照。  
   - **配置可追溯**：`config.yaml` 里每个被采纳的字段必须在代码中有 **读者与生效路径**；禁止“装饰性配置”。

4. **运行边界**  
   - `deploy.sh` / 云端与本仓库的边界以项目既有规则为准；本 skill 聚焦 **研究与回测流水线**。

---

## 已证伪路径（不要重做）

下面方向 **已实验完整，结论 negative**。再有人问类似需求，先把 memory 链接发过去，再讨论是否值得做不同的路径。

### 美股 momentum 中线选股
- **NASDAQ100 等权 momentum-only**：4y Sharpe -0.22 / FAIL（[[equity_us_momentum.yaml]] DEPRECATED 注释）
- **NASDAQ100 + yfinance fundamentals 数据接入**：4y 不变 -0.22，因策略 yaml 把 fundamentals 权重故意全 0（[[us_fundamentals_yfinance_2026-05]]）
- **SP500 universe + quality 因子 (roe/fcf_yield) 重设权重**：4y Sharpe -0.18 / 胜率 37.5% / FAIL，胜率反而比 NASDAQ100 (42.5%) 降 5pp（[[sp500_negative_2026-05]]）

**已经被证明的根因**：等权 + ATR trail stop + 中线持仓在美股 2022-2026 大盘成长占主导环境**结构性失效**，跟 universe 大小 / fundamentals 接入无关。后续若要做美股 momentum 必须改架构：市值加权 / 年度持有 / regime filter，或缩窄到 top-20 by mkt cap。

### HK 庄股策略数据接入
- **akshare HK + yfinance HK fundamentals**：网络阻塞 + 缺换手率 + 历史市值（survivorship bias）；架构占位保留但实盘退回（[[zhuang_hk_research_2026-05]]）

---

## 里程碑一览（M0 → M终）

| 节点 | 定义（“长什么样”） | 当前仓库锚点（实现时以 grep 为准） |
|------|-------------------|-------------------------------------|
| **M0** | **观测与验收面**：固定 **输出目录**（`data/backtest/<strategy>_<market>_<start>_<end>/`）、`metrics.json`、universe 样例、**候选/排序/退出决策/原因汇总** 等诊断文件齐全；可脚本审计。 | `scripts/backtest.py`、`quant_system/engine/backtest.py`（`BacktestDiagnostics`）、`scripts/audit_m0_outputs.py` |
| **M1** | **可交易 universe**：流动性/市值/价/ROE/负债/上市天数/停牌/涨跌停等 **硬过滤**；**按 asof** 统计 `output_n`、缺失率、逐规则剔除数；接入 `BottomupTimingStrategy` 后再 enrich。 | `quant_system/universe/filter.py`、`quant_system/engine/strategy.py`、`quant_system/data/loader.py`（含债务率 THS 窄表缓存） |
| **M2** | **市况 + 单票质量门**：指数层 **允许开新仓**；单票层 **RSI 带 ATR 微调**、可选 **收阳/中位量**、**结构突破**；全部走 `strategy.timing`。 | `quant_system/timing/regime.py`、`quant_system/timing/signals.py`（`TimingConfig` + `timing_config_from_yaml_node`）、`config.yaml` → `strategy.timing` |
| **M3** | **择时深化**：RSI 带宽与市况/波动 **显式联动**、多周期 RSI 一致性（在 M2 之上演进）。 | `quant_system/timing/signals.py`（`m3_*`、`TimingRegimeContext` 消费）、`quant_system/timing/regime.py`（`build_timing_regime_context`）、`config.yaml` → `strategy.timing` |
| **M4** | **因子与组合**：因子离散度惩罚、换手惩罚、回测内 **行业 / 新开仓风险预算** 约束；从纯排序到组合入口。 | `quant_system/bottomup/factors.py`、`quant_system/bottomup/portfolio.py`、`engine/strategy.py`、`engine/backtest.py`、`config.yaml` → `factors.m4` |
| **M5** | **退出与风控闭环**：`exit_layer` 分层（`exit_taxonomy.py`）、可选市况强制平仓（`m5_regime_exit_enabled`）；与 `exit_events` / `trades.exit_reason` / `exit_reason_summary` 一致；`RiskMonitor` 与回测同路径。 | `timing/exit_taxonomy.py`、`signals.py`、`engine/strategy.py`、`engine/backtest.py`、`risk/monitor.py`、`scripts/backtest.py` |
| **M终** | 研究 / 回测 / 准入 / `daily_run` **脚本边界清晰**；重大变更必有 **回归区间 + 审计记录**。 | `scripts/daily_run.py`、`scripts/backtest.py`、`scripts/run_acceptance.ps1`（`pytest` + 提示 M0 审计）、CI/测试策略（以仓库实际为准） |

---

## 按里程碑的代码审计标准

### 通用（每一 diff 都过）

- **因果链**：谁写配置、谁读、谁执行、错值会怎样——说不清则 **不合并**。  
- **asof**：凡“报告期/公告日/财务列名日期”，必须证明 **`<= asof`** 才进入信号。  
- **性能与 IO**：全市场路径禁止无界重复读盘；大循环要有 **缓存或批处理** 意识。  
- **测试**：以仓库约定为准（有 `tests/` 则改策略核心逻辑应补或跑现有测）。

### M0 审计

- **产物**：一次回测是否在 `data/backtest/<strategy>_<start>_<end>/<run_id>/` 下具备 `metrics.json`、`universe_filter_stats_sample.json`、`universe_filtered_sample.csv`、`equity.csv`、`positions.csv`、`entry_candidates.csv`、`ranking.csv`、`exit_events.csv`、`exit_reason_summary.json`（`trades.csv` 可无成交时缺失需约定一致）。  
- **自动化**：`python scripts/audit_m0_outputs.py <run_dir>` 必须 **PASS**。  
- **列契约**：CSV 列名变更视为 **破坏性变更**，需同步审计脚本与任何消费方。  
- **`exit_events.csv`**：须含 `exit_layer`（与 `reason` 字符串经 `exit_layer_from_reason` 一致）。  
- **`exit_reason_summary.json`**：须含 `closed_trades_by_exit_layer`、`exit_events_by_exit_layer`（按层聚合；空层不出现在 dict 中可接受）。

### M5 审计

- **分层**：技术出场与 `m5_regime_exit` / 末日强平等理由均能映射到稳定 `exit_layer` 枚举。  
- **配置**：`m5_regime_exit_enabled` 在 `timing_config_from_yaml_node` → `TimingConfig` → `BottomupTimingStrategy.evaluate` 生效；关闭时不改变仅技术出场路径。  
- **对齐**：`exit_signal` / `exit_signal_from_enriched` 与 `RiskMonitor.daily_check` 均带 `exit_layer`；`PositionRisk.exit_layer` 可供 `daily_run` 展示。

### M1 审计

- **统计诚实**：`universe_filter_stats_sample.json` 中 `input_n` / `output_n` / `missing_*` 与 CSV 行数 **一致**。  
- **债务/ROE/市值**：数据源、单位、**缺失是否硬剔除** 与 `UniverseFilterConfig` 语义一致。  
- **涨跌停池**：日期格式、`asof` 与池接口一致；失败时有明确 **空表/降级** 行为且不静默吞异常导致全通过。

### M2 审计

- **配置**：`strategy.timing` 中每个 `m2_*` 字段必须在 `timing_config_from_yaml_node` → `TimingConfig` → **regime 或 entry 路径** 中生效；关掉开关时行为与 M2 前 **可预期**。  
- **市况门**：仅用 **`date <= asof`** 的指数序列；禁止用全样本 future MA。  
- **双路径**：`entry_signal` 与 `entry_signal_from_enriched` 对 **M2 单票规则** 保持一致（或文档声明仅一条路径用于生产）。  
- **daily_run 与 backtest**：同一 `tcfg` 与市况门逻辑 **对齐**。

### M3+ 审计

- **配置**：`strategy.timing` 中每个 `m3_*` 字段须在 `timing_config_from_yaml_node` → `TimingConfig` → **`_effective_rsi_entry_band` / `enrich` / 入场双路径`** 或 **`build_timing_regime_context`** 中有读者；关开关时行为可预期。
- **市况上下文**：仅用 `date <= asof` 的指数序列；与 `m2_regime_ma_days`、基准指数对齐。
- **双路径**：`entry_signal` 与 `entry_signal_from_enriched` 对 **M3 规则** 保持一致。
- 每加一层门控，须同步 **配置说明**（`reference.md`）、必要时 **M0 漏斗**、**短回测对照**。

### M4 审计

- **配置**：`factors.m4` 每个 `m4_*` 须在 `m4_config_from_yaml` → `M4Config` → **`score_universe` / `BottomupTimingStrategy.screen` / `m4_prioritize_signals`** 或 **`get_a_share_industry_map`** 中有读者。
- **行业映射**：整表缓存、失败降级为空（行业上限自动不生效），禁止静默当成「全行业同一类」。
- **回测一致性**：`m4_prioritize_signals` 在 `pending_buys` 入队前调用，与 `slots` 截取逻辑一致。

---

## 建议的 Agent 工作流

1. 读用户请求 → 映射到 **M 节点**。  
2. 改代码前打开相关模块与 **`config.yaml`**。  
3. 改完后：本地可跑 **`scripts/run_acceptance.ps1`**（全量 `pytest`）；至少 **短回测** + **`audit_m0_outputs.py <run_dir>`**（目录为固定 `strategy_market_start_end`，无 `run_id`）。  
4. 在回复中写清：**触达哪一节 M、验收命令、输出目录**。

## 延伸阅读

- 更细的检查项与命令模板：同目录 [reference.md](reference.md)。
