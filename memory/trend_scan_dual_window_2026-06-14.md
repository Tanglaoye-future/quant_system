---
name: trend-scan-dual-window-2026-06-14
description: 2026-06-14 三市场 trend_scan 3y+8y 双窗口结果 — A/US 证伪关 enabled，HK 8y +94% 超额保留待 sweep
metadata:
  type: project
---

## 背景

[[trend_scan_pivot_2026-06-12]] 用户转向纯量价全市场扫描，6-12 落 3 yaml capital_pct=0.00 待验证。
本次完成 3y (2022-2024) + 8y (2018-2025) 双窗口判定。

## 工程修

- `universe/filter.py` 加 `skip_fundamentals` 旁路 — pure_pv 跳过 ROE/PE/market_cap 网络调用（不修这个 3866 只 universe 每个 asof 数小时）
- `engine/strategy.py` pure_pv → `UniverseFilterConfig(skip_fundamentals=True)` 透传
- `loader.py` HK/US universe 优先扫本地 prefetch CSV (`data/hk_prices/`, `data/us_prices_all/`)，回测启动不再调 sina spot 网络
- `loader.py` HK/US universe 切非 em 变体 (`stock_hk_spot`/`stock_us_spot`)，em 端点 push2 本机被 Clash 拦
- `prefetch_hk_all.py` / `prefetch_us_all.py` 同切非 em + `import quant_system` 触发 curl_cffi 补丁
- `engine/backtest.py:213` 加 `exec_price <= 0` 守门 — 美股 universe 含退市/OTC 脏数据 open=0
- `universe/filter.py` base.empty 分支返回带列空 df — A 8y 早期日期下游 `filtered_df["code"]` 不再 KeyError

123/123 pytest 通过。

## Prefetch 数据落地

- HK: 2719/2719 fetched (7 失败), 52m，`data/hk_prices/`
- US: 17131/17545 fetched (414 失败 ≈ 2.4%), 243m，`data/us_prices_all/`
- A: 已有 (zhuang 子策略预热 3866 只)，`data/prices/`

## 双窗口结果

### A 股 trend_scan — HARD-FALSIFY

| 窗口 | Sharpe | 总收益 | DD | vs HS300 | 4 门槛 |
|---|---:|---:|---:|---:|---|
| 3y | -0.42 | -14.48% | -26.33% | **+5.51%** | 全 FAIL |
| 8y | **-0.90** | **-65.85%** | **-74.62%** 💀 | **-79.12%** 💀 | 全 FAIL |

双窗口同向 + 8y DD 腰斩账户。`enabled=false` 落地。

### HK trend_scan — SOFT-FALSIFY / 待 sweep

| 窗口 | Sharpe | 总收益 | DD | vs HS300 | 4 门槛 |
|---|---:|---:|---:|---:|---|
| 3y | -0.26 | -6.94% | -30.37% | +7.62% | 全 FAIL |
| 8y | **+0.33** | **+73.98%** 🚀 | **-22.51% ✓** | **+94.30%** 🚀 | Sharpe/Sortino/胜率 FAIL，DD PASS |

3y FAIL / 8y 正且 DD PASS。**AMBIGUOUS → 按 [[equity_factor_c_ensemble_falsified_2026-06]] 规则 = SOFT-FALSIFY**，但 8y +94.30% 超额是真 alpha 不应直接扔。`enabled=true / capital_pct=0` 保留待 sweep（max_hold_days / regime_ma_days / tiered sizing）。

### US trend_scan — FAIL

| 窗口 | Sharpe | 总收益 | DD | vs benchmark | 4 门槛 |
|---|---:|---:|---:|---:|---|
| 3y | (未跑) | — | — | — | — |
| 8y | -0.23 | -19.71% | -38.47% | benchmark 标签 bug² | 全 FAIL |

²US yaml 未设 benchmark，默认 fallback "HS300" 写错，实际应是 SPX。绝对值 8y 仍 FAIL。`enabled=false` 落地。

## 核心洞察

1. **A 8y DD -74.62% 灾难** — 趋势策略在 A 股 3866 只全扫描下被 2018/2022 双熊市腰斩。zhuang 子策略 (hs300 限 + lottery exit) 才是 A 股趋势可行结构
2. **HK 是唯一正 alpha 市场** — 8y +94.30% vs HS300，admission 门槛 0.5 Sharpe 对 trend lottery 太苛刻（胜率 38% × 盈亏比 1.7 = lottery）
3. **lottery 结构跨市场一致** — 3 市场胜率全 37-38%，盈亏比 1.5-1.9，确认是趋势策略系统性形态
4. **US benchmark 默认 fallback bug** — 多市场架构遗留 hardcode "HS300"，要追修

## 关联

- [[trend_scan_pivot_2026-06-12]] — pivot 决策出处
- [[equity_factor_c_ensemble_falsified_2026-06]] — AMBIGUOUS = SOFT-FALSIFY 规则
- [[zhuang_optimization_2026-05]] — A 股 lottery 策略正确结构 (hs300 限 + L1-E 入场 + L4 出场 + L5 sizing)
- [[hk_optimization_2026-05]] — HK v10 (hs100 限) 当前实盘部署
- [[sp500_negative_2026-05]] — US momentum SP500 4y FAIL 早期证伪
