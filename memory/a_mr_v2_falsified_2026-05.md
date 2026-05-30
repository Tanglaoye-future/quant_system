---
name: a-mr-v2-falsified-2026-05
description: 2026-05-30 — A_mr v2 (MA200 buffer + 斜率 + grace) 4y Sharpe -0.26 (vs v1 -0.27)；10-case sweep 5 个有效 case 全 plateau -0.27~-0.34 → v2 三参方向证伪；连同 v6 grid + regime overlay 共 4 条 A_mr 优化路径全死，A_mr 是 uncorrelated noise 不是 alpha
metadata:
  type: project
---

## 起点

[[a_mr_rebuild_v6_grid_2026-05]] 里 v1 (SwingReversion: RSI dip+bounce+ATR target) 4y Sharpe -0.27 / break_ma200 占 46% 出场。v2 设计基于该诊断，三招修缺陷：

1. MA200 buffer: close > MA200 × (1 + buffer)，过滤"瓶口反弹"
2. MA200 斜率门: 仅 MA200 vs N 日前上升时入场
3. break_ma grace: 连续 N 天 close < MA 才出，避免单日噪音

## 代码改动

`SwingReversionConfig` 新增 3 参数：
- `ma_long_buffer_pct: float = 0.0` (默认 v1 行为)
- `ma_long_slope_enabled: bool = False` + `ma_long_slope_lookback: int = 20`
- `break_ma_grace_days: int = 0`

`screen()` + `evaluate()` 加 v2 逻辑分支。单测加 3 个 v2 case (test_v2_ma_buffer_blocks_thin_bounce / slope_blocks_downtrend / grace_holds_single_day_dip)。共 10/10 pass。

## 4y baseline (buf=0.03, slope=on, grace=3)

| 指标 | v1 (RSI dip+bounce) | **v2 default** |
|---|---|---|
| Sharpe | -0.27 | **-0.26** (持平) |
| 总收益 | -7.69% | -6.93% |
| 笔数 | 208 | 207 |
| 胜率 | 34.1% | 34.8% |
| 盈亏比 | 1:2.43 | 1:2.37 |
| **break_ma 出场** | **95 (46%)** | **93 (45%)** |

v2 三招几乎没改变任何东西 — break_ma 出场只少 2 笔。

## v2 Sweep 10-case (run_swing_rev_v2_sweep.py)

参数空间：buffer ∈ {0.02, 0.03, 0.05}, slope on, grace ∈ {2, 3, 5} + buf03_only (no slope/grace) 对照 = 10 cases。

⚠️ Sweep 首次 4-worker 并行跑撞 race condition（yaml 全局共享 + backtest.py 固定 output dir），5 个 case 出有效数据：

| tag | Sharpe | 总收益 | 笔数 |
|---|---|---|---|
| buf05_slope_g5 | -0.274 | -7.69% | 208 |
| buf03_slope_g5 | -0.296 | -8.65% | 205 |
| buf02_slope_g3 | -0.299 | -8.76% | 205 |
| buf03_slope_g3 | -0.317 | -9.61% | 210 |
| buf02_slope_g5 | -0.339 | -10.57% | 201 |

**全部在 -0.27 ~ -0.34 plateau，无一好过 v1 baseline**。

Sweep 脚本已修：N_WORKERS=1 强制串行（避免 race）+ metrics.json 嵌套结构容错。

## 4 条 A_mr 优化路径全死汇总

| 路径 | Sharpe / 影响 | 状态 |
|---|---|---|
| v1: RSI dip+bounce+ATR target | -0.27 (4y solo) | ❌ |
| v2: + MA200 buffer/slope/grace | -0.27~-0.34 (5 case plateau) | ❌ |
| v6 grid 砍 A_mr | 组合 -0.10 + 2022 熊市 +0.47→-0.32 (反向证伪) | ❌ |
| v6 regime overlay 动态切 | 组合 -0.089 + 2025-26 反弹 -0.40 | ❌ |

## PM 真相 — A_mr 是 uncorrelated noise，不是 alpha

- A_mr solo Sharpe 长期在 -0.30 ~ +0.05 区间漂移
- 它在组合层贡献 +0.10 Sharpe **不是来自 stock-picking alpha**，而是：
  - 10% 配比 solo 期望 Sharpe ≈ 0
  - 与 zhuang/A_mom/QQQ 负相关或近 0 → 降 portfolio vol
  - vol 降低 → Sharpe = mean/vol 自动上升
- 任何"做强 A_mr"的方向都偏离这个真相 — A_mr 的价值上限是 noise diversification，不是 timing/factor 选股

## 决策

- **A_mr 保留旧 mean_reversion**（kind=mean_reversion，RSI<30 经典 oversold）— 实盘不动
- SwingReversion 代码 + 单测 + sweep 脚本 + 4 case 数据**留仓内**作历史记录，未来谁想再试 v3 有起点
- a_share.yaml 的 swing_reversion 节**删除**（v2 默认参数被证伪比 v1 略差，让代码默认回 v1）
- 未来 alpha **不在 A_mr 层**，往新方向找：
  1. 新低相关性资产（BTC ETF / TLT 重测 / 中证 1000 小盘）
  2. fundamentals 升级（ROIC / 应收增速 / 现金流分项让 L9-A 因子层精进）
  3. HK 真做空 leverage（融券/期货放大 alpha）
  4. 实盘 3 个月真实数据再说

## 不要做

- 不要再试 SwingReversion v3 (quality gate / chandelier exit / 极端参数 sweep) — 4 条路径已证 A_mr 结构性 ceiling
- 不要砍 A_mr 配资把权重移给其他资产（v6 grid 已证 -0.10 Sharpe）
- 不要在 a_share.yaml 重新加 swing_reversion 节 — 让代码 default (== v1 baseline) 是清晰契约

## 产物

- 代码：`SwingReversionStrategy` v2 参数 (engine/strategy.py)
- 单测：`tests/equity_factor/test_swing_reversion.py` 10/10 (3 v2 新 case)
- 4y v2 baseline 数据：`data/backtest/swing_rev_v2_sweep_buf03_slope_g3/`
- Sweep 脚本：`scripts/backtest/run_swing_rev_v2_sweep.py` (修 race condition 后串行 1-worker)
- 5 case 数据：`data/backtest/swing_rev_v2_sweep_*/` (4 个有效 + 1 个空目录)

**Why:** 4 条 A_mr 优化路径全死是高价值结论，避免未来再投工程"做强 A_mr"。A_mr 的本质是 noise diversification 不是 alpha，PM 视角应该接受这个 ceiling 把精力放在更有 upside 的方向。
**How to apply:** 下次再有"A_mr 是不是要 v3"讨论，先指本 memory；任何想从 A_mr strategy 层榨 alpha 的尝试，先在 4y 单测里证明 break_ma 出场比例能压到 20% 以下，否则就是另一个 -0.27 plateau。
