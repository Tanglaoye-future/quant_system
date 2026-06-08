# Spec — L5.0.1: benchmark-relative α 列（M2）

## 背景

L5 retrospective 报表当前只看绝对 pnl，结果是 **混淆 β 与 α**。

实证：2026-05-22 ~ 06-08 大盘同期：
- HS300 -0.58%（A_mom benchmark）
- CSI500 -3.80%（zhuang benchmark）

我们的浮亏 -0.20% 加权，**两个 sleeve 都跑赢各自 benchmark +1.4%** — 这是 α 真正展现的事实，但 L5 当前报表看不出来。

用户 06-08 question："为什么大面积持仓回撤" 的核心误判就是 **没看到 benchmark-adjusted α**。

## 改动范围

| 文件 | 改动 |
|---|---|
| `scripts/research/learn_from_trades.py` | 加 helper `_fetch_benchmark_returns(start, end, market)`; build_report 加 sleeve-level **`alpha_summary` 字段** + per-trade **`benchmark_pnl_pct`** + **`alpha_pct`** = (trade pnl - same-period benchmark return); markdown 加 §2.5 "α vs β 归因" 段 |
| `tests/research/test_learn_from_trades.py` | +2 case: benchmark fetch fail-soft / alpha 算法正确性 |

## 数据源 / benchmark 映射

| sleeve | benchmark code | benchmark name |
|---|---|---|
| A_mom (strategy=`equity_momentum`, market=`a_share`) | `sh.000300` | HS300 |
| HK_mom (strategy=`equity_hk_momentum`, market=`hk_share`) | TBD — HSCHK100 / HSI; L5.0.1 先标 None 占位 |
| zhuang | `sh.000905` | CSI500 |
| mean_reversion (M1 后启用) | `sh.000300` | HS300 (与 A_mom 同 universe) |

HK / mean_reversion 留 None 占位时 alpha_pct = None, 不影响其它 sleeve 输出。

## 计算

per-trade:
```python
benchmark_pnl_pct = bench_close_at_exit_date / bench_close_at_entry_date - 1.0
alpha_pct = pnl_pct - benchmark_pnl_pct
```

sleeve-level:
```python
alpha_summary = {
    "avg_benchmark_pnl_pct": mean(benchmark_pnl_pct for closed),
    "avg_alpha_pct": mean(alpha_pct for closed),  # 真 α
    "n_alpha_positive": count(alpha_pct > 0),
}
```

数据源用 baostock (实测可拉 sh.000300 / sh.000905, [[session_2026_06_08_self_learning_pipeline]] 已验证)。fail-soft: benchmark 拉不到 → alpha_pct=None, sleeve 报表段标 "benchmark 不可用"。

## Markdown 输出新段

```
### §2.5 α vs β 归因

| sleeve | n | avg pnl | avg benchmark | **avg α** | α>0 笔数 |
|---|---|---|---|---|---|
| A_mom | 1 | +3.46% | -0.58% | **+4.04%** | 1/1 |
| HK_mom | 0 | — | — | — | — |
| zhuang | 0 | — | — | — | — |

注: α = trade pnl_pct - 同期 benchmark return; 若 α > 0 = 选股/择时跑赢大盘
```

## Backstop 严守

- **#1** 17 条证伪硬墙: benchmark 选用现成指数 (HS300/CSI500), 不引入新因子
- **#2** 双窗口纪律不动: 仅报表层加列, 不改 yaml
- **#5** 0 新依赖: 用现有 baostock 拉指数 (实证已验)
- fail-soft: 任何 benchmark 拉取异常 → alpha_pct=None, 报表段标 "不可用"

## 验收

- `pytest tests/research/` 不回归 (base 11 case → +2 ≥ 13)
- 实盘 dry-run: `venv/bin/python scripts/research/learn_from_trades.py --since 2026-05-22` →
  - A_mom 已退出 1 笔 (601066 +3.46% / 持有 5-26 → 6-5) → benchmark 同期 HS300 ≈ -0.5%~+0% → α ≈ +3.5%~+4%
  - 报表 §2.5 段输出非空

## 不做（明文）

- 不接入 HK benchmark (HSCHK100 数据源 / HSI 选哪个 = L5.0.2 决策)
- 不算 risk-adjusted α (Sharpe / IR — 需更大 N, 留 L5.1)
- 不接入 per-day α (实盘 hold 期间逐日 β-adjusted) — 当前每 trade 算 entry→exit 一次

## 关联

- [[self_learning_pipeline]] — 总路线 + 5 backstop
- [[session_2026_06_08_self_learning_pipeline]] — benchmark 拉取实证
- [[learn_l5_retrospective_report]] — L5 报表 base spec
- 06-08 conversation: 用户 "大面积持仓回撤" 主观感受的根因是 **β 拖累 + 报表无 α 列**
