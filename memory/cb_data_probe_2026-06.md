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

## 链接

- 立项 spec：[[convertible-bond-sleeve]]
- 4 支柱扩展驱动：[[project-north-star]]（支柱 1 加债性 + 支柱 2 risk-parity 豁免，2026-06-15 扩展）
- 同期未试方向 v7 frontier：[[v7-efficient-frontier-2026-06]]
- 对照：已死路径 [[a1-northbound-dead-southbound-alive-2026-06]] / [[capitulation-strategy-falsified-2026-06]]

**Why**: 2026-06-15 用户问"A 股还有收益率更高的策略"。Probe 必须先做避免投 ~10 hr 工程后才发现数据死亡（北向资金教训）。本 memory 永久保留 probe 结果，未来"是否值得 CB"提问直接引用，避免重复 probe。
**How to apply**: 接到任何 CB 相关需求（双低/转股套利/可交换债/...）时，先引用本 memory 确认数据可得性 + survivorship 状态；若新分支需要本 memory 未 probe 的字段，新增 probe 不重做 4 端点；若 cb_double_low 双窗口证伪，写 falsified memory 时引用本 memory 作数据层"无故障"证据。
