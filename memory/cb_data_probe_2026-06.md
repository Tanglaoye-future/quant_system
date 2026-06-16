---
name: cb-data-probe-2026-06
description: 可转债数据 probe 结论 PASS（akshare 全套可用 + 无 survivorship bias + 容量 < 100M AUM 无障碍），驱动 cb_double_low sleeve 立项；区别于已死 hsgt/zt_pool/lhb_panic 路径
metadata:
  type: project
---

## 一句话结论

A 股 sleeve 在 v7 4 支柱框架下饱和（18 条证伪）后，用户问"还有收益率更高的策略"。CB 双低 probe **数据层 PASS** — akshare 4 个核心接口覆盖完整（历史价格+溢价率面板 + 强赎事件 + 实时 spot），**无 survivorship bias**（含 2007 起退市债），容量 < 100M AUM 无障碍。**与已死的 hsgt 北向 / zt_pool 涨跌停 / LHB 机构席位 全不同**，CB 不撞 akshare 30 日窗口限制。立项 cb_double_low sleeve，详见 [[convertible-bond-sleeve]] spec。

## Probe 矩阵（2026-06-15 实测）

| endpoint | 用途 | 覆盖 / 字段 | 状态 |
|---|---|---|---|
| `akshare.bond_zh_cov()` | universe 池 + 发行信息 | 1022 行 × 19 列；2007-2026 上市；**含已退市债**（189 只 2019 前上市） | ✅ |
| `akshare.bond_zh_cov_value_analysis(symbol)` | backtest 主面板 | 6 列：日期/收盘价/纯债价值/转股价值/纯债溢价率/转股溢价率；回溯 2019-2020；退市债 last 截止退市日 | ✅ |
| `akshare.bond_cb_redeem_jsl()` | exit + filter | 324 行 × 18 列：触发日/最后交易日/到期日/强赎价/强赎条款/强赎状态 | ✅ |
| `akshare.bond_zh_hs_cov_spot()` | 实盘 daily ranking | 332 行 × 15 列实时 OHLCV | ✅ |
| `akshare.bond_zh_hs_cov_daily(symbol)` | 备用 OHLCV | 6 列 OHLCV；回溯 2015-2020；**不含溢价率** | ⚠️ 备用 |
| `akshare.bond_cb_jsl()` | 集思录补充 | 30 行（分页/采样不全）| ⚠️ 不可靠，不主用 |
| `akshare.bond_cb_adj_logs_jsl()` | 转股价下修 | 3 行（极不全） | ❌ 数据残缺 |

## Survivorship bias 验证（关键差异于已死路径）

直接验证两只**已下市**可转债是否仍返回历史数据：
- **113008**（已退市）：`bond_zh_cov()` 列表✅含 + `value_analysis` 返回 1183 行（2015-02-16 → 2021-01-18，覆盖至退市日）
- **113537**（已退市）：`bond_zh_cov()` 列表✅含 + `value_analysis` 返回 1344 行（2019-06-10 → 2024-12-18）

**结论**：CB 数据**不像 hsgt/zt_pool 那样只保最近 30 日**，能完整 4y/8y backtest 含退市样本。**这是 CB 与已死路径的结构性差异**。

## 数据量评估

- 1022 只 × ~0.5s/call = **~8.5 分钟全量 backfill**
- DuckDB cache 后日级增量 < 30s
- 实盘 daily 用 `bond_zh_hs_cov_spot()` 一次 1s 拿全市场 332 行截面

容量上限：< 10M AUM 无障碍；> 100M 撞小盘债流动性（单只剩余规模 1-5 亿）。本 sleeve 5-10% 占比下 v7 组合规模 < 5M，**安全**。

## 与已死路径的对比（避免下次混淆）

| 路径 | 数据状态 | 是否撞 4 支柱 | CB 是否同问题 |
|---|---|---|---|
| A1 北向资金日级 | ❌ 2024-08 永久停更 | 撞支柱 1（纯资金面） | ❌ CB 是债性条款选标的，扩支柱 1 后✅ |
| zt_pool 涨跌停 | ❌ akshare 仅 30 日 | 撞支柱 2（反趋势） | ❌ CB value_analysis 全历史可用 |
| LHB 龙虎榜 trigger | ❌ T+1 滞后 | 撞支柱 2 | ❌ CB 双低用日级 EOD 数据，无 T+1 问题 |
| 主力净流入 net_flow | ❌ akshare 估算噪声 | 撞支柱 1 | ❌ CB 溢价率是官方计算字段 |

**CB 是首个通过 4 支柱 cross-check（扩展后）+ 数据 probe 全 PASS 的新方向**。

## 不要做（避免下次重发现）

- 不要再 probe `bond_cb_jsl` 作面板数据源 — 30 行采样不全
- 不要再 probe `bond_cb_adj_logs_jsl` 作转股价下修主源 — 3 行残缺，从 `bond_zh_cov_info` 拿
- 不要用 `bond_zh_hs_cov_daily` 当主面板 — 无溢价率字段，做双低无用
- 不要假设 2018 全窗口可回测 — value_analysis 早期 2019-2020 起，真实 8y 起点可能是 2020-01-01（6y 窗口）
- 不要跳过 universe filter 直接用 1022 全样本 — 强赎/到期/低评级/低规模债会污染回测

## Probe 时间成本

- akshare 接口枚举 + 4 端点 probe：~5 min
- Survivorship bias 验证（两只退市债）：~3 min
- 总：~8 min

## v1.1 — 2026-06-16 PR4 strategy 端到端 smoke 实测 3 个 nuance（PR5/PR6 必须处理）

PR4 落地后 `scripts/research/cb_target_today.py --n 200` 真 universe 跑 `compute_target_portfolio`，pipeline 全跑通但暴露 3 个 spec 隐含假设与 2026 实况不符：

### Nuance 1 — asof 当日 panel 覆盖率仅 59%（118/200 只）

200 只 active 头部样本里，仅 118 只在 asof=2026-06-15 有 panel 数据。原因可能是停牌 / 即将退市 / akshare 当日缺口。**PR5 backtester 每个交易日都会撞**：覆盖率 < X% 是否 skip 当天？
- 推荐 best-effort + log warning（CB 流动性本身就差，硬卡 skip 会大量丢交易日）
- backtester 必须 emit `panel_coverage` 序列到 M0 artifact，用于事后审计

### Nuance 2 — 双低 score 中位 138（远高于 spec 假设的 sweet spot 100-105）

2024 后 CB 估值整体抬升。入场 20 只里 **19/20 的 score > 150（spec 默认 `exit_dual_low_threshold=150`）**，意味 cold start 第一天的入场池立刻触发卖出。
- spec 150 阈值基于 2018-2021 历史拟合，2024+ 校准失效
- **PR6 双窗口 backtest 必须做 exit_threshold sweep**（候选：150 / 170 / 190 / 相对值 `top_N_median + 30`）
- 入场 score 分布参考：min=129.68 / max=180.26 / 头 20 只 median ≈ 173

### Nuance 3 — 入场 #1 可能是折价转债（负溢价 -11.58%）

`dual_low_score = close + premium` 公式下，负溢价（转股价值 > 债价）会自然落到顶部。但负溢价债往往是已公告强赎 / 即将退市的尾盘行情。
- 当前 127090 兴瑞转债 active 但 premium=-11.58% 需要 verify（可能 redeem 表延迟标）
- **PR5 backtester 建议加 `premium_rate >= -5%` 软底**（避免折价债主导入场），candidate 落 yaml `min_conversion_premium`

### 全市场 backfill 实测时间

- 200 只混合（含老券）cold backfill 14 天 panel：**69.3s (0.35s/只)** vs 10 只新债 0.07s/只 — 5x 偏差源是 sample 含老券（行数 1183 vs 49）
- 全市场 946 只外推真实 cold ≈ **5-7 min**（vs spec 8.5 min，合理范围）
- DuckDB cache 第二次 < 0.005s/只 (221x speedup)

## 链接

- 立项 spec：[[convertible-bond-sleeve]]
- 4 支柱扩展驱动：[[project-north-star]]（支柱 1 加债性 + 支柱 2 risk-parity 豁免，2026-06-15 扩展）
- 同期未试方向 v7 frontier：[[v7-efficient-frontier-2026-06]]
- 对照：已死路径 [[a1-northbound-dead-southbound-alive-2026-06]] / [[capitulation-strategy-falsified-2026-06]]

**Why**: 2026-06-15 用户问"A 股还有收益率更高的策略"。Probe 必须先做避免投 ~10 hr 工程后才发现数据死亡（北向资金教训）。本 memory 永久保留 probe 结果，未来"是否值得 CB"提问直接引用，避免重复 probe。
**How to apply**: 接到任何 CB 相关需求（双低/转股套利/可交换债/...）时，先引用本 memory 确认数据可得性 + survivorship 状态；若新分支需要本 memory 未 probe 的字段，新增 probe 不重做 4 端点；若 cb_double_low 双窗口证伪，写 falsified memory 时引用本 memory 作数据层"无故障"证据。
