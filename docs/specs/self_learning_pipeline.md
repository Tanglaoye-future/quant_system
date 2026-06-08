# Spec — Self-Learning Pipeline (实盘 RL fine-tuning 类比)

## 背景与诚实定义

用户 2026-06-08 提出："把实盘视作强化学习，预训练（8y 回测 + 17 条证伪）已完，
希望程序可以自我学习进步，而不是只活在过去。"

**诚实翻译**（避免 RL 比喻过度承诺）：
- 当前系统：offline 监督学习 + 实盘 frozen-policy
- 用户想要：让 daily 产生的每笔交易都能被未来 retrospective 反馈
- **本 spec 落地的 ≠ online gradient**, 是 **数据采集 + retrospective 分析 + PM
  决策辅助 三件套**。最终输出是给 PM 看的报表; yaml 调参仍走双窗口 4y+8y backtest
  人工通道。

"程序学到的是 应该问什么问题, 不是 自动改答案。"

## 5 条硬性 Backstop (写进每个 PR header, 永不撞)

1. **17 条证伪 + 四层 efficient set 同构是硬墙**
   - candidate 落 yaml 前必须自动 cross-check 已死方向
     ([[a1_northbound_dead_southbound_alive_2026-06]] /
     [[zhuang_l8_fundamentals_falsified_2026-05]] /
     [[v5_efficient_frontier_2026-05]] 等)
   - L5 报表 hardcode falsified-methods manifest, candidate 撞墙直接 SOFT-FALSIFY

2. **双窗口 4y+8y Sharpe 同向 PASS 才落 yaml**
   - [[session_2026_06_01_handoff]] 4 次同模式打脸纪律
   - AMBIGUOUS verdict (Spearman 0.4-0.6) ≡ SOFT-FALSIFY (不投 backtest)

3. **实盘 < 90 天 / < 30 笔 closed 不能撬 frontier**
   - [[capitulation_strategy_falsified_2026-06]] paradox 第 5 类
     (execution-vs-strategy 错配) — 实盘小样本不是 alpha 信号源
   - L5 报表 N < 10 时强制 "样本不足" warn, 拒绝输出分布差结论

4. **PM 决策权 — 程序产出报告, 不自动改 alpha**
   - 任何 yaml 调参经 AskUserQuestion 人工通道
   - 程序永不直接 mutate config/*.yaml

5. **采集与 alpha 决策完全分离**
   - feature snapshot 写 journal 永远 nullable + 默认 NULL 不影响现有 daily 行为
   - L2/L3/L4 采集层禁止以"采集"名义引入新计算 (新因子 / 新信号) —
     只能 snapshot daily 已算出的 feature
   - daily 跑路径回归测试每个 PR 都跑 (基线 283 + 持仓 v2 全量)

## 5 PR Roadmap (按顺序, 每个独立 review)

### PR L1 — 基建 schema (本 PR)

- `journal_trades.entry_features JSONB` (nullable)
- `journal_trades.exit_features JSONB` (nullable)
- `zhuang_trades.entry_features JSONB` (nullable)
- `zhuang_trades.exit_features JSONB` (nullable)
- alembic migration `<rev_id>_add_features_jsonb` (down_revision = `f4a5b6c7d8e9`)
- 1 test 验 JSON round-trip (内存 SQLite + JSONColumn fallback to JSON)
- 0 alpha 影响 (nullable + 无 daily code 路径变更)

### PR L2 — A_mom + HK_mom 采集

`scripts/daily/daily_equity.py` 在 `journal.open_trade` 前组装 entry_features dict:
```python
entry_features = {
    "rsi": float,              # 已存于 enriched df
    "vol_ratio": float,        # 量比
    "ma20_above_ma60": bool,
    "dist_to_20d_high_pct": float,
    "zscore_within_universe": float,  # bottomup 排序分
    "sector_sw1": str,         # 申万一级 (开 universe loader 已有)
    "market_gate_on": bool,
    "asof": "YYYY-MM-DD",
}
```
- 全部从 `enriched_df` / 已有 universe loader 读, **零新计算**
- HK_mom 同款 (RSI / vol_ratio / MA bands 已存)
- 测试: mock open_trade, 验 entry_features 被完整传入

### PR L3 — zhuang 采集

`scripts/daily/daily_zhuang.py` 在 `ZhuangJournal.open_trade` 前:
```python
entry_features = {
    "accumulation_ma_convergence": float,
    "accumulation_volume_asymmetry": float,
    "accumulation_price_consolidation": float,
    "accumulation_turnover_decline": float,
    "accumulation_vp_divergence": float,
    "phase": str,              # A / A+ / B
    "atr_at_entry": float,
    "market_cap_band": str,    # "50-200" / "200-500" / "500-2000"
    "market_trend_on": bool,   # 趋势门状态
    "asof": str,
}
```
- 全 snapshot daily_zhuang 已扫出的 5 分量, 零新计算

### PR L4 — exit 采集

equity_factor `RiskMonitor` + zhuang exit 路径在 `close_trade` 前:
```python
exit_features = {
    "exit_type": str,             # "trailing_stop"/"break_ma60"/"take_profit"/"overbought"/"time_stop"/"distribution"/"momentum_stop"
    "hold_days_bucket": str,      # "0-5"/"6-20"/"21-60"/"60+"
    "max_drawdown_during_hold_pct": float,  # 从 journal_snapshots 算
    "max_profit_during_hold_pct": float,
    "asof": str,
}
```
- 从已存 `journal_snapshots` / `zhuang_snapshots` 算, 零新源数据

### PR L5 — retrospective 报表

`scripts/research/learn_from_trades.py`:

```
usage:
  --since YYYY-MM-DD          (default = 实盘起点 2026-05-22)
  --min-sample N              (default = 10, < N warn 不出分布差)
  --output md|json|both
```

输出:
1. **样本量校验** — closed N < min_sample → 强制 warn, 不输出特征分布差
2. **Winner vs Loser feature gap** — entry_features 每 numeric/categorical 维度:
   - mean (winner) vs mean (loser)
   - median, std
   - Mann-Whitney U / chi-square p-value
3. **17 条证伪 cross-check** — candidate 特征撞墙警告:
   - 例如 winner mean RSI 显著低 → "捕捉低 RSI = mean-reversion 信号" → 撞
     [[a_mr_v2_falsified_2026-05]] (A_mr v2 5 case 全 plateau)
4. **样本量充分时输出 candidate 报告** — 仍明文 "请走 backtest sweep 8y 双窗口
   再决定是否落 yaml"

入口手动跑 (不进 deploy/run_daily.sh), 月度 KPI 旁边触发:
```bash
venv/bin/python scripts/research/learn_from_trades.py --since 2026-05-22
```

## 验收 (本 spec / L1 PR)

- pytest tests/ 不回归 (基线 283 → L1 后 ≥ 284)
- alembic heads 单 head 升到 L1 新 rev
- daily run 跑完无 NULL pollution (entry_features 字段默认 NULL, 既有 daily 路径
  不写它 → 既有 daily 行为零变化)
- DB ↔ JSON verify_dualwrite 全 OK

## L2-L5 触发条件

- L2 / L3 / L4 在 L1 merge 后逐个开 PR (按 06-07 harness-first)
- L5 报表脚本可与 L4 同 PR 或独立, 用户决策
- **首次有效报表跑出 ≈ 实盘 ≥ 30 笔 closed** (估计 2026-09)
- 2026-06-30 第一次月度 KPI 仍按 [[monthly_kpi_scaffold_2026-05]] 跑, 不依赖本 pipeline

## 不做 (明文)

- 不做 yaml 自动调参 / online gradient — Backstop #4
- 不在采集层加新因子 / 新信号 — Backstop #5
- 不在样本量 < 30 时输出 candidate (强 warn) — Backstop #3
- 不绕过双窗口 backtest 直接落 yaml — Backstop #2
- 不让 L5 报表 candidate 直接撞已死方向 — Backstop #1

## 关联

- [[session_2026_06_01_handoff]] — 17 条证伪 + 4 次同模式打脸纪律
- [[v5_efficient_frontier_2026-05]] — 当前 frontier 不可撬
- [[monthly_kpi_scaffold_2026-05]] — 月度 KPI 与本 pipeline 并行
- [[capitulation_strategy_falsified_2026-06]] — execution-vs-strategy 错配
- [[feedback_harness_first_pr_split]] — 5 PR 拆分纪律
