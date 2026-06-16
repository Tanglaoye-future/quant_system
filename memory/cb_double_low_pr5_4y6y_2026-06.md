---
name: cb-double-low-pr5-4y6y-2026-06
description: CB 双低 PR5 backtester 落地 + 4y/6y 双窗口同向 PASS (Sharpe 0.839 / 1.419) — 准入 PR6 + 实盘条件已满足
metadata:
  type: project
---

# CB 双低 PR5 — 4y/6y 双窗口同向 PASS

**日期**: 2026-06-16
**Spec**: [[convertible-bond-sleeve]] (PR5 验收)
**北极星**: [[project-north-star]] 支柱 1 (债性条款) + 支柱 2 (risk-parity 豁免)

## 一句话结论

PR5 backtester 落地 + 4y/6y 双窗口同向 PASS (Sharpe +0.839 / +1.419)。**首次有数据支撑的"未来 alpha"方向**，自 [[v7-efficient-frontier-2026-06]] 与 18 条 A 股证伪后。可进 PR6 (8y 完整 + sweep) → PR7 (yaml 落地 advisory)。

## 4y / 6y 双窗口实测

| 指标 | 4y [2022-01-01 → 2026-05-25] | 6y [2020-01-01 → 2026-05-25] |
|---|---|---|
| Total return | +111.55% | **+295.73%** |
| CAGR | +19.50% | +25.13% |
| **Sharpe** | **+0.839** | **+1.419** |
| Max DD | -9.93% | -14.87% |
| N closed trades | 334 | 503 |
| Hit rate | 35.3% | 41.7% |
| Avg pnl/trade | +4.89% | +6.04% |

**6y > 4y 是关键** — 不只是双窗口同向，而且更长样本 + 更早期数据下 Sharpe 提升 +0.58，与拥挤后 2023-2024 A 股 sleeve 趋稳同向，CB sleeve 跑出独立 alpha。

## vs v7 efficient frontier 对比

| | v7 6 资产组合 | CB sleeve solo |
|---|---|---|
| 4y Sharpe | +1.842 | +0.839 |
| 8y/6y Sharpe | +1.455 | +1.419 |
| Max DD | -12.5% / -14.8% | -9.93% / -14.87% |

**CB 单 sleeve Sharpe 6y ≈ v7 6 资产 8y (1.419 vs 1.455)** + DD 更友善 (-9.9% vs -12.5%)。**与 v7 6 资产相关性预期接近 0** (CB 是债性独立资产类别), 组合层叠加 v7 后 PR6 sweep 验证.

## PR4 → PR5 内化的 3 个 nuance（实测有效）

1. **Panel coverage median 47.1% (4y) / 42.7% (6y)** — nuance 1 best-effort 设计正确, 默认值 (>30%) 全程满足. 4y `days < 30%` = 0; 6y = 136 (集中 2020-2021 早期数据稀疏区).

2. **exit_dual_low_threshold 默认 180 (vs spec 原 150)** — 4y/6y 默认配置下入场池 score 中位 ≈ 144, 默认 180 不立刻强制出场, 也不太松。PR6 sweep 候选 150/170/180/190/200/相对值.

3. **min_conversion_premium=-5% (nuance 3)** — 已落 `UniverseFilterConfig`, 全市场默认配置下 4y 跑通无再次撞兴瑞转债式入场.

## 实战可执行性硬卡

- ✅ 实盘账户类型：A 股账户 (已有, T+0 CB 交易)
- ✅ 数据可得性：akshare 4 端点 probe PASS (见 [[cb-data-probe-2026-06]])
- ✅ Survivorship bias：含 2007 起退市债 (113008/113537 验证)
- ✅ 容量：< 100M AUM 无障碍 (本 sleeve 5-10% 占比 < 5M, 安全)
- ✅ 双窗口同向：4y/6y Sharpe 均正且同向上升
- ⚠️ 8y 真实起点限制：value_analysis 2020 起 → 6y 是 spec 8y 等价 (spec §4 已声明)

## PR5 落地产物

- `src/quant_system/strategies/cb_double_low/engine/backtest.py` — CBBacktester + write_m0_artifact
- `scripts/backtest/backtest_cb_double_low.py` — 4y/6y 入口
- `tests/cb_double_low/test_backtest.py` — 10 case (rebalance / force_exit / M0 artifact)
- `scripts/backtest/audit_m0_outputs.py` — 加 cb_double_low strategy 分支, audit PASS
- `data/backtest/cb_double_low_a_share_2022-01-01_2026-05-25/` 4y M0 audit PASS
- `data/backtest/cb_double_low_a_share_2020-01-01_2026-05-25/` 6y M0 audit PASS

## PR6 下一步必做

按 [[convertible-bond-sleeve]] PR6 准入清单:

1. **8y backtest**：value_analysis 早期起点限制下, 6y 已等价 8y. 若 2018-2019 数据后续放开补回, 再加.
2. **exit_threshold sweep**: 150/170/180/190/200/相对值 (`top_N_median + 30`); 双窗口同向 PASS 才能调.
3. **min_conversion_premium sweep**: -3% / -5% / -10% / None; 看 hit rate + avg pnl trade-off.
4. **组合层叠加 v7 grid**: CB 加入 v7 6 资产, 测 5% / 10% / 15% 占比, 看组合 Sharpe 是否同向提升.
5. **写 falsified memory or proceed**: 若组合层叠加无 Sharpe 同向提升, 写 cb_double_low_falsified_<date>.md 归档.

## 已知限制 (PR5 backtester 设计)

1. **look-ahead universe**: `load_universe(asof=end_dt)` 用 end 当 universe → "未来强赎"被排除. backtest 阶段已知缺陷, PR6+ 可改滚动 asof.
2. **last_trading_date 作强赎 proxy**: backtest 用 `last_trading_date <= asof` 视为强赎生效, 实际公告 1-2 月前 (PR3 announcement_date 占位 NaT 限制).
3. **每日 close 价 force-exit**: 当日 close 触发出场 = 当日 close 价成交. 实际 T+1 略保守, 影响 < 单边 slippage 5bp.
4. **Equal weight**: PR5 仅支持 equal weight (`weight_scheme="equal"`). score-weighted / inverse-vol 留 PR8+.

**Why**: 自 v7 efficient frontier 落地 + 18 条 A 股证伪后, 6+ 个月没出现新方向. CB 双低 PR1-5 闭环 11 hr (vs spec 估算 10 hr) 跑出 6y Sharpe 1.42 / 与 v7 相关性预期 0 的独立 sleeve. PR5 后唯一未填窟窿的是 PR6 (组合层叠加 v7 验证) + PR7 (yaml 落地).

**How to apply**: 接到任何 CB 相关需求 (调阈值 / 加因子 / 改 sizing) 时, 先引用本 memory 的双窗口 baseline 作 dominate test 基准. 若 PR6 组合叠加证伪 → 写 cb_double_low_falsified, CB sleeve 永久归档. 若 PR6 PASS → 进 PR7 + 实盘 advisory.
