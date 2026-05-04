# Quant system milestones — reference

本仓库通过 **`.cursor/rules/quant-system-milestones.mdc`**（`alwaysApply: true`）在每次会话中提示 Agent 阅读 `SKILL.md`；Skill 的 frontmatter 已设置 **`disable-model-invocation: false`** 以便与仓库上下文匹配时由模型加载。

## 常用命令

```text
# 单元测试（M终）
powershell -File scripts/run_acceptance.ps1

# HS300 短回测（验收优先；输出目录固定，会覆盖同区间旧结果）
python scripts/backtest.py --start 2026-01-01 --end 2026-02-28 --refresh-days 999

# M0 产物审计（路径无 run_id 子目录；须为当前脚本版本生成）
python scripts/audit_m0_outputs.py data/backtest/<strategy>_<market>_<start>_<end>
```

## M0 文件契约（审计脚本对齐）

| 文件 | 必需列或键 |
|------|------------|
| `entry_candidates.csv` | `screen_date`, `factor_rank`, `symbol`, `factor_score`, `queued_for_buy` |
| `ranking.csv` | `screen_date`, `rank`, `symbol`, `score` |
| `exit_events.csv` | `decision_date`, `symbol`, `reason`, `event`, **`exit_layer`** |
| `exit_reason_summary.json` | 可解析 object；含 `closed_trades_by_exit_reason`、`exit_events_by_reason`、**`closed_trades_by_exit_layer`**、**`exit_events_by_exit_layer`** |
| `metrics.json` | `metrics`, `admission_pass` |

## 配置入口速查

| 区域 | 用途 |
|------|------|
| `data.*` | 缓存目录、`price_adjust` |
| `markets.*.universe` | 仅 **`hs300`**（A）/ **`hs100`**（恒生 **HSCHK100**，成份见 `data.hang_seng_indexes`） |
| `data.hang_seng_indexes` | 港股：`full_constituents_csv` / `allow_factsheet_top50_only`、`hk_constituent_daily_dir`、`hschk100_index_daily_csv`（`hang_seng_indexes.py`） |
| `strategy.timing` | 择时 + **M2**（`m2_*`）+ **M3**（`m3_*`）+ **M5**（`m5_regime_exit_enabled`）；`timing_config_from_yaml_node` |
| `factors.m4` | **M4**：`m4_config_from_yaml` → `M4Config`；离散度/换手见 `factors.py` + `strategy`；行业/风险预算见 `portfolio.m4_prioritize_signals` + `loader.get_a_share_industry_map` |
| `backtest.benchmark_symbol` | A 股默认回测基准；港股优先用 **`markets.<market>.benchmark`**（如 `HSCHK100`） |

## M2 字段语义（审计时核对）

- `m2_regime_enabled`：为 true 时，`BottomupTimingStrategy.screen` / `daily_run` 在扫票前先过 `MarketRegimeGate`。  
- `m2_regime_ma_days`：指数收盘与 SMA 比较窗口。  
- `m2_rsi_atr_adjust` / `m2_rsi_atr_k` / `m2_rsi_atr_cap`：入场 RSI 上下轨随 ATR% 微调。  
- `m2_vol_green_bar`：要求收阳。  
- `m2_vol_median_mult`：`<=1` 关闭与近端中位量比较。  
- `m2_structure_lookback` / `m2_structure_eps`：收盘相对前 N 日最高收盘的突破缓冲。

## M3 字段语义（`timing.regime` + `timing.signals`）

- `m3_regime_rsi_band`：为 true 且传入 `TimingRegimeContext` 时，在 M2 ATR 微调之后再按指数 **高于 SMA 的幅度** 放宽 RSI 下沿（有 cap）。
- `m3_reg_vol_tighten_hi`：为 true 且 `index_atr_pct_rel>0` 时，按指数波动 **相对近端中位 ATR%** 收紧 RSI 上沿（有 cap）。
- `m3_reg_index_atr_pct_median_window`：`build_timing_regime_context` 中计算 `index_atr_pct_rel` 的 rolling median 窗口。
- `m3_mtf_rsi_enabled` / `m3_mtf_rsi_period` / `m3_mtf_rsi_min`：`enrich` 增加慢周期 RSI，入场要求 **快 RSI 在带内** 且 **慢 RSI ≥ min**（与 `entry_signal` / `entry_signal_from_enriched` 双路径一致）。
- 回测 / `daily_run`：A 股下由 `build_timing_regime_context(loader, benchmark, asof, m2_regime_ma_days, …)` 构造上下文；`BottomupTimingStrategy.screen` 与 `scan_today_entries` 对齐传入。

## M4 字段语义（`factors` + `portfolio` + `backtest`）

- `m4_factor_dispersion_lambda`：`score_universe` 内对加权总分减去 `lambda * std(z_filled)`，抑制多因子 z 分歧过大的名字。
- `m4_turnover_penalty` / `m4_turnover_top_n`：`BottomupTimingStrategy.screen` 内对「未出现在上一屏 topN」的命中扣分并重排；`top_n` 与 penalty 同时为 0 等价关闭。
- `m4_enabled`：为 true 时，`Backtester` 在入 `pending_buys` 前调用 `m4_prioritize_signals`，按 **行业上限** 与 **当日新开仓风险预算** 把可行信号排到列表前部。
- `m4_max_same_industry`：统计已持仓 + `pending_buys` + 当日已接受信号的行业数；需 `get_a_share_industry_map` 非空，否则该约束自动跳过（避免误杀）。
- `m4_new_risk_budget_frac`：当日新接受信号 `(entry-stop)/entry` 之和上限；单票无止损时该项贡献为 0。

## M5 字段语义（`timing.exit_taxonomy` + `signals` + `strategy.evaluate`）

- `m5_regime_exit_enabled`：为 true 且 A 股时，技术出场未触发则复用 `MarketRegimeGate.allows_long_entries(asof)`；不通过则 `EXIT`，`reason` 前缀 `m5_regime_exit:`，`exit_layer`=`REGIME`。依赖与开仓相同的指数序列与 `m2_regime_ma_days`。  
- **`exit_layer`**：`exit_layer_from_reason(reason)` 产出 `STOP_TRAIL` / `STOP_TREND` / `TAKE_PROFIT` / `OVERBOUGHT` / `TIME_STOP` / `REGIME` / `FORCED_CLOSE` / `OTHER`；非出场决策为空串。

## 反模式（审计一票否决）

- 新增 `config.yaml` 字段但 **grep 不到读者**。  
- 用未截断的财务/公告日期做回测决策。  
- 全市场循环内 **每票网络请求**且无缓存键。  
- 改 `entry_signal_from_enriched` 却忘记 **`entry_signal`**（或反之）且无文档说明。
