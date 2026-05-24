---
name: equity-factor-l8-2026-05
description: 2026-05-23~24 equity_factor A 股 L7-C3 之后 L8 因子层探索：rev_accel / 北向 / fcf 反向去除；最终 L8D2 (fcf_yield=0) 落地，4y Sharpe 0.579→0.675、8y 0.063→0.195
metadata:
  type: project
---

## 起点

L7-C3 (regime_exit + partial_exit + collar) 已落地，4y Sharpe 0.62（高于 base 0.23 +174%）。本轮目标：在出场已收紧的基础上，看因子权重还能否再榨。

## L8 sweep — 加新因子（结果：组合反相互抵消）

窗口 2022-01-01 → 2026-05-04 (4y)：

| 实验 | Sharpe | 收益 | DD | 笔数 | 备注 |
|---|---|---|---|---|---|
| L8-base | 0.579 | +36.0% | -14.3% | 396 | baseline (≠ 4y L7-C3 0.62，因 loader.py 90d lag 修复) |
| L8A-rev_accel (+rev_accel 0.10, rev_growth 0.15→0.10) | 0.635 | +39.9% | -12.4% | 394 | ✅ 单加 rev_accel +0.056 |
| L8B-north_top10 (北向 widen) | 0.584 | +37.0% | -14.4% | 405 | 几乎持平 |
| L8C-combo (A + B) | 0.439 | +28.8% | -15.1% | 403 | A+B 互相抵消 |

**关键经验**: 因子叠加 ≠ 单因子叠加效果之和。两个独立有效的改造组合在一起反而拉低 Sharpe，可能是入场过滤过严或信号冲突 → 别盲目堆因子。

## L8D sweep — 怀疑 fcf_yield 负贡献并验证

L8-base 比记忆里旧 L7-C3 baseline 略低，怀疑 fcf_yield 0.20 实际是负贡献。4y 窗口对照：

| 实验 | Sharpe | 收益 | DD | 笔数 | 备注 |
|---|---|---|---|---|---|
| L8D1-no_fcf_pe_back (fcf=0, pe_inverse 0.15→0.20) | 0.656 | +42.0% | -13.5% | 408 | 重分配，sum=1 |
| **L8D2-no_fcf_only (fcf=0，其他不动)** | **0.675** | +43.4% | -13.6% | 407 | ✅ 4y winner |
| L8D3-rev_accel_no_fcf (L8A + fcf=0) | 0.476 | +31.3% | -13.3% | 403 | rev_accel + no_fcf 也互相抵消 |

**结论**: fcf_yield 在 A 股 4y 是负贡献。直接置 0 (sum=0.80) 比重分配到 pe (sum=1.00) 更好。

## L8D2 8y 验证（落地决策依据）

窗口 2018-01-01 → 2026-05-04 (8y, 含 2018-2021 牛市 + 2022-2024 熊市)：

| 标签 | Sharpe | 年化 | 收益 | DD | 胜率 | 笔数 |
|---|---|---|---|---|---|---|
| verify8y-L8-base | 0.063 | +2.2% | +18.8% | -16.8% | 49.1% | 529 |
| verify8y-L8D2-no_fcf | **0.195** | +3.5% | +32.0% | **-19.5%** | 49.1% | 591 |

8y 维度 Sharpe +0.132 (比 4y +0.096 还更大)，方向一致 → 不是过拟合。**但 DD 恶化 +2.7pp** — fcf_yield 在熊市段起一定"避雷"作用。

**落地决策**: L8D2 原样落 `config/strategies/equity_momentum.yaml`（fcf_yield: 0.0, sum=0.80）。
- **Why**: 4y/8y 双窗口稳赢 base，统计上扎实；sum=0.80 实操上无碍（FactorWeights 内部 zscore 排序对 sum 不敏感）
- **Trade-off**: 接受 DD 恶化 2.7pp。若未来运行中 DD 触底大于历史 -19.5%，应回滚或重启 L8D1 重分配方案

## 顺手修的数据正确性 bug

L8 sweep 中途发现 `latest_indicator_value` / `latest_n_indicator_values` 的 `asof` cutoff 直接用报告期，无公告窗口延迟。等于"财报当天就可获取"，存在数据泄漏。

修复：加 `publication_lag_days=90`，与 HK 对齐（年报最长 4 个月披露）。这导致 L7-C3 旧记录的 4y Sharpe 0.62 与本次 L8-base 0.579 不可直接对比 — L8-base 是修复后基准。落 yaml 时统一以 L8-base / L8D2 为口径。

新增 unit test `tests/equity_factor/test_loader_publication_lag.py` 8 个用例覆盖：窗口内排除 / 窗口外纳入 / lag=0 退化 / asof=None / NaN 回退 / n 期截断 / 自定义 lag / 指标缺失。

## 未来扩展指南

- **新因子加进来**: 先单独测 4y → 显著正再 8y 验证 → 双窗口同向才落
- **不要堆叠因子**: L8C / L8D3 都说明 A+B 互相抵消，每次只动一个权重
- **DD trade-off**: fcf=0 后熊市抗跌差，可后续加 m5_regime_exit 阈值收紧或 hedge ratio 上调对冲
- **HK / US 是否也跑 L8D2**: 未做对照实验，理论上 fcf 在 HK 更有效（价值股市场），别盲目移植；若要试，按 [[strategy_market_decouple_2026-05]] 模板，单市场跑 4y/8y 对照

## 不要做

- 不要把 L8-base 的 0.579 与 L7-C3 记忆里的 0.62 直接比对 — loader 公告窗口口径不同
- 不要因为 4y 单窗口结果就落 yaml — 必须 8y 同向才扎实
- 不要把因子改成 sum=1 强约束 — FactorWeights 不要求；让"去掉某因子"=权重 0 即可，可读性最佳

**Why:** 用户长期希望"用数据说话"地迭代因子；本轮严格做了 4y → 8y 双窗口验证，并主动暴露 DD 恶化 trade-off 而非掩盖。
**How to apply:** 未来调因子权重时复制本节模板：sweep → 怀疑某项负贡献 → 单独对照 → 双窗口验证 → 落 yaml。每步留 4y/8y json 产物供回溯。
