---
name: cb-double-low-pr12-self-learning-2026-06
description: PR12 — learn_from_trades.py 加 cb_double_low sleeve, 修 A_mom 桶吞 CB bug (PR8 前 if market!=hk: A_mom 会把 cb_a 误归), §5 exit_summary sleeve-aware 选 cb_exit_type vs equity exit_type; 完成 CB 北极星支柱 4 retrospective 闭环
metadata:
  type: project
---

# PR12 — self_learning_pipeline 加 CB sleeve

**日期**: 2026-06-17
**前置**: [[cb-double-low-pr8-journal-portfolio-2026-06]] schema + [[cb-double-low-pr11-closed-trades-html-2026-06]] cb_exit_type 沉淀
**Base pipeline**: [[session_2026_06_08_self_learning_pipeline]] L5 retrospective
**Why**: 北极星支柱 4 闭环最后一环 — CB closed_trades 已通过 PR11 沉淀含 cb_exit_type/dual_low_score/conversion_premium/scale_remain_yi/rating, PR12 让 retrospective 报表能消费, advisory 期 N=0 → 9 月 ≥30 笔后首次有意义报表.

## 关键工作 (3 块)

### 1. Bug fix — A_mom 桶吞 CB 行

PR8 之前 `fetch_closed_trades` 用 `if t.market == "hk_share": HK_mom else A_mom`. PR8 后 CB sleeve market='cb_a' 不匹配 hk_share, 会**误归 A_mom**, 污染 A_mom 的 winner-vs-loser 分布.

修法 — 新 helper `_classify_journal_sleeve(t)` 联合 (market, strategy) 显式分桶:
```
market='cb_a' & strategy='cb_double_low' → cb_double_low
market='hk_share'                         → HK_mom
其他                                       → A_mom (fallback)
```

防御性: market='cb_a' 但 strategy 缺 → fallback A_mom (避免 mislabeled 数据混桶), 测试 `test_classify_cb_a_without_strategy_falls_back_to_a_mom` 锁定.

### 2. 加 cb_double_low sleeve

`fetch_closed_trades` 返回 dict 加第 4 个 key `cb_double_low`. `build_report` 自动 iterate 所有 sleeves, 不需要改 (好设计).

`SLEEVE_BENCHMARK` 加 `"cb_double_low": None`:
- 集思录 EW 双低指数无 baostock 接口, 无法接 alpha α 计算
- alpha_summary.reason = "未接入 (L5.0.2 决策)" — 不阻断 pnl/winner-vs-loser/cb_exit_type 分析
- L5.1 followup: 自建 CB EW 净值曲线 (从 panel value_analysis 历史数据), 或 akshare bond_cov_index 替代

### 3. §5 exit_summary sleeve-aware exit_type 选择

equity exit_taxonomy (STOP_TRAIL/STOP_TREND/TAKE_PROFIT/...) 与 CB exit_taxonomy (SCORE_EXIT/STOP_LOSS/FORCE_REDEEM/REBALANCE/DELISTED/OTHER) 不重合. PR11 已在 exit_features 同时写两个字段 (浅合并保留 equity exit_type=OTHER fallback + cb_exit_type 真值).

PR12 §5 分桶按 sleeve 选字段:
```python
exit_type_field = "cb_exit_type" if sleeve == "cb_double_low" else "exit_type"
```

PR12 winner-vs-loser CB sleeve §5 分桶按 CB layer (SCORE_EXIT/STOP_LOSS/FORCE_REDEEM/REBALANCE/DELISTED), equity/zhuang sleeve 仍按 equity layer (PR8-PR11 行为零变化).

## 关键反例 — 没扩 17 条证伪 manifest

L5 falsified manifest 17 条全是 equity/zhuang 已死路径 (北向/南向/ROIC/AR_YoY/FCF_yield/...). CB 是 PR8/9/10/11 落地的**新方向**, 还没积累任何"已死 dimension" — manifest 不加 CB 条目, 等 9 月 retrospective 真出数据后看是否需要扩.

如果未来出现 "CB conversion_premium_rate 撬阈值 winner/loser 反向 不可重复" 这类发现, 那时再加 manifest 条目和 keyword cross-check.

**不扩 = 留白合理**, 不是 PR12 漏做.

## 文件清单

| 文件 | 变动 |
|---|---|
| `scripts/research/learn_from_trades.py` | (1) _classify_journal_sleeve helper + _trade_row_to_dict helper (2) fetch_closed_trades 加 cb_double_low key + 用新 classifier (3) SLEEVE_BENCHMARK 加 cb_double_low: None (4) §5 exit_type_field sleeve-aware |
| `tests/research/test_learn_from_trades_cb.py` | 10 case: 4 classify (cb/equity/hk/fallback) + 2 build_report empty/small_sample + alpha 未接入 + 2 §5 sleeve-aware (CB cb_exit_type / equity exit_type 无回归) + 1 numeric §3 (CB entry_features) + 2 render_markdown |
| `memory/cb_double_low_pr12_self_learning_2026-06.md` | 本文件 |

## 验收

| 命令 | 结果 |
|---|---|
| `pytest tests/research/test_learn_from_trades_cb.py tests/research/test_learn_from_trades.py -v` | **30/30 PASS** (10 PR12 新 + 20 既有无回归) |
| `pytest tests/cb_double_low/ tests/db/ tests/equity_factor/test_journal.py tests/intraday/ tests/reporting/ tests/research/ -q` | **279/279 PASS** 全 PR8-PR12 链路 + base 全无回归 |
| `python scripts/research/learn_from_trades.py --since 2026-05-22` | 真实报表 `/tmp/learn_2026-06-17.md` 含 `## cb_double_low` section (advisory_only 期 N=0 正常) |

## advisory_only → ≥30 笔 UX 时间线

- 现在 (2026-06-17 后): cb_double_low sleeve N=0, retrospective 报表显示 "n_closed = 0", 无 winner-vs-loser
- 7/1: PM 月初首次 rebalance, 录 20 笔 open
- 8/1 (rebalance day) / 中途强赎或止损: 首笔 closed 入 journal_trades, exit_features.cb_exit_type 自动写
- 9/30 累计 ~30 笔 closed (若 5% 月度换仓率即 ≥30 笔/季度) → **min_sample=10 触发首次 winner-vs-loser 分布差报表**
- PM 看 winner_vs_loser §3:
  - dual_low_score winner 均值 vs loser 均值: 是否 entry score 越低越赚?
  - conversion_premium_rate: 是否负溢价 winner 偏多 (强赎尾盘)?
  - scale_remain_yi: 是否小规模偏 winner (流动性溢价)?
  - rating: AA / AA- / A+ 桶占比 (categorical descriptive)
- §5 exit_summary cb_exit_type 分布: SCORE_EXIT/STOP_LOSS/FORCE_REDEEM/REBALANCE 哪种比例最高 → 是否符合策略预期

## 5 条 Backstop 严守 — 不写 yaml 不调参

PR12 严守 L5 5 条 Backstop:
1. ✅ 17 falsified manifest 不扩 CB (留白合理, 等数据)
2. ✅ 双窗口 4y+8y 同向 PASS 才落 yaml — 报表 footer 强制写
3. ✅ N < min_sample 强 warn — CB 当前 N=0 自动触发
4. ✅ 程序产出报告, 不自动改 yaml / 不触发 daily / 不自动调阈值
5. ✅ 采集与 alpha 决策完全分离 — features nullable + 零新依赖

## 北极星支柱 CB sleeve 全闭环

| 支柱 | PR | 状态 |
|---|---|---|
| 1 债性条款选标的 | PR4/PR5 | ✅ 转股溢价率 + 纯债溢价率 + 剩余规模 + 评级 |
| 2 risk-parity 豁免 | 北极星扩展 | ✅ CB 低波 + 债底保护 |
| 3 schema | PR8 | ✅ journal_trades + portfolio_history 共享表族 |
| 3 daily signal | PR9 | ✅ BUY/SELL/HOLD 三栏 + mode 判定 |
| 3 实时告警 | PR10 | ✅ close<85 + 强赎临近 |
| **4 retrospective** | **PR11 + PR12** | ✅ cb_exit_type 沉淀 + retrospective sleeve 接通 |

**CB sleeve 已在北极星 4 根支柱上全部完成 PR1-PR12 工程闭环.** 实盘等 7 月首次 rebalance → 9 月首次 retrospective 报表 → PM 决策 v7 配比 Option 2 (CB 10%) 升级或归档.

## 不在 PR12 范围

- L5.1: chi-square p-value for categorical (rating bucket 分布显著性), 留 ≥30 笔后做
- CB benchmark α 接入: 集思录 EW 自建净值曲线, 留 L5.1
- 自动 yaml 调参 / online gradient — **永远不做** (Backstop #4 明文)

## "≥ 90 天 + ≥ 30 笔不撬" backstop 兼容性

PR12 **未撬任何 yaml 参数** (n_entry / exit_threshold / stop_loss / sizing / weight 全部不动). 仅在 learn_from_trades.py 加 CB sleeve 消费, 不改策略. backstop 完全兼容.

## 关联
- [[cb-double-low-pr8-journal-portfolio-2026-06]] schema 前置
- [[cb-double-low-pr11-closed-trades-html-2026-06]] cb_exit_type 沉淀前置 (PR12 直接消费)
- [[session_2026_06_08_self_learning_pipeline]] L5 base pipeline + 5 条 Backstop
- [[project-north-star]] 支柱 4 闭环
- [[cb-double-low-pr6-v7-overlay-2026-06]] STRONG PASS 基础 (9 月 retrospective 验证是否真兑现)
