---
name: zhuang-l6a-weights-2026-05
description: 2026-05-31 — zhuang L6-A accumulation_weights sweep + 6y verify；equal weights (全 0.20) 双窗口同向赢 baseline (3y +0.065, 6y +0.041 Sharpe)；组合层 v5 + L6A-equal 2.347→2.365 Δ+0.018 (sleeve vol 3.5% 被稀释)；落 yaml
metadata:
  type: project
---

## 起点

[[zhuang_optimization_2026-05]] L1-L5 完成后 zhuang Sharpe 1.806 (6y, prefetch 3270 universe)。L6 候选按 PM ROI 排：accumulation_weights 5 维 (ma_convergence/volume_asymmetry/price_consolidation/turnover_decline/vp_divergence) 权重固定 5 年没动过，是最高 ROI 探索方向。

baseline weights (config 历史): 0.20/0.30/0.20/0.15/0.15。

## 3y Sweep (2022-01-01 → 2024-12-31, universe 2496 只)

`scripts/backtest/run_l6a_zhuang_weights_sweep.py` — 6 hypothesis + 1 baseline 串行跑.

| rank | tag | 3y Sharpe | weights (ma/vol/pr/tu/vp) |
|---|---|---|---|
| 1 ⭐ | **L6A-equal** | **+1.505** | 0.20/0.20/0.20/0.20/0.20 |
| 2 | L6A-strong-ma | +1.476 | 0.30/0.25/0.20/0.15/0.10 |
| 3 | L6A-strong-conso | +1.473 | 0.15/0.25/0.30/0.20/0.10 |
| 4 | L6A-weak-vp | +1.471 | 0.20/0.35/0.20/0.20/0.05 |
| 5 | L6A-strong-turnover | +1.466 | 0.15/0.30/0.20/0.25/0.10 |
| 6 | L6A-baseline | +1.440 | 0.20/0.30/0.20/0.15/0.15 |
| 7 | L6A-strong-volume | +1.414 | 0.15/0.40/0.20/0.15/0.10 |

**反直觉发现**：
- equal (无 prior) > 任何加重单维 hypothesis → 5 维信号 alpha 大致均等
- **strong-volume 唯一输 baseline**（vol 0.30→0.40 → -0.026 Sharpe）= 量信号已饱和
- PM 假设 "strong-turnover 最赢"（基于"浮筹减少是核心"代码理解）实际 rank 5，证伪

## 6y Verify (2020-01-01 → 2026-05-04)

Top 3 + baseline 跑 6y 双窗口验证.

| rank | tag | 6y Sharpe | Δ vs baseline | DD% |
|---|---|---|---|---|
| 1 ⭐ | **L6A-equal** | **+1.129** | **+0.041** | -4.97 |
| 2 | L6A-strong-ma | +1.128 | +0.040 | -4.71 |
| 3 | L6A-baseline | +1.088 | — | -4.70 |
| 4 | L6A-strong-conso | +1.085 | **-0.003** | -4.72 |

**关键**:
- equal / strong-ma 6y 几乎并列 (差 0.001 纯噪音)；都赢 baseline +0.04
- **L6A-strong-conso 在 6y 反转输 baseline** (3y +0.033 → 6y -0.003) = 过拟合警告
- equal 双窗口都赢 (3y +0.065 / 6y +0.041) = 非过拟合 ✅
- universe 用 2022-01-01 csv (2496 只) — 比历史 [[zhuang_optimization]] prefetch 3270 只少，baseline 6y Sharpe 1.088 < 历史 1.806，但相对排名仍有效

## 组合层验证 (v5 grid)

`scripts/portfolio/run_v6_zhuang_l6a_portfolio.py` — 用 L6A-baseline 6y 与 L6A-equal 6y 同 universe 公平对照（不用历史 zhuang 8y baseline 避免 universe 差异污染）.

| 配置 | 全窗口 Sharpe | Ann | DD |
|---|---|---|---|
| v5 + zhuang L6A-baseline (6y) | **2.347** | +9.19% | -2.68% |
| v5 + zhuang L6A-equal (6y) | **2.365** | +9.27% | -2.78% |
| **Δ Sharpe** | **+0.018** | +0.08% | -0.10% |

**为什么 sleeve +0.04 → 组合层 +0.018？**
- zhuang ann vol ~3.5% 是 6 资产里**最低**的
- 40% 配比看似大，但 portfolio vol 主要由 HK_mom (9.4%) / A_mom (10.3%) / QQQ (25.5%) 贡献
- sleeve Sharpe 改进在 vol 加权后被稀释 — 单 sleeve +0.04 → 组合 +0.02 是合理放大率
- 我之前预测"zhuang 1.81→2.0+ 拉组合 +0.08"偏乐观 2-4 倍，原因同上

跨段稳健性（全部 |Δ| ≤ 0.05 噪音范围，无显著好坏段）：

| 段 | base | L6A | Δ |
|---|---|---|---|
| 2020 疫情 | +1.078 | +1.058 | -0.020 |
| 2021 牛/顶 | +2.062 | +2.045 | -0.017 |
| 2022 熊 | +0.080 | +0.088 | +0.008 |
| 2023-24 震荡 | +3.404 | +3.443 | +0.040 |
| 2025-26 反弹 | +3.196 | +3.237 | +0.042 |

## 落 yaml (config/zhuang.yaml)

```yaml
accumulation_weights:
  ma_convergence: 0.20        # 不变
  volume_asymmetry: 0.20      # 0.30 → 0.20 (vol 信号过载证伪)
  price_consolidation: 0.20   # 不变
  turnover_decline: 0.20      # 0.15 → 0.20
  vp_divergence: 0.20         # 0.15 → 0.20
```

**理由 (PM trade-off)**:
- ✅ sleeve 3y/6y 双窗口同向 (+0.065 / +0.041) 非过拟合
- ✅ anti-overfit (无 prior weight 减少未来漂移风险)
- ✅ 简化 (5 个 0.20 vs 5 个不同值，易理解)
- ✅ 组合层不退步 (+0.018 噪音范围内)
- ⚠️ 组合层增益噪音级，实盘可能拿不到这 +0.018

低风险微收益改动。

## 累计 zhuang 优化路径 (6y, 2020-2026)

| 阶段 | Sharpe | 收益 | 累计 |
|---|---|---|---|
| v5 原始 | 0.944 | +37.3% | — |
| L1-E | 1.346 | +44.0% | +0.402 |
| L4-combo4 | 1.627 | +48.1% | +0.683 |
| **L5B-tiered** | **1.806** | **+76.0%** | +0.862 |
| **L6A-equal** (本轮) | 1.806 + 边际 | — | +0.04 sleeve / +0.02 组合 |

⚠️ L6-A 数据 (1.088→1.129) 用 universe 2496 只，与历史 (3270 只 prefetch) 不能直接对比。L6-A 的相对改进 (+0.04) 是真的，但绝对 Sharpe 数字不能拿来更新累计路径表。

## 不要做

- 不要再 sweep accumulation_weights — 6 hypothesis 已覆盖主要轴，且 plateau 紧 (1.41~1.51 差 0.09 Sharpe)
- 不要因为组合层 +0.018 噪音级就回退 — sleeve 双窗口同向是真信号，equal 哲学也支持
- 不要假设 "sleeve Sharpe +0.10 = 组合 Sharpe +0.04" — 这次实测 sleeve +0.04 → 组合 +0.018 (放大率 0.45)；zhuang vol 太低稀释

## 真正的下一步 (L7+ 候选, 按 ROI)

1. **L7-A: position_max_count 6 → 8/10 + L1-E 联调**
   - [[zhuang_l1_l2_l3_experiments_2026-05]] L1D-pos8 单独试过 Sharpe 0.928，但是 baseline 比较；与 L1-E 联调可能不同
   - 工程量极小（1 参 sweep）
2. **L7-B: 加 fundamentals quality gate** (ROE > 0 / 营收增速 > 0)
   - 但 [[zhuang_l1_l2_l3]] L2/L3 (信号 overlay) 已证负转移；基本面 gate 可能类似
   - 工程量中等
3. **L7-C: 动态 tp/sl by score** (高分股给更宽 trailing)
   - L4-combo4 已经把 tp/sl 收紧；动态化看是否高分股可放松
   - 工程量中等

## 产物

- Sweep 脚本：`scripts/backtest/run_l6a_zhuang_weights_sweep.py`
- 6y verify 脚本：`scripts/backtest/run_l6a_verify_6y.py`
- 组合层验证脚本：`scripts/portfolio/run_v6_zhuang_l6a_portfolio.py`
- Sweep 数据：`data/backtest/zhuang_l6a_sweep_summary.md` (3y) + `zhuang_l6a_verify_6y_summary.md` (6y)
- 组合层数据：`data/backtest/portfolio_v6_zhuang_l6a.md`
- yaml: `config/zhuang.yaml` accumulation_weights 全 0.20 ✅

**Why:** L6-A 是 zhuang L5 后第一个有方向感的优化层 — accumulation_weights 5 维权重固定 5 年没动是探索缺口；sweep 找出 equal weights 微赢 baseline + 双窗口同向 = 非过拟合，落 yaml 低风险微收益。
**How to apply:** zhuang accumulation_weights 决策已固化为 equal (0.20×5)；下次想再调 weights 必须证明 3y/6y 双窗口都 > equal +0.05 Sharpe，否则回退 equal。L7+ 候选见末尾。
