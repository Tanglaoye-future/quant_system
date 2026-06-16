# Spec — 可转债双低 sleeve（cb_double_low v1）

## 背景

[[project_north_star]] 4 支柱扩展驱动（2026-06-15 已确认）：
- **支柱 1** 从"基本面（PE/PB/ROE/...）选标的" 扩为"**基本面或债性条款选标的**（PE/PB/ROE/转股溢价率/纯债溢价率/剩余期限/...）"
- **支柱 2** 增补："**risk-parity 类低波动资产可豁免趋势择时**"（CB 双低本质是"低估均值回归"，不撞"反趋势不作 alpha"红线）

驱动需求：v7 当前 efficient frontier 4y Sharpe 1.842 / 8y 1.455，A 股 sleeve 已饱和（18 条证伪）；用户问"A 股还有收益率更高的策略"，CB 双低是当前唯一未试过的、能在 A 股账户内执行、与现有 6 资产相关性接近 0 的方向。

预期组合占比：**5-10% 试水**（从 A_mom 或 GLD/IBIT 抽），双窗口同向 PASS 才落 yaml。

## 4 支柱 cross-check

| 支柱 | 是否对齐 | 备注 |
|---|---|---|
| 1 基本面或债性选标的 | ✅（扩展后） | 转股溢价率 + 纯债溢价率 + 剩余规模 + 评级 = 债性选标的核心 |
| 2 趋势择时（豁免） | ✅（扩展后） | CB 双低低波动 + 债底保护，不需要 regime gate |
| 3 实时风控 + 日内 T | ⚠️ 风控复用 schema；T+0 是 CB 优势但本 PR 暂不实现 | M5 阶段做风控 schema 对齐，T+0 推迟 |
| 4 trade retrospective | ✅ | 复用 closed_trades 管道，加 entry/exit features（cb_premium / dual_low_score / 强赎状态） |

## 数据层（probe 已 PASS，详见 [[cb_data_probe_2026-06]]）

| 数据源 | endpoint | 用途 | 历史回溯 |
|---|---|---|---|
| 全市场债券列表（含退市） | `akshare.bond_zh_cov()` | universe 池 | 2007-2026，1022 行（含已退市，无 survivorship bias） |
| 个券日级（价格 + 4 溢价率字段） | `akshare.bond_zh_cov_value_analysis(symbol)` | backtest 主面板 | 2019-2020 起，6 字段：日期/收盘价/纯债价值/转股价值/纯债溢价率/转股溢价率 |
| 强赎事件 | `akshare.bond_cb_redeem_jsl()` | exit + universe filter | 324 只已公告，含触发日/最后交易日/强赎价 |
| 实时 spot（实盘） | `akshare.bond_zh_hs_cov_spot()` | daily 入场 ranking | 332 行实时 |

**全量 backfill 估算**：1022 只 × ~0.5s/call = ~8.5 分钟，日级 cache 后增量 refresh。

**Survivorship bias 验证**：113008（已退市，last=2021-01-18）和 113537（last=2024-12-18）`value_analysis` 仍返回全历史，✅。

## 设计 — 双低策略 v1

### §1 双低评分

```
dual_low_score = close_price + premium_rate_pct
  -- close_price: 当日收盘价（CB 面值 100 基准，典型范围 90-130）
  -- premium_rate_pct: 转股溢价率（百分数，非比例；典型范围 -10% ~ +60%）
```

低分 = 价低 + 溢价率低 = 双低，目标"近债底 + 转股价值高"。

### §2 Universe filter（每日 asof 截面）

- 排除：已公告强赎（`bond_cb_redeem_jsl` 强赎状态='已公告强赎'）
- 排除：剩余年限 < 0.5 年（到期前换仓）
- 排除：剩余规模 < 1 亿
- 排除：债现价 < 80（深度违约风险，含退市债）
- 排除：评级 < AA-（可选，灵敏度测试）

### §3 入场 / 持有 / 出场

| 阶段 | 规则 |
|---|---|
| 入场 | 每日按 dual_low_score 升序取前 N=20，等权配置 |
| 持有 | 每日重新评分；仍在前 N×1.5（=30）名内则保留，否则换仓 |
| 出场 | 强赎公告、剩余年限 < 0.5、双低分 > exit_threshold（默认 150）、个券止损（CB close < 85）|

换手率预期：月级再平衡而非日级（前 N×1.5 buffer 避免边缘股频繁进出）。

### §4 回测窗口（双窗口同向硬卡）

- 4y: 2022-01-01 → 2026-05-25（含 2022 熊市 + 2023-24 反弹 + 2025-26 震荡）
- 8y: 2018-01-01 → 2026-05-25（含 2018 熊市 + 2019-21 牛市 + 2022 熊市 + ...）
- **8y 窗口需谨慎**：bond_zh_cov_value_analysis 早期回溯到 2019-2020，2018 数据可能不全，需 probe 确认。8y 真实可行起点可能是 2020-01-01（6y 窗口）

**落 yaml 准入**：4y/8y 双窗口 Sharpe 同向 PASS（均 > v7 6 资产组合 sleeve 等价 Sharpe ~1.5）+ DD 不恶化超 3pp + 组合层叠加 v7 后 Sharpe 同向提升。

## 子策略包结构

```
src/quant_system/strategies/cb_double_low/
├── __init__.py
├── data/
│   ├── loader.py           # bond_zh_cov / value_analysis / redeem / spot 封装 + DuckDB cache
│   └── cache.py            # 复用 equity_factor cache pattern
├── universe/
│   └── filter.py           # §2 filter 实现
├── engine/
│   ├── strategy.py         # §1 评分 + §3 入场/持有/出场
│   └── backtest.py         # Backtester（复用 BacktestDiagnostics M0 contract）
├── config_schema.py        # yaml 节点 + dataclass
└── reporting/
    └── trade_features.py   # entry/exit features 采集（cb_premium / dual_low_score）

config/cb_double_low.yaml   # 主配置
scripts/daily/daily_cb.py   # daily 入口
tests/cb_double_low/        # 单元测试
```

## PR 拆分（每步独立 PR）

| PR | 范围 | 改动 | 准入 |
|---|---|---|---|
| **PR1（本 spec）** | spec + 扩 4 支柱 memory | `docs/specs/convertible_bond_sleeve.md`, `memory/project_north_star.md`, `memory/cb_data_probe_2026-06.md`, `memory/MEMORY.md` | review only |
| PR2 | DataLoader 红灯测试 + DuckDB cache schema | `src/quant_system/strategies/cb_double_low/data/`, `tests/cb_double_low/test_loader.py` | pytest 红灯 |
| PR3 | DataLoader 实现（PR2 测试 PASS）+ M0 全市场 backfill 脚本 | + `scripts/research/cb_backfill.py` | pytest 绿 + duckdb 1022 行 panel 写入 |
| PR4 | universe/filter + strategy（双低评分 + N=20 入场）+ 单元测试 | `universe/filter.py`, `engine/strategy.py`, `tests/cb_double_low/test_strategy.py` | pytest 绿 |
| PR5 | engine/backtest.py + M0 artifact contract + 4y backtest 一次 | + `data/backtest/cb_double_low_a_share_2022-01-01_2026-05-25/` | M0 audit PASS |
| PR6 | 8y backtest + 双窗口同向决策 + exit_threshold sweep + 组合层叠加 v7 grid | + memory 记录 backtest 结果 | 双窗口 PASS 才进 PR7 |
| PR7 | yaml 落地 + daily 入口 + launchd 调度 | `config/cb_double_low.yaml`, `scripts/daily/daily_cb.py`, `deploy/run_daily.sh` | 实盘 advisory only |

### PR5 设计补丁（2026-06-16 PR4 smoke 实测后追加）

详见 [[cb_data_probe_2026-06]] v1.1。backtester 必须把以下 3 个 nuance 内化：

1. **Panel 覆盖率每日不齐**（实测 asof=2026-06-15 头 200 只仅 59% 有数据）
   - 策略：best-effort（用可得数据继续），不硬卡 skip 当天
   - artifact 要求：M0 输出 `daily_panel_coverage.csv`（date, asked_n, available_n, pct），供事后审计
   - 异常阈值（advisory）：覆盖率 < 30% 时 log warning，不阻塞 backtest

2. **exit_dual_low_threshold=150 已过时**（2024+ 入场 score 多数已 > 150）
   - PR5 默认值改 `exit_dual_low_threshold=180`（实测头 20 只 median 173 + 7 buffer），yaml 留可配
   - PR6 sweep candidate: 150 / 170 / 180 / 190 / 200 / `top_N_median + 30`（相对值）
   - 双窗口（4y/8y）同向 PASS 才能落 yaml

3. **负溢价债污染入场**（127090 兴瑞转债 prem=-11.58% 排第一）
   - PR5 新增 filter 项 `min_conversion_premium`，默认 -5%（负溢价 < -5% 排除）
   - 落到 `UniverseFilterConfig`，配套 stats key `dropped_negative_premium`
   - 灵敏度测试候选：-3% / -5% / -10% / 不过滤

## 不做（Backstop 严守）

- ❌ **不引入 binary 杠杆 / 融资融券** — v1 现金 long-only，杠杆放大留给执行层
- ❌ **不接付费数据** — Wind/iFinD/L2 tick 全部 out-of-scope；akshare 数据已 probe PASS
- ❌ **不做 CB 期权 / 转股套利** — 仅做双低多头，转股套利下游分支
- ❌ **不撬 4 支柱以外的策略** — CB sleeve 独立，不动 equity_factor / options
- ❌ **不假设 8y 全窗口可回测** — 早期数据不全，6y/8y 真实回溯由 probe 确定
- ❌ **不接受单窗口 PASS 落 yaml** — 4y/8y 必须同向

## 已知前置风险

1. **2017-2024 双低 alpha 拥挤** — 集思录/雪球公开策略，历史 Sharpe 2.0 不保证未来。**需要在 2022-2026 窗口（拥挤后）单独 verify**，不能只看 8y 全窗口
2. **2022-2024 强赎规则收紧** — exit 假设需用最新 `bond_cb_redeem_jsl` 而非历史规则推断
3. **退市债数据缺口** — `value_analysis` 对退市债的最后几日 NaN 概率高；需 fail-safe（last valid forward fill or skip）
4. **容量上限** — < 10M 账户无影响，> 100M 撞小盘债流动性。本 PR 5-10% 占比 < 5M，安全

## 时间预算估计

| PR | 工程时间 | backtest 时间 |
|---|---|---|
| PR1（本） | 30 min | - |
| PR2-3 | 2-3 hr | + 8.5 min backfill |
| PR4-5 | 3-4 hr | + 5-10 min 4y backtest |
| PR6 | 1 hr | + 10 min 8y + grid |
| PR7 | 1-2 hr | - |
| **总** | **~10 hr** | ~30 min |

## Cross-check 完成清单

- [x] 4 支柱 cross-check 完成（支柱 1 + 2 需扩，已与用户口头确认 2026-06-15）
- [x] 撞墙检查：与已死 18 条证伪不重叠（CB 是全新资产类别，不撞 equity_factor / zhuang / hsgt 任何路径）
- [x] 数据可得性 probe PASS
- [x] Survivorship bias 验证 PASS
- [x] 容量评估 PASS（< 100M AUM）
- [x] 实盘可执行性（akshare 实时 + A 股账户）PASS

**Why**: A 股 sleeve 在 v7 当前 4 支柱框架下已饱和；CB 双低是唯一通过 4 支柱 cross-check + 数据 probe + survivorship 验证的新 sleeve 方向；与 6 资产 v7 组合相关性接近 0，预期组合 Sharpe 同向提升。
**How to apply**: 按 PR 拆分依次推进；每个 PR 独立 review；双窗口同向硬卡是落 yaml 前提；PR6 后若证伪，写 `memory/cb_double_low_falsified_<date>.md` 归档，CB 路径关闭。
