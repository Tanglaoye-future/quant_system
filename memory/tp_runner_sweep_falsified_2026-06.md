---
name: tp-runner-sweep-falsified-2026-06
description: 2026-06-14 HK equity_hk_momentum TP runner / ATR trail sweep 0 PASS — atr_target_mult × atr_stop_mult 12 变体双窗口同向 PASS 全失败；4y 牛市友好 / 8y 含熊不友好的典型 stop-widening paradox；time_stop alpha 留存假设反证；TP runner 5×ATR target 全样本 0 触发死代码但不能动；baseline (5.0/2.5) 是 efficient set 内
metadata:
  type: project
---

# TP runner sweep 证伪 — 第 18 条证伪墙（2026-06-14）

## 一句话

HK T+0 重跑后看到 `trail=89%, time_stop=4 笔 avg+28% / break_ma80=9 笔 avg-6%, TP runner 0 触发`，提"放松 trail / 收 target 留住 time_stop 大赢家"假设；跑 `atr_target_mult ∈ {3.0, 3.5, 4.0, 5.0}` × `atr_stop_mult ∈ {2.5, 3.0, 3.5}` 12 变体双窗口 sweep → **0 同向 PASS**，baseline (`5.0/2.5`) 是 efficient set 内。

## 触发假设（被反证）

回测后看到：4y baseline 121 笔中 trail 占 89%，time_stop 仅 4 笔但平均 +28%（4y）/ +30%（8y）；TP runner promote 全样本 0 触发（5×ATR target 太远）。
→ 假设 H：放宽 `atr_stop_mult` 让 trail 距离更远，可以留住更多 time_stop 大赢家的尾部 alpha；或降低 `atr_target_mult` 激活 promote 路径锁利后收紧 trail。

## Grid（4×3 = 12 变体 × 2 窗口 = 24 backtests）

`atr_target_mult ∈ {3.0, 3.5, 4.0, 5.0(baseline)}`
`atr_stop_mult ∈ {2.5(baseline), 3.0, 3.5}`

## 结果

### 4y 维度（2022-2026 牛市段）：放宽 stop=3.0 显著改善

| 变体 | 4y Sharpe | 4y Ret | 4y DD | 4y Sortino |
|---|---:|---:|---:|---:|
| **target=5.0 stop=3.0** | **+1.244** (Δ+0.095) | +69.3% | **-6.51%** (改善 7pp) | +1.485 (Δ+0.375) |
| target=4.0 stop=3.0 | +1.235 | +68.4% | -7.11% | +1.443 |
| baseline (5.0/2.5) | +1.149 | +81.1% | -13.53% | +1.109 |

### 8y 维度（含 2018-2021 长熊段）：同变体显著恶化

| 变体 | 8y Sharpe | 8y Ret | 8y DD |
|---|---:|---:|---:|
| baseline (5.0/2.5) | **+0.644** | +88.7% | -14.71% |
| target=5.0 stop=3.0 | +0.513 (Δ-0.131) | +62.2% (-26pp) | -17.69% |
| target=4.0 stop=3.0 | +0.494 (Δ-0.150) | +59.7% (-29pp) | -17.03% |

### Δ vs baseline 双窗口判定

| target | stop | 4y ΔSharpe | 8y ΔSharpe | 判定 |
|---|---|---:|---:|---|
| 5.0 | 3.0 | **+0.095** | **-0.131** | ❌ 异号（最大反差）|
| 4.0 | 3.0 | **+0.086** | **-0.150** | ❌ 异号 |
| 4.0 | 2.5 | -0.020 | **+0.006** | ❌ 异号 |
| 其余 9 个 | — | — | — | 全 ➖ 同负 |

**Backstop #2 严守**：0 双窗口同向 PASS → 不改 yaml。

## H 假设的反证（time_stop 留 alpha 失败）

| Variant | n_time_stop | avg time_stop pnl_pct |
|---|---:|---:|
| baseline (5.0/2.5) 4y | **4** | **+28.0%** |
| 5.0/3.0 4y | 7 | +17.5% |
| baseline 8y | **5** | **+30.4%** |
| 5.0/3.0 8y | 11 | +17.8% |

放宽 stop 后 time_stop 笔数 ↑（4→7 / 5→11），但 avg pnl 反而 ↓（28%→17% / 30%→17%）。
**反证机理**：trail 不是 alpha 砍刀，是 alpha 边界守卫。放松守卫不增加大赢家命中率，只是把"中等回报票"推到 time_stop 出场，稀释了 baseline 下少数真正强趋势票的尾部价值。

## TP runner 5×ATR target = 死代码但不能动

- baseline 4y：trail=108, time=4, break=9, **TP promote=0**
- 即使 target 改 3.0：trail=110, time=3, break=10, **TP promote 仍 0**

机理：HK 持仓 80 天内 close ≥ entry + 3-5×ATR 极罕见（HK 单 ATR ≈ entry × 4-6%，需要 close 涨 15-30% 才能 promote，但绝大多数走 trail stop 就先到了）。
→ `tp_runner_enabled / atr_stop_mult_runner / tp_runner_lock_atr_mult` 三字段在 HK universe 实质是 noop，但**改 target 任何值都不能激活路径**，sweep 验证后不动 yaml。

## paradox 类别（第 7 类）

windowed-stop-widening paradox：**stop_mult 放宽在 4y 牛市段单方向改善 / 8y 含熊段单方向恶化**，4y/8y 反向不对称。
- 与 paradox 第 6 类（[[equity_factor_c_ensemble_falsified_2026-06]] 窗口依赖 / regime-specific）同构但维度不同：第 6 类是 alpha 信号源（mom6m）的 regime-specific，第 7 类是 risk-management 出场的 regime-specific
- 与 paradox 第 5 类（[[capitulation_strategy_falsified_2026-06]] execution-vs-strategy 错配）正交

## 与既有 paradox / efficient set 关系

| 旧结论 | 本 sweep 验证 |
|---|---|
| [[hk_t0_recalibration_2026-06]] +0.06 Sharpe（执行层校准）| 本 sweep 在校准后 baseline 上跑，确认 alpha 层 (5.0/2.5) 仍 efficient |
| [[hk_optimization_2026-05]] L1 选 atr_stop_mult=2.5/atr_target_mult=5.0 | L1 在 4y 单窗口下选的；本 sweep 在 8y 验证 L1 仍是双窗口最优解 |
| [[a1prime_southbound_gate_falsified_2026-06]] HK sleeve 饱和 | 本 sweep 强化：连出场层都 0 PASS → HK 当前架构 alpha 已挤干 |
| [[equity_factor_c_ensemble_falsified_2026-06]] paradox 第 6 类 | 本 sweep 第 7 类（出场 risk-management 维度）同模式 |

## 第 18 条证伪

加入 `scripts/research/learn_from_trades.py` `FALSIFIED_PATTERNS` manifest:
- name: `tp_runner_atr_sweep_hk`
- keywords: `["atr_target_mult", "atr_stop_mult", "tp_runner", "trail_widen"]`
- doc_ref: `tp_runner_sweep_falsified_2026-06`
- severity: `SOFT-FALSIFY`（4y +0.095 但 8y -0.131 异号；不是 DEAD 因为 4y 单维度仍 alpha）
- note: HK windowed-stop-widening paradox 第 7 类; trail 不是 alpha 砍刀是边界守卫

## 5 条 Backstop 检查

- **#1 17 → 18 条证伪墙**：本 PR 把自己加入墙 ✓
- **#2 双窗口同向 PASS**：0 候选 PASS → 不改 yaml ✓
- **#3 实盘 < 30 笔不撬 frontier**：N/A（回测层；HK 实盘 0 仓）✓
- **#4 PM 决策权**：仅出 sweep 报表，不动 yaml ✓
- **#5 采集 vs alpha 分离**：N/A（不涉及 self-learning）✓

## 仍然不要做

- ❌ 不要把"4y +0.095 Sharpe / DD 改善 7pp"作为局部最优落 yaml — Backstop #2 拦
- ❌ 不要清掉 yaml 里的 `tp_runner_enabled / atr_stop_mult_runner / tp_runner_lock_atr_mult` — 在 HK 是 noop 但在其它 universe (A/US/未来) 可能激活；保留无害
- ❌ 不要因 4y stop=3.0 看起来好就单跑 4y 决策 — c_ensemble 教训：单窗口贪婪 = 8y 打脸
- ❌ 不要拓展 sweep 到 stop ∈ {3.5+} — 全样本验证持仓更长 = 资金占用更长 = N trades 大幅降（121→67）+ 总 ret 显著降

## Out-of-scope（follow-up）

- 是否在 A 股 / US universe 复跑同款 sweep — A 股 baseline atr_stop_mult=1.5 比 HK 紧得多，机理不同；US baseline 已负 Sharpe 不投资源
- 是否 sweep `atr_stop_mult_runner` × `tp_runner_lock_atr_mult` — TP promote 全样本 0 触发，sweep runner 段毫无意义

## 关联

- [[hk_t0_recalibration_2026-06]] — baseline 校准来源（本 sweep 在 T+0 baseline 上跑）
- [[hk_optimization_2026-05]] — L1 trail=2.5/target=5.0 历史选定理由
- [[equity_factor_c_ensemble_falsified_2026-06]] — paradox 第 6 类，本 sweep 是第 7 类
- [[a1prime_southbound_gate_falsified_2026-06]] — HK sleeve 饱和（本 sweep 强化）
- [[project_north_star]] — 支柱 2 趋势出场层；Backstop #2 双窗口同向规则来源
- [[session_2026_06_08_self_learning_pipeline]] — 5 条 backstop / 17 条墙原始定义
- `data/backtest/_hk_tp_runner_sweep/summary.md` — 完整 sweep 表
- `scripts/backtest/run_hk_tp_runner_sweep.py` — 可复跑

**Why**: 用户回测后发现 time_stop 票 alpha 残留，提"trail 砍掉尾部"假设；sweep 系统化验证 0 双窗口 PASS + 反证假设；为未来"看到某个出场维度有 alpha 残留就想调"类提议立硬墙。

**How to apply**: 未来任何"调 atr_stop_mult / atr_target_mult / TP runner / trail 距离"类提议，先指 [[tp_runner_sweep_falsified_2026-06]] 双窗口同向 PASS 拒；如果用户坚持，必须先证明 8y 不反向。HK windowed-stop-widening paradox (第 7 类) 是 HK 4y/8y 不可同时优化的硬约束之一。
