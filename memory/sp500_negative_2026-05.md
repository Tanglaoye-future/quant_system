---
name: sp500-negative-2026-05
description: 2026-05-27 SP500 universe + quality 因子组合 4y FAIL，证明换 universe 救不了美股 momentum 策略；问题在策略而非 universe
metadata:
  type: project
---

## 实验背景

接上 [[us_fundamentals_yfinance_2026-05]]：US fundamentals 接入完成但 yaml 权重故意全 0，4y Sharpe -0.22 不变。用户选定方向"换 universe 到 SP500"，预期 SP500 503 ticker 比 NASDAQ100 MAG7 集中更宽，等权 momentum + quality 因子有机会做出 alpha。

## 工程改动（已落地）

| 文件 | 改动 |
|---|---|
| `scripts/prefetch/prefetch_sp500_universe.py` | 新文件：GitHub 镜像拉 503 成分股 + akshare 日线 + SPY ETF (SPX 代理)；501/503 成功，BRK-B / BF-B 因 akshare 不接受 berkshire 类股两个失败 |
| `src/quant_system/strategies/equity_factor/data/loader.py` | DataLoader 加 `us_universe` 参数；`_us_paths()` 根据 universe 切换 `sp500_*` 字段；`get_universe(us_share, sp500)` 支持；`get_daily` us_share 加 nasdaq100 dir fallback；`get_index_daily("SPX")` 支持 |
| `src/quant_system/config.py` | `_assemble_split` 允许 strategy deployment 覆盖 market 默认 universe + benchmark |
| `scripts/backtest/backtest.py` + `scripts/daily/daily_equity.py` | DataLoader 创建时传 `us_universe=market_cfg.get("universe")` |
| `config/markets/us_share.yaml` | 加 `sp500_daily_dir` / `sp500_index_daily_csv` / `sp500_constituents_csv` 字段 |
| `config/strategies/equity_sp500_momentum.yaml` | 新文件：universe=sp500, benchmark=SPX, factors (pe 0.10, pb 0.05, roe 0.20, fcf_yield 0.15, momentum 0.20/0.20) |
| `config/equity_factor.yaml` | strategies 列表加 equity_sp500_momentum |
| `tests/equity_factor/test_deployments_multi_market.py` | 更新 us_share 期望从 equity_us_momentum 改为 equity_sp500_momentum (后者是首个 enabled) |

数据基建完整：`data/sp500_prices/` 501 ticker × 8y 日线 + SPX 指数；`data/cache/us_fin_*.parquet` ~503 ticker fundamentals (Apple AAPL 等数据样本合理)。

## 关键负结果

`equity_sp500_momentum × us_share/sp500` 4y (2022-01-01 → 2026-05-25):

| 指标 | SP500 实测 | NASDAQ100 baseline | 评价 |
|---|---|---|---|
| Sharpe | **-0.18** | -0.22 | 0.04 个 unit 提升，无意义 |
| 年化收益 | -1.19% | -1.74% | 略改善但仍负 |
| 最大回撤 | -22.96% | -24.83% | 2pp 改善 |
| **胜率** | **37.53%** ↓ | 42.49% | **反而下降 5pp** |
| 交易笔数 | 365 | 273 | universe 大 → 假信号更多 |
| Admission | FAIL (3/4 不达标) | FAIL (2/4) | SP500 多失一条胜率门 |

**结论：换 universe 不能救美股 momentum 策略**。SP500 503 ticker 反而引入更多噪音信号，胜率下降说明等权 momentum + ATR trail stop 这套机制在美股大盘成长占主导（2022-2026）的环境里**结构性失效**。

## 根因诊断

- 美股 2022-2026 = 熊市（'22）+ AI 大涨（'23-'24）+ 调整（'25-'26）。这种环境对**等权选股 + ATR 止损 + 30 天持仓**的中线 momentum 极不友好：
  - 强势股（NVDA / META / TSLA）大幅波动，2.5×ATR trail stop 频繁触发后又回涨 → 卖飞
  - 等权将资金分给 10 只票，错过 MAG7 集中度 alpha
  - 50%+ 大盘股是低 vol、低 beta 公司（康卡斯特、宝洁等），momentum 信号弱
- A 股策略本质是 mean-reversion-friendly + 月度切仓节奏。美股大盘成长股的反身性周期完全不同（3-6 个月趋势 vs A 股 1-2 个月切换）

## 暴露的策略局限

接下来想做美股 momentum 有几条根本性路径，**全部不是简单 universe / 因子微调能解决的**：

1. **重新设计 holding period**：把 max_hold_days 从 60-150 改到 250+ (年度持有)，stop loss 放宽到 4-5×ATR
2. **改变选股逻辑**：用市值加权（capture MAG7 集中度）而不是等权
3. **加入 macro regime filter**：QQQ MA200 + VIX 阈值组合，熊市完全不入场
4. **放弃因子选股，做被动+择时**：用 QQQ/SPY/IWM 做 mom + IV regime 切换

实际上 [[deployment_plan_2026-05]] 当前方案就是 4：QQQ 15% 被动 ETF + IV 触发期权（已经在 options 子策略里）。这套已经是验证过的美股 alpha 路径。

## 待决策

**最诚实的结论**：用户想要的"美股 momentum 中线选股每日自动跑"目前缺乏可行回测验证。建议：

A. **接受现状**：美股走 [[deployment_plan_2026-05]] QQQ 15% 被动 + options 期权信号；equity_factor 子策略不进美股 daily。fundamentals 基建保留作未来研究底座。

B. **大改策略**：放弃移植 A 股 momentum，重新设计美股专用策略（市值加权 / 年度持有 / regime filter / 等）。工程 1-2 周。

C. **缩窄 universe**：试 NASDAQ100 top-20 by market cap（MAG7 + 准 MAG7），模拟"集中持有大票"逻辑。工程 0.5 day。

**Why**: 用户最初问"为什么 momentum 不在每日自动跑"，调研后链条清晰：HK 已修参数 bug + US 数据接入证明 universe 不是瓶颈；下一层 blocker 是**策略本身在美股结构性失效**，不是工程问题.
**How to apply**: 下次美股相关需求来时，**先指向本 memory** 跳过"换 universe / 加因子"这两条已证伪路径；评估是否值得做选项 B/C，或维持 A 接受被动。

## 不动清单

- `equity_us_momentum.yaml` `enabled: false`（NASDAQ100 deprecated 不动）
- `equity_sp500_momentum.yaml` `enabled: true` 但 `capital_pct: 0.0`，daily 跑也不会下任何单（待用户决策）
- `deploy/run_daily.sh` 不加 US momentum 调用
- `equity_momentum.yaml` / `equity_hk_momentum.yaml`（已调好的 A/HK 策略）

## 顺手观察 / 副作用

- 503 ticker × yfinance fundamentals 拉完一次 ~5 min；本地 cache 503/503 都成功
- BRK-B / BF-B 两个伯克希尔类股 akshare 拒收（symbol 含 `-`），需要 yfinance 数据源备份；当前 backtester 在 try/except 里跳过，对结果影响 <0.4%
- regime_benchmark 仍是 NDX（继承自 us_share.yaml），SP500 策略 M2 门控用 NDX > MA200 跨 universe 不优雅，但能 work；理想应该用 SPX
