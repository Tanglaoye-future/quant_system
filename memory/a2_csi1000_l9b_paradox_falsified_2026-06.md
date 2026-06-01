---
name: a2-csi1000-l9b-paradox-falsified-2026-06
description: A2 CSI1000 L9-B 预检查软证伪 — HS300 ROIC×ROE Spearman 全 asof 0.92-0.95, AR YoY 季节性主导, 切 universe 不能解耦; 省 3-5 hr CSI1000 universe 接 loader + 1000 ticker prefetch + sweep 工程; 第 15 条证伪
metadata:
  type: project
---

## 一句话结论

CSI1000 切 universe 假设建立在 "小盘 ROIC/ROE 解耦 + AR YoY 摆脱行业噪声"。**HS300 现有数据 paradox 预检查 4 个 asof 全 Spearman(ROIC, ROE) ∈ [0.92, 0.95]**, 远超 0.7 同质阈值; AR YoY 横截面 median ≈ -0.78 一致负是中国 A 股累计申报季节性 artifact 而非公司质量信号。**切 universe 不可能解耦, 软证伪 A2, 不投 3-5 hr CSI1000 prefetch + sweep**。第 15 条证伪。

## driver + 假设

- **handoff**: session_2026_06_01_handoff #1 backlog (cheap ROI #1, "工程已落改 universe 即可")
- **L9-B HS300 结果** ([[equity_factor_l9b_falsified_2026-05]]):
  - L9B-roic-10:  0.761 (-0.096) — 归因 ROIC 与 ROE 重复
  - L9B-ar-10:    0.826 (-0.031) — 归因 AR YoY 大盘行业属性主导
  - L9B-both-05:  0.838 (-0.019)
- **假设**: 小盘 ROE/ROIC band 不同 → 解耦; AR YoY 在小盘逃脱行业噪声

## 预检查反驳 (HS300 现有 abstract, 零 prefetch)

| asof | n | Pearson(ROIC, ROE) | Spearman | AR_YoY median | AR_YoY std |
|---|---|---|---|---|---|
| 2023-06-30 | 252 | 0.831 | **0.922** | -0.780 | 0.159 |
| 2024-06-30 | 252 | 0.994 | **0.915** | -0.781 | 1.041 |
| 2025-06-30 | 252 | 0.942 | **0.942** | -0.785 | 0.108 |
| 2026-03-31 | 252 | 0.932 | **0.949** | +0.407 | 1.113 |

### 反驳 1: ROIC ≡ ROE (rank 等价)

**Spearman 0.92-0.95 → ROIC 与 ROE 在 HS300 实际上是同一 rank 信号**。
切 CSI1000 小盘只会**更同质**:
- 小盘资本结构相似 (低 leverage, debt/equity 离散度低)
- ROE/ROIC 的差异主要来自 leverage; leverage 离散度小 → ρ 升, 不降
- 小盘行业更集中 (科技 + 消费 + 制造为主) → 不可能解相关

切 universe 不是 ROIC alpha 的解药。

### 反驳 2: AR YoY 是季节性 artifact, 不是质量信号

- 2023/2024/2025-06-30 三个 asof, median 一致 -0.78, std 异常波动 (0.16/1.04/0.11)
- 这是因为我们用 latest_n_indicator_values 取最近两期, 中国 A 股 abstract:
  - Q2 (asof 06-30 + 90 天 lag → cutoff 03-31) 取到 Q4-2022 cumulative (年度) vs Q1-2023 (单季) 的 Q1/Q4 比, 不是真正 YoY
- 2026-03-31 cutoff 后 median +0.41 反向, 同一 artifact 不同段
- 这是**算法 bug 而非 alpha**: AR YoY 的当前公式是 (latest - prev) / |prev|, prev 在中国累计申报体系下不是真"前一期相同口径"

→ 任何 universe (HS300 / CSI1000 / CSI2000) 都失败, 与 universe 大小无关

## 与 14 条证伪 + 4 次 paradox 模式的对齐

完美匹配 [[session_2026_06_01_handoff]] paradox 表 3 类风险:

| paradox 类别 | A2 体现 |
|---|---|
| 信号互斥/重复 | ROIC × ROE Spearman 0.93 平均 → ROIC 是 ROE 的同义词 |
| Base rate 结构 | AR YoY 横截面 std 被中国累计申报季节性主导, 不是 alpha |
| Sample size | N/A (前两类直接 design 错, 没到 sample 这层) |

第 5 次同模式打脸 — 预检查 (handoff 估 cheap ROI) 一查就证伪, 与 L7-A / L8 fundamentals / L9-B ROIC / A1' 同。

## 工程产出

- **新增** `scripts/research/a2_csi1000_l9b_paradox_precheck.py` — 复用模板, 任何 "切 universe / 加因子" 提议都可改阈值复用
- **未改** loader (没加 csi1000 universe 路径)
- **未改** factors.py (L9-B 已落, 默认权重 0 不变)
- **未改** yaml
- **新增** `data/backtest/_a2_precheck/a2_paradox_summary.json` — 结构化证据

## 五层 efficient set 同构升级

承 [[session_2026_06_01_handoff]] 四层同构, A2 paradox 证伪进一步收敛:

| 层 | efficient 配置 | 证伪累积 |
|---|---|---|
| 组合层 v5 | HK25/A_mom10/A_mr10/zhuang40/QQQ5/GLD10 | 5 |
| HS300 因子层 | L8D2 (fcf=0 + L9-B=0) | 2 |
| zhuang sleeve | L1-E + L6-A equal | 3 |
| HK sleeve | widen on + gate off | 1 |
| **A 股因子 universe 维度** | **HS300 (CSI1000 切换不可行)** | **1 (本条)** |

→ alpha 通道再窄: 不在因子层, 不在 universe 切换, 仅剩外部信号 + 真做空 + 实盘 KPI 收敛。

## Why
保留是为了**未来不再重做** "切 universe 救相关性高的因子" 这类提议。任何后续 "改 universe 加 X 因子" 必须先 paradox precheck (5 行命令), 不要再投 prefetch 工程。

## How to apply
- 收到 "切 universe / 用小盘 / 用大盘 X 因子" 提议 → 立刻跑 `python scripts/research/a2_csi1000_l9b_paradox_precheck.py` 模板 (改 indicator 名), 或要求用户提供同等横截面 ρ 证据再决定
- A2 在新数据源接入 (非 akshare, 非 baostock 同源) 之前**彻底封死**
- AR YoY 算法本身需要重写才考虑复活 (改用真年度 YoY 而非 quarter-of-cumulative 对比, 见反驳 2)

## 链接
- 上游: [[equity_factor_l9b_falsified_2026-05]] [[session_2026_06_01_handoff]]
- 同模式: [[zhuang_l7a_falsified_2026-05]] [[zhuang_l8_fundamentals_falsified_2026-05]] [[a1prime_southbound_gate_falsified_2026-06]]
- 教训源: [[feedback_user_collab_style]] (双窗口 + 预检查 sanity)
