---
name: trend-scan-pivot-2026-06-12
description: 2026-06-12 策略全面转向趋势交易 — 关停 SP500/A_mr/NASDAQ100，新建三市场纯量价全扫描策略
metadata:
  type: project
---

## 决策

用户确认："真正能稳定挣钱的交易只有趋势交易和套利交易，硬件不支持套利，全面转向趋势交易。扫描市场里所有股票。"

## 关停（已落地）

| 策略 | 状态 | 原因 |
|---|---|---|
| equity_sp500_momentum | `enabled: false` | 4y Sharpe -0.18 |
| equity_us_momentum (NASDAQ100) | 已是 `false` | 8y Sharpe -0.05 |
| A_mr mean_reversion | cells.yaml 标记 `deprecated` | 8y Sharpe ~0 纯噪音 |

## 新建（已落地）

### 纯量价打分快速通道

`bottomup/factors.py` — `compute_raw_factors_pv()` + `PV_FACTOR_WEIGHTS`：
- `momentum_3m` (0.30) — 60 日价格动量
- `momentum_6m` (0.25) — 120 日价格动量
- `vol_adj_momentum` (0.25) — 动量 / 60 日年化波动率
- `trend_strength` (0.20) — close / MA60 − 1

零基本面 API 调用。`score_universe()` 新增 `pure_pv` 参数。

### 全市场 universe

`DataLoader.get_universe(name="all")` 三市场支持：
- A 股：扫描 `data/prices/` 3866 个 CSV（zhuang 已预热）
- 港股：`ak.stock_hk_spot_em()`
- 美股：`ak.stock_us_spot_em()`

`get_daily()` A 股新增 CSV fallback（`data/prices/{code}_daily.csv`），避免 akshare 网络依赖。

### 三策略配置

`config/strategies/equity_trend_scan_a.yaml` — A 股全扫描，MA60 门控，沿用 L9-A 出场参数
`config/strategies/equity_trend_scan_hk.yaml` — 港股全扫描，MA200 门控，tp_runner
`config/strategies/equity_trend_scan_us.yaml` — 美股全扫描，MA200 门控

三者 `capital_pct: 0.00`，待回测验收后调整。

### 数据预取

`scripts/prefetch/prefetch_hk_all.py` + `prefetch_us_all.py`

### 测试

123/123 pytest 通过（`test_deployments_multi_market` 更新适配新部署）

## 已知限制

- **回测速度**：`UniverseFilter.filter_a_share()` 对全市场仍会调用基本面 API（PE/PB/ROE），3866 只需数小时。建议 `nohup` 过夜跑。
- **港股/美股**：需先跑 prefetch 下载数据。

## 为什么不直接关 hs300/hs100 限定版

`equity_momentum` / `equity_hk_momentum` 保留 enabled=true 作为对照，待全扫描版回测通过后再决定去留。

## 相关

[[deployment_plan_2026-05]] — 已更新 A_mr 停用 + 趋势转向声明
[[cells.yaml]] — 新增 `equity_mean_reversion × a_share deprecated`
