---
name: equity-factor-c-ensemble-falsified-2026-06
description: C ensemble mom3m+mom6m 4y PASS (+0.082 Sharpe) → 8y FAIL (-0.052) 双窗口未同向 — paradox 第 6 类新增 (窗口依赖); AMBIGUOUS 预检查路径首次走完 → 同样 FAIL 但 DD trade-off 真实; L8D2 仍 efficient set; 第 17 条
metadata:
  type: project
---

## 一句话结论

C-split (mom3m 0.10 + mom6m 0.10) 4y Sharpe 0.890 vs base 0.808 (**+0.082**) ✅, 但 8y Sharpe 0.314 vs base 0.366 (**-0.052**) ❌, **双窗口未同向** 触发 [[feedback_user_collab_style]] #3 严守规则 — 不落 yaml, 第 17 条证伪. paradox 第 6 类 (窗口依赖 / regime-specific) 首次显化. 但 8y DD 改善 5.3pp (-18.2% → -12.9%) + 笔数 -33% (换手降) 是真实 trade-off, 仅在收益降幅 (-1.1pp 年化) > Sharpe 改善幅时综合负. L8D2 (mom3m 0.20 单一 momentum) 仍是 HS300 因子层 efficient set.

## paradox 预检查 paradox (AMBIGUOUS → PASS → FAIL 路径首次走完)

| 阶段 | 信号 | 结论 |
|---|---|---|
| paradox 预检查 (c_ensemble_mom36_paradox_precheck.py) | Spearman(mom3, mom6) 4 asof ∈ [0.596, 0.775], 残差 \|Spearman\| max 0.204 | **AMBIGUOUS** (上次 threshold: > 0.7 软证伪, < 0.5 proceed) |
| 4y sweep (run_c_ensemble_mom36_sweep.py) | C-split Sharpe 0.890 vs base 0.808 (+0.082) | **PASS 4y winner** |
| 8y verify (run_c_ensemble_mom36_verify_8y.py) | C-split 0.314 vs base 0.366 (-0.052) | **FAIL 双窗口反向** |

## 实验设置

- driver: handoff session_2026_06_01_handoff backlog #2 (C ensemble after A2 软证伪)
- baseline: L8D2 (pe 0.15 / pb 0.10 / roe 0.20 / rev_g 0.15 / mom3m 0.20, sum=0.80)
- 4 case 4y: C-base / C-split / C-mom6-add / C-mom6-swap
- 2 case 8y: C-base-8y / C-split-8y (仅 4y winner 验证)

## 4y 结果 (C-split winner)

| rank | tag | Sharpe | 年化 | 收益 | DD | 胜率 | 笔数 |
|---|---|---|---|---|---|---|---|
| 1 | **C-split** | **0.890** | +11.6% | +58.0% | -11.7% | 44.7% | 367 |
| 2 | C-base | 0.808 | +10.8% | +53.0% | -12.8% | 44.0% | 368 |
| 3 | C-mom6-add | 0.807 | +10.9% | +53.8% | -12.7% | 44.4% | 367 |
| 4 | C-mom6-swap | 0.524 | +7.5% | +35.1% | -11.6% | 43.5% | 361 |

**关键洞察**:
- C-mom6-swap (mom3m=0 + mom6m=0.20) 严重崩 (-0.284) → mom3m 仍是主信号, mom6m 单独不胜任
- C-mom6-add (sum=0.90) 持平 base → 不是权重总和问题, 是 split 拆配比问题
- C-split (各 0.10) winner → mom6m 残差独立带来 4y 增益

## 8y verify (双窗口反向)

| tag | Sharpe | 年化 | 收益 | DD | 胜率 | 笔数 | Δ vs base |
|---|---|---|---|---|---|---|---|
| C-base-8y | **0.366** | +5.4% | +52.6% | -18.2% | 42.9% | 564 | — |
| C-split-8y | 0.314 | +4.3% | +39.9% | **-12.9%** | 44.2% | 380 (-33%) | -0.052 Sharpe / **+5.3pp DD** |

**关键洞察**:
- C-split 8y 笔数 380 vs base 564 (-184 笔) — mom6m 降低换手, holding period 延长
- DD 改善 5.3pp 显著 (-18.2% → -12.9%) — mom6m 在 2018-2021 大幅震荡段帮过滤了一些坏 trade
- 但收益降幅 12.7pp (52.6% → 39.9%) > DD 改善的 vol 折扣, Sharpe 净负
- **是真 trade-off** (low-vol / low-return), 不是 strict dominated

## 双窗口反向的根因 (regime-dependent)

| 段 | C-base 主导 | C-split 主导 |
|---|---|---|
| 2018-2021 (波动 + 流动性宽松) | 收益机会快变, mom3m (60d) 抓快 | mom6m (120d) 滞后, 滑过短反弹 |
| 2022-2026 (调整 + 缩量) | 短 mom 频繁假信号 | mom6m 滤掉假信号, 残差独立带 alpha |

→ **mom6m 是 regime-conditional alpha**, 不是 unconditional alpha. 单一权重无法 capture, 需要 regime-switch 来动态加权 (但这层在 v6 regime overlay 已证伪 [[v6_regime_overlay_2026-05]]).

## paradox 第 6 类新增: 窗口依赖 / regime-specific

| paradox 类 | 例子 |
|---|---|
| 1. 信号互斥/重复 | L9-B ROIC ≡ ROE, A2 small-cap 不解耦 |
| 2. Base rate spurious | A1' 南向 gate, L8 fundamentals gate |
| 3. Sample 压扁 | L7-B 阈值收紧, capitulation 变体 A 反包+jg |
| 4. 数据死亡 | A1 北向 akshare 2024-08, capitulation 跌停撬开 30 日限 |
| 5. Execution-vs-strategy 错配 | capitulation 盘中 alpha 不可日级化 |
| **6. 窗口依赖 (本条新增)** | C-split 4y PASS 8y FAIL, mom6m 在 2022-2026 段 alpha 但 2018-2021 段 drag |

**预检查 calibration 升级**:
- Spearman > 0.6 → 软证伪 (从之前 > 0.7 收紧, 因 C-split 平均 0.69 仍 8y FAIL)
- Spearman ∈ [0.4, 0.6] + 残差独立 → AMBIGUOUS, 优先选 swap 而非 split (避免窗口依赖)
- Spearman < 0.4 → push backtest (更严判断 proceed)

## yaml 不动 (严守双窗口规则)

config/strategies/equity_factor.yaml: markets.a_share.factors.weights 保持
- momentum_3m: 0.20 (不变)
- momentum_6m: 0.0 (不变)

L8D2 (pe 0.15 / pb 0.10 / roe 0.20 / rev_g 0.15 / mom3m 0.20, fcf=0 + L9-B=0 + mom6m=0) **仍是 HS300 因子层 efficient set**, 累积 4 条证伪锁死 (fcf / L9-B / A2 universe / C-split window).

## 六层 efficient set 第 4 次锁定

| 层 | efficient | 证伪累积 |
|---|---|---|
| 组合层 v5 | HK25/A_mom10/A_mr10/zhuang40/QQQ5/GLD10 | 5 |
| **HS300 因子层** | **L8D2 (mom3m 0.20 单 momentum 维度)** | **4 (本条)** |
| zhuang sleeve | L1-E + L6-A equal | 3 + capitulation (互斥) |
| HK sleeve | widen on + gate off | 1 |
| A 股因子 universe | HS300 only | 1 |
| 反向情绪/题材 | dashboard 辅人工 (无 sleeve) | 第 16 条 |

## DD trade-off (用户拒绝改规则)

8y DD 改善 5.3pp 真实但 user 不接受改 "双窗口同向" 规则. 这是 user 个人风险偏好 — 偏好 Sharpe-based 决策 > DD-based decision. 未来类似 trade-off 路径直接套用 "Sharpe 双窗口同向" 严判, 不另问.

## Why
保留是为了:
1. 未来不再做 "mom3m + mom6m / RSI + ROC / 短中期 momentum ensemble" 类提议
2. paradox 第 6 类 (窗口依赖) 给未来 AMBIGUOUS 预检查路径校准: 平均 Spearman > 0.6 + 残差独立, 大概率窗口依赖, 等价软证伪
3. 双窗口规则严守 不被 DD-trade-off 撬动 (即使 DD 改善 5pp 也不落)

## How to apply
- 收到 "拆 mom3m + mom6m / mom6m + mom12m / RSI + Stochastic ensemble" 类:
  - 先跑 [[c_ensemble_mom36_paradox_precheck]] 模板 (改 indicator 名)
  - Spearman > 0.6 → 软证伪不投 backtest
  - Spearman 0.4-0.6 + AMBIGUOUS → 直接软证伪 (本案教训, 窗口依赖大概率)
  - Spearman < 0.4 → 仅 push backtest
- AMBIGUOUS verdict 现在等价于 SOFT-FALSIFY (不再投 2.5 hr sweep + 1.5 hr verify ~4hr 工程)

## 链接
- 上游: [[session_2026_06_01_handoff]] [[a2_csi1000_l9b_paradox_falsified_2026-06]] [[equity_factor_l9b_falsified_2026-05]]
- 教训源: [[feedback_user_collab_style]] #3 (双窗口同向才落 yaml)
- regime overlay 历史: [[v6_regime_overlay_2026-05]] (regime-switch 也证伪)
- paradox 6 类列表见本文件
