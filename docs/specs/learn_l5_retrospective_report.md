# Spec — L5: Retrospective 报表脚手架

L5 of [[self_learning_pipeline]]. 所有 5 条 Backstop 在此 PR 最终被报表 enforce.

## 目标

读 PG 的 closed trades (journal_trades + zhuang_trades 含 L2-L4 采集的
entry_features / exit_features), 输出 **winner vs loser 特征分布差** + 17
条证伪 cross-check + 严格小样本警告 —— 给 PM 看的报表, **不自动改 alpha**。

## 入口

```bash
venv/bin/python scripts/research/learn_from_trades.py \
    [--since 2026-05-22] \
    [--min-sample 10] \
    [--output md|json|both] \
    [--out-dir logs]
```

- `--since`: closed trade 起始日 (default = 实盘启动 2026-05-22)
- `--min-sample`: < N 时强 warn 不出分布差 (default = 10, Backstop #3)
- `--output`: md / json / both (default = both)
- `--out-dir`: 输出目录 (default = logs/)

输出文件:
- `logs/learn_<YYYY-MM-DD>.md` (人读)
- `logs/learn_<YYYY-MM-DD>.json` (机读 — 未来 L5.1 dashboard 可消费)

## 报表 6 段结构

### §1. 样本量校验 (Backstop #3)
- 各 sleeve (A_mom / HK_mom / zhuang) closed trade 计数
- N < min_sample 时**强 warn**, 该 sleeve 后续段跳过, 报表头部红色 banner
  "样本量不足, 任何 winner-vs-loser 结论无统计学意义"
- 不阻止脚本继续跑其它 sleeve, 但**绝不**输出分布差结论

### §2. 总体 PnL 描述
- 每 sleeve win rate / avg win pct / avg loss pct / sharpe-like (mean/std)
- hold_days 分布 (median / 桶化)
- 与 monthly_kpi_scaffold 重叠的字段尽量不重 (避免与 06-30 月度 KPI 报表打架)

### §3. Winner vs Loser entry_features 分布差 (numeric)
- 仅 N >= min_sample 时输出
- 对 entry_features 每 numeric key:
  - winner_n / loser_n / winner_mean / loser_mean / delta
  - Mann-Whitney U p-value (本 PR 自实现, 不依赖 scipy)
- 标 `⚠ p < 0.05` 提示统计显著, 但**仍需 backtest 8y 双窗口验证 (Backstop #2)**

### §4. Winner vs Loser entry_features 分布差 (categorical)
- 对 categorical key (sector_sw1 / phase / market_trend_on) 输出 contingency
  table
- p-value (chi-square) 留 L5.1 (需 scipy), 当前仅 descriptive

### §5. exit_features 分布
- exit_type 分布 (winner vs loser 各类占比)
- max DD/profit during hold (mean / median / dist)
- hold_days_bucket (winner vs loser)

### §6. 17 条证伪 cross-check (Backstop #1)
- hardcoded `FALSIFIED_PATTERNS` manifest: list of (pattern, falsified_doc_ref)
- 对 §3-§4 的 candidate feature, 自动 scan manifest:
  - candidate 名字 / 含义撞墙 (例如 RSI 显著低于 loser → 触发 [[a_mr_v2_falsified_2026-05]] 路径)
  - 触发 → 标 ⚠ SOFT-FALSIFY tag + 链接证伪文档
- 报表 footer 强制写:
  ```
  ⚠ 本报表仅为 PM 决策辅助。任何 yaml 调参须先通过双窗口 4y+8y backtest 同向
  PASS (Backstop #2)。命中 SOFT-FALSIFY 标记的方向不应再尝试 (Backstop #1)。
  ```

## Mann-Whitney U 不带 scipy (Backstop #5 — 不引新依赖)

normal approximation 实现:
- 合并 a/b 赋秩 (同值平均秩)
- U = sum(ranks_a) - n_a*(n_a+1)/2
- mean_U = n_a * n_b / 2
- std_U = sqrt(n_a * n_b * (n_a + n_b + 1) / 12)
- z = (U - mean_U) / std_U
- p_two_sided = 2 * (1 - Φ(|z|))
- Φ 用 math.erf: `Φ(x) = 0.5 * (1 + erf(x / sqrt(2)))`

n < 20 时 normal approximation 偏差大, 但本 PR 强 warn N<10 已挡 — 真到 ≥10 后
n=10 仍是 borderline, 报表里需明文标注.

## Falsified Patterns Manifest

hardcoded `FALSIFIED_PATTERNS: list[dict]` in `learn_from_trades.py`:

```python
FALSIFIED_PATTERNS = [
    {
        "name": "northbound_overlay",
        "match_keys": ["sector_sw1", "market", "asof"],  # 触发条件 (TBD by L5.1)
        "doc_ref": "a1_northbound_dead_southbound_alive_2026-06",
        "severity": "DEAD",  # akshare 2024-08 停更, 不投 backtest
    },
    {
        "name": "southbound_gate_threshold",
        "match_keys": [...],
        "doc_ref": "a1prime_southbound_gate_falsified_2026-06",
        "severity": "DEAD",
    },
    {
        "name": "hs300_roic_ar_yoy",
        "match_keys": [...],
        "doc_ref": "equity_factor_l9b_falsified_2026-05",
        "severity": "DEAD",
    },
    {
        "name": "zhuang_position_max_count",
        "match_keys": [...],
        "doc_ref": "zhuang_l7a_falsified_2026-05",
        "severity": "DEAD",
    },
    {
        "name": "zhuang_score_threshold_loosen",
        "match_keys": [...],
        "doc_ref": "zhuang_l7b_falsified_2026-05",
        "severity": "DEAD",
    },
    {
        "name": "zhuang_fundamentals_gate",
        "match_keys": [...],
        "doc_ref": "zhuang_l8_fundamentals_falsified_2026-05",
        "severity": "DEAD",
    },
    # ... 17 条全列, 详见 src
]
```

L5 本 PR 先骨架 — manifest 包含 17 条名字 + doc_ref + severity, 完整 match
逻辑 (regex / threshold / candidate name → pattern) 留 L5.1 (实盘 ≥30 笔后
真用得上时再 implement match). 当前 L5 cross-check 仅: candidate feature
**名字** 或 **关键词** 命中 manifest 名字 → warn.

## 测试

- `tests/research/test_learn_from_trades.py`:
  - fixture 注入内存 SQLite (含 entry/exit_features) 模拟 closed trades
  - 3+ case:
    1. N < min_sample → 强 warn + 不输出分布差段
    2. N >= min_sample → §3 numeric + §6 manifest 段输出, MWU p-value 数值合理
    3. manifest 命中 (mock candidate name 撞 "zhuang_position_max_count") → ⚠ tag

## 验收

- pytest tests/ 不回归 (base 302 → L5 后 ≥ 305)
- 不引入 scipy 等新依赖
- markdown 报表手动验: closed trades 表(当前实盘只有 1 笔 — 601066 已退) →
  脚本运行强 warn "样本量不足", 不抛错

## 不做（明文）

- 不自动改 yaml (Backstop #4 — 这是脚本输出报表的全部边界)
- 不接入 chi-square p-value (留 L5.1, 需 scipy)
- 不接入完整 falsified pattern matcher (留 L5.1, 当前只 manifest stub)
- 不接入 dashboard / 前端 (报表 = logs/*.md, 用户 cat 看; future PR 接入)
- 不集成 deploy/run_daily.sh (月度 KPI 时手动跑, 非每日)

## 关联

- [[self_learning_pipeline]] — 总路线 + 5 backstop
- [[monthly_kpi_scaffold_2026-05]] — 月度 KPI, 与本报表并行 (不重叠)
- [[session_2026_06_01_handoff]] — 17 条证伪 + paradox 6 类 + 四层 efficient set 同构
- [[v5_efficient_frontier_2026-05]] — Backstop #1 守墙
