---
name: us-fundamentals-yfinance-2026-05
description: 2026-05-26 US fundamentals via yfinance 接入 — 数据层 ready (93/93 ticker)，但策略 yaml 故意全 0 权重导致回测不变；HK daily 参数 bug 同步修复
metadata:
  type: project
---

## 同时落地的两件事

### 1. HK daily 参数 bug 修复

**问题**：`deploy/run_daily.sh:70` 旧调用 `--strategy bottomup_timing --market hk_share`，走 `config.py:resolve_strategy` legacy 分支 → `strategy_name=None` → `resolve_strategy_params` 回退到 `markets[hk_share]`（仅 universe/benchmark），完全忽略 `config/strategies/equity_hk_momentum.yaml` 调好的因子权重 (pe=0/pb=0/roe=0.3/momentum 主信号) 和 hedge ratio 0.3 等参数。HK 在 daily 跑了几个月但跑的是 A 股默认参数。

**修复**：`deploy/run_daily.sh` 新增 `run_equity_named()` helper，HK + A momentum 切到 `--strategy <name>` 主索引调用：
- `run_equity_named "equity_hk_momentum" "HK_momentum"`
- `run_equity_named "equity_momentum"    "A_momentum"`
- mean_reversion 暂保留 legacy（还没迁 strategy 名）

**验证**：手跑 `bash deploy/run_daily.sh --no-options` HK 日志显示 `M2市况门: 收盘 7146.40 <= MA200 7427.44`，证明拿到了 `equity_hk_momentum.yaml:19` 的 `m2_regime_ma_days: 200`（旧路径会用 A 股默认 MA60）。

### 2. US fundamentals via yfinance 接入

**新增方法**：`src/quant_system/strategies/equity_factor/data/loader.py`
- `get_us_financial_indicator(code) -> pd.DataFrame`：拉 yfinance `.financials` / `.balance_sheet` / `.cashflow`，输出 6 列 [report_date, eps_ttm, bps, roe_avg, revenue_yoy, fcf_per_share]
- `latest_us_indicator(df, col, asof, publication_lag_days=60)`：60 天 SEC 10-K 滞后（HK 用 90 天）

**factors.py**：`bottomup/factors.py:compute_raw_factors` 新增 `us_share` branch，复用 HK 模式；`fcf_yield` 守卫从 `a_share` only 扩展到 `("a_share", "us_share")`。

**数据质量**：93/93 NASDAQ100 ticker cache 落地（`data/cache/us_fin_*.parquet`），无空文件。AAPL 样本 5 年年度数据值合理（EPS 6.0-7.5 / ROE 1.5-2.0 受股本回购拉高 / FCF/share ~7$）。yfinance 5 年限制使 2018-2020 段 NaN（影响 8y 回测，4y 起 2022 完整覆盖）。

**测试**：`tests/equity_factor/test_us_fundamentals.py` 10/10 通过；全套 `tests/equity_factor/` 46/46 通过。

## 关键发现：fundamentals 接入未改变 US 4y 回测

**baseline**: equity_us_momentum × us_share 4y (2022-01-01 → 2026-05-25)
- 接入前：Sharpe -0.22 / DD -24.83% / 273 trades / FAIL
- 接入后：Sharpe -0.22 / DD -24.83% / 273 trades / FAIL **（完全一致）**

**根因**：`config/strategies/equity_us_momentum.yaml:53-62` 因子权重：
```yaml
pe_inverse: 0.0    # 注释 "高 PE 成长股，估值因子反效"
pb_inverse: 0.0
roe: 0.0
revenue_growth: 0.0
momentum_3m: 0.50
momentum_6m: 0.50
fcf_yield: 0.0
```

策略文件**显式把所有 fundamentals 权重设 0**，仅保留 momentum_3m/6m。fundamentals 数据虽已接入 factors dict，但 z-score 加权时 × 0 不参与 score 计算，因此回测不变。

**原作者结论（注释中）**：8y Sharpe -0.05 vs QQQ 被动 +241%，归因于 NASDAQ100 MAG7 集中市等权 momentum 失效；实盘改用 QQQ ETF 被动持有。

## 待决策（用户拍板）

1. 试 quality 因子组合（roe + fcf_yield 0.20 + momentum 0.30/0.30）跑 4y sweep
2. 换 universe SP500 / Russell1000（需新增 prefetch + 成分股 csv）
3. 维持现状：fundamentals 接入留作后续实验基础设施，不动 us yaml

**Why**: 用户想"中线 momentum 美股每日自动运行"。当前 4y FAIL 不达 admission，自动跑会产生负 PnL 信号；fundamentals 接入是必要前提但非充分条件。
**How to apply**: 若用户选 1 → 跑 sweep，winner 双窗口验证后 AskUserQuestion 是否落 yaml；若用户选 3 → 工程基建保留，未来回到 US 时不必再接数据层.

## 不动清单

- `equity_us_momentum.yaml` 任何字段（用户拍板才动）
- `equity_momentum.yaml` / `equity_hk_momentum.yaml`（算法层已调好）
- `daily_equity.py` / 其他 daily 脚本

## 顺手观察

- `logs/launchd_stderr.log` 全 `Operation not permitted`（最后成功 2026-05-15）；macOS 需用户手工给 `/bin/bash` Full Disk Access 才能恢复 launchd 调度
- HK daily 风控显示持有 601939 / 601066 两个 **A 股代码**——journal 跨 market 隔离 bug，超本任务 scope 但需后续修
- 反复出现的 `venv/lib/.../site-packages/*.pth` 被设 UF_HIDDEN 导致 `import quant_system` 失败：每次 launchd / shell 任务后都要 `chflags -R nohidden venv/lib/python3.14/site-packages/`。详见 [[feedback_venv_naming]]，但 `venv/` 不带 dot 仍复发，说明 feedback memory 的"venv/ 就修了"结论需要更新

**Why**: 完整记录这次工程改动的边界 + 决策点 + 暴露的 side bug，避免后续重复踩坑.
**How to apply**: 后续若决定试 quality 权重，从 `data/cache/us_fin_*.parquet` 已 ready；若放弃 US，loader 和 factors.py 的 us 路径保留无害（branch 仅在 market="us_share" 时触发）.
