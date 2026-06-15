# Spec — 持仓中日内做 T 执行层（A 股 advisory v1）

## 背景

`memory/project_north_star.md` 支柱 3 = **持仓中日内做 T+0 + 实时风控**。
- 实时风控告警 ✅ 已落（`src/quant_system/intraday/core.py::evaluate_alerts` 7 阈值 + PR5 Telegram）
- 日内做 T 执行 ❌ **零代码 — 最大缺口**

支柱 2 趋势策略 (HK Sharpe 1.149, A 股 0.844) 是 D+1 open 入场后中线持有 30 天的"底仓 alpha"。
日内做 T 不是新 alpha 信号源，**是已有持仓内的执行层优化**：
- 浮盈高位卖一部分锁利，回落后买回原仓（合规 A 股不增持，当日净持仓量不变）
- 目标：在 30 天底仓持有期内，通过 5-10 次小幅 T 调仓，每次 1-2% 额外 alpha（合 30 天 0.5-1pp）

PR1 范围：**A 股 advisory only**，与 PR5 Telegram alerts 同框架，**人工下单**。

## 改动范围（PR 拆分 — 每步独立 PR）

| PR | 内容 | 改动文件 |
|---|---|---|
| PR1 (本 spec) | spec + 单元测试 (TDD 红灯) | `docs/specs/intraday_t_execution_a_share.md`, `tests/intraday/test_t_signals.py` |
| PR2 | `intraday/core.py` 加 `evaluate_t_signals` 纯函数（让 PR1 测试 PASS） | `src/quant_system/intraday/core.py` |
| PR3 | `config/intraday.yaml` t_signals 段 + 调度脚本 | `config/intraday.yaml`, `scripts/intraday/intraday_t_signals.py` |
| PR4 | alerts_sent 表 alembic 扩 `t_signal_sell` / `t_signal_buy` enum + Telegram 集成 | alembic migration, `intraday/core.py` notify hook |
| PR5 | dashboard 前端 T signals 区段 | `frontend/src/components/TSignalCard.tsx` |

PR2-5 都需要单独 spec 文档，本 spec 只到 PR1 测试 schema 完整契约层级。

## 不做（Backstop 严守）

- ❌ **不 auto-execute** — 不接券商 API；advisory 阶段验证 alpha + 估手动延迟，PR2+ 月再讨论 IBKR/同花顺自动化
- ❌ **不引入新 alpha 信号源** — T 信号是已有持仓的 sub-execution；不改 entry/exit factor weights / RSI / regime gate
- ❌ **不撬五层 efficient set / 不改 yaml strategy 参数** — 与回测层完全解耦
- ❌ **不在盘前/盘后触发** — 仅 A 股交易时段 09:30-11:30 + 13:00-15:00；早间集合竞价不发 T
- ❌ **不对 zhuang 持仓发 T** — zhuang 已弃用（[[zhuang_deprecated_2026-06]]）；strategy_name='zhuang' 直接跳过
- ❌ **不对 break_stop_loss 已触发的持仓发 T** — 接近止损区禁用日内 T，让标准 stop 路径走
- ❌ **不对 A_mr 持仓发 T** — A_mr by design 不自动开仓，也不做 T（PR2+ 再评估）
- ❌ **不动 entry_features / exit_features schema** — T 数据进独立采集表（PR2 后续）
- ❌ **不引入新数据源** — VWAP 通过 spot_em 5min 累计算（[[session_2026_06_09_realtime_data_intraday_5min]] 已接入）

## 设计 — 综合触发 3 sub-signal + 合成

### §3.1 价格网格信号（base layer，必选）

基于持仓票浮盈/亏 vs 入场价的两侧网格：

```
unrealized_pct = (current_price - entry_price) / entry_price

candidate_side =
  SELL if unrealized_pct >= sell_unrealized_pct_min  (default +5%)
  BUY  if buy_unrealized_pct_min <= unrealized_pct < sell_unrealized_pct_min  (default [+2%, +5%))
  None if unrealized_pct <  buy_unrealized_pct_min   (浮亏区不做 T)
  None if unrealized_pct <= no_t_unrealized_pct_max  (default -3%, 接近止损禁用)

base_qty_ratio = 0.5  # 卖 50% 锁利 / 买回 50% 恢复底仓
```

**BUY 触发的物理含义**：当 unrealized 从 5%+ 回落到 [2%, 5%) → 之前应该已经发过 SELL，现在回买恢复底仓。**首次进入 [2%, 5%) 区间不发 BUY**（无前置 SELL）。实现：BUY 必须当日已有 SELL 记录在 `alerts_sent` 表。

### §3.2 VWAP 偏离 override（多选）

```
vwap_today = Σ(price × volume) / Σ(volume) 累计自 09:30 (spot_em 5min K 线)
deviation = (current_price - vwap_today) / vwap_today

if vwap_enabled:
  if deviation >= vwap_sell_premium_pct (default +2%):  qty_ratio_modifier += 0.2
  if deviation <= -vwap_buy_discount_pct (default -1.5%): qty_ratio_modifier += 0.2

modified_qty_ratio = base_qty_ratio + (modifier 仅对当前 side 生效)
```

**含义**：当价格已经偏离 VWAP 显著时，T 信号的 qty 调高（更高位 SELL / 更低位 BUY），最高到 0.7。
若 spot_em VWAP 数据缺失 → fail-soft，不应用 override，base 0.5 直出。

### §3.3 量价 anti-distribution（防误卖派发尾）

```
day_change_pct  = spot_em '涨跌幅' / 100
volume_ratio    = spot_em '量比'

if vol_price_enabled and current_side == SELL:
  if day_change_pct >= sell_suppress_change_pct (default +4%) and
     volume_ratio >= sell_suppress_vol_ratio   (default 2.0):
    qty_ratio_modifier *= 0.7   # 放量上涨 → SELL 抑制（可能是真趋势启动）

if vol_price_enabled and current_side == BUY:
  if day_change_pct <= buy_boost_change_pct (default -2%) and
     volume_ratio <= buy_boost_vol_ratio    (default 0.7):
    qty_ratio_modifier *= 1.3   # 缩量回调 → BUY 加强（弱反向风险低）
```

**含义**：避免与"庄家拉升出货"反向操作（强信号时不 SELL），鼓励"缩量回踩"低位 BUY。
注意 `vol_price` 抑制因子作用于 qty_ratio 而非 *是否触发*，触发仍由 §3.1 价格网格主导。

### §3.4 合成规则（顺序）

1. **支柱合规过滤** — strategy_name ∈ {equity_factor 三市场}；market='a_share'；非 break_stop / 非 zhuang / 非 A_mr
2. **价格网格判定** (§3.1) → candidate_side ∈ {SELL, BUY, None}
3. **当日上限去重** — alerts_sent 当日已有 `t_signal_<side>` 记录该股 → skip
4. **BUY 前置 SELL 检查** — 当日无 SELL 记录 → skip BUY（首次进入 [2%, 5%) 不买）
5. **VWAP 调整** (§3.2)（fail-soft 缺数据跳过）
6. **量价调整** (§3.3)（fail-soft 缺数据跳过）
7. **qty_ratio clamp** — 最终 ∈ [0.2, 0.7]
8. **生成 TSignalEvent** → 写 alerts_sent + Telegram push

## §4 Schema

### `PositionSnapshot` 扩展（intraday/core.py）

```python
@dataclass
class PositionSnapshot:
    # 既有字段 (PR1-5)
    strategy_name: str
    symbol: str
    market: str
    entry_price: float
    current_price: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    ma_long: Optional[float] = None
    volume_ratio: Optional[float] = None
    day_change_pct: Optional[float] = None
    # 新增 — 日内 T 用 (本 spec)
    vwap_today: Optional[float] = None     # spot_em 5min 累计 VWAP
    day_open: Optional[float] = None       # 开盘价 (可选, qty 推算用)
```

### `TSignalEvent` (new)

```python
@dataclass
class TSignalEvent:
    asof: str                # ISO datetime "2026-06-15 10:23"
    strategy_name: str       # "equity_factor"
    symbol: str
    market: str              # "a_share"
    side: str                # "SELL" | "BUY"
    suggested_price: float   # current_price snapshot
    qty_ratio: float         # [0.2, 0.7]
    base_qty_ratio: float    # 0.5 (debug)
    reason: str              # 三段拼接 "grid: unrealized +6.2% | vwap: +2.1% premium | volprice: normal"
    confidence: str          # "high" (3 layer 同向) / "medium" (2 layer) / "low" (1 layer)
```

### alerts_sent 表 enum 扩展

新枚举值：
- `t_signal_sell`
- `t_signal_buy`

dedup key 沿用既有 `(asof_date, strategy_name, symbol, alert_type)` unique index。

## §5 Config (config/intraday.yaml 加段)

```yaml
t_signals:
  enabled: false                       # 默认 OFF (Backstop 零行为差异)
  strategies: ["equity_factor"]        # 不含 zhuang (deprecated) / 不含 A_mr (by design)
  markets: ["a_share"]                 # PR1 only
  trading_hours:                       # A 股交易时段 (Asia/Shanghai)
    morning: ["09:30", "11:30"]
    afternoon: ["13:00", "15:00"]
    skip_first_minutes: 5              # 跳开盘集合竞价 5 分钟噪声

  grid:
    sell_unrealized_pct_min: 0.05      # 浮盈 ≥ 5% 触发 SELL
    buy_unrealized_pct_min: 0.02       # 浮盈 ∈ [+2%, +5%) 触发 BUY (前提当日已发 SELL)
    no_t_unrealized_pct_max: -0.03     # 浮亏 ≤ -3% 全面禁用 T
    qty_ratio_base: 0.5

  vwap:
    enabled: true
    sell_premium_pct: 0.02
    buy_discount_pct: 0.015
    qty_ratio_boost: 0.2

  vol_price:
    enabled: true
    sell_suppress_change_pct: 0.04
    sell_suppress_vol_ratio: 2.0
    sell_suppress_factor: 0.7
    buy_boost_change_pct: -0.02
    buy_boost_vol_ratio: 0.7
    buy_boost_factor: 1.3

  qty_ratio_clamp:
    min: 0.2
    max: 0.7

  frequency:
    max_sells_per_day: 1
    max_buys_per_day: 1
```

## §6 集成 — intraday/core.py 加纯函数

```python
@dataclass
class TSignalConfig:
    enabled: bool
    strategies: list[str]
    markets: list[str]
    # ... 与 yaml 字段镜像

def evaluate_t_signals(
    positions: list[PositionSnapshot],
    cfg: TSignalConfig,
    asof: datetime,
    sent_today: dict[tuple[str, str], list[str]],  # (symbol, market) -> ["t_signal_sell", "break_stop_loss", ...]
) -> list[TSignalEvent]:
    """纯函数 — 无 IO; 输入快照, 输出事件 list. 与 evaluate_alerts 平行.

    sent_today: 当日已发 alert 类型映射, 用于:
      - dedup max_sells/buys_per_day
      - BUY 前置 SELL 检查
      - break_stop_loss 触发后禁用 T
    """
    ...
```

调用方 `scripts/intraday/intraday_t_signals.py`（PR3）：
1. `journal.list_open()` → 持仓
2. `fetch_realtime_prices()` + `fetch_vwap_today()` + spot_em → PositionSnapshot
3. 查 alerts_sent 当日记录 → sent_today
4. `evaluate_t_signals(...)` → TSignalEvent list
5. 写 alerts_sent + Telegram send

## §7 单元测试契约 (tests/intraday/test_t_signals.py — PR1 红灯)

| 测试名 | 输入 | 期望输出 |
|---|---|---|
| `test_t_signal_grid_sell_basic` | 浮盈 +6.2%（无 VWAP / 无量价数据）| 1 SELL event, qty=0.5, reason 含 "grid: unrealized +6.2%" |
| `test_t_signal_grid_no_sell_below_threshold` | 浮盈 +4.9%（< 5% 阈值） | 0 event |
| `test_t_signal_grid_buy_requires_prior_sell` | 浮盈 +3.5% **当日无 SELL 记录** | 0 event |
| `test_t_signal_grid_buy_after_sell` | 浮盈 +3.5% **sent_today 含 t_signal_sell** | 1 BUY event, qty=0.5 |
| `test_t_signal_no_t_in_loss_zone` | 浮亏 -3.5%（≤ -3%）| 0 event |
| `test_t_signal_break_stop_disables` | 浮盈 +6% **sent_today 含 break_stop_loss** | 0 event |
| `test_t_signal_zhuang_strategy_skipped` | strategy_name='zhuang' | 0 event |
| `test_t_signal_a_mr_strategy_skipped` | strategy_name='mean_reversion' | 0 event |
| `test_t_signal_non_a_share_skipped` | market='hk_share' | 0 event (PR1 only A 股) |
| `test_t_signal_outside_trading_hours_skipped` | asof 12:00 (午休) | 0 event |
| `test_t_signal_first_5_min_skipped` | asof 09:32 (开盘前 5 分钟内) | 0 event |
| `test_t_signal_vwap_premium_boost_sell` | SELL + 价 > VWAP×1.02 | qty=0.7（base 0.5 + boost 0.2） |
| `test_t_signal_vwap_discount_boost_buy` | BUY + 价 < VWAP×0.985 | qty=0.7 |
| `test_t_signal_vwap_missing_data_fail_soft` | SELL + vwap_today=None | qty=0.5（不 boost 不报错） |
| `test_t_signal_vol_price_suppress_sell` | SELL + day_change +5% + vol_ratio 2.5 | qty=0.35（0.5 × 0.7） |
| `test_t_signal_vol_price_boost_buy` | BUY (有前置 SELL) + day_change -3% + vol_ratio 0.5 | qty=0.65（0.5 × 1.3） |
| `test_t_signal_vol_price_missing_data_fail_soft` | day_change=None vol_ratio=None | qty=0.5（不调整） |
| `test_t_signal_qty_clamp_min` | 极端组合 qty 计算 0.15 | qty=0.2（clamp min） |
| `test_t_signal_qty_clamp_max` | 极端组合 qty 计算 0.85 | qty=0.7（clamp max） |
| `test_t_signal_dedup_max_1_sell_per_day` | sent_today 含 t_signal_sell + 浮盈 +7% | 0 event |
| `test_t_signal_dedup_max_1_buy_per_day` | sent_today 含 t_signal_buy + 浮盈 +3% | 0 event |
| `test_t_signal_confidence_high_all_three_align` | 3 层同向 boost | confidence='high' |
| `test_t_signal_confidence_medium_two_align` | 2 层同向 | confidence='medium' |
| `test_t_signal_confidence_low_one_align` | 仅 base | confidence='low' |
| `test_t_signal_disabled_yaml_noop` | cfg.enabled=False | 0 event 不报错 |

合计 **24 case**，PR1 全部红灯（function not implemented），PR2 实现后转绿。

## §8 验收 step (PR2 实现完成后)

1. `pytest tests/intraday/test_t_signals.py -v` → 24/24 PASS
2. `pytest tests/intraday/` 全跑 → 现有 27 case 不回归
3. `pytest tests/` 全跑 → 不回归
4. `scripts/intraday/intraday_t_signals.py --dry-run --asof "2026-06-16 10:30"` 输出预览（仅打印不写 DB / 不发 Telegram）
5. Telegram send 测试（用 `--asof-now --test` mock 一条事件）
6. PR header 重申 5 条 Backstop check（见 §10）

## §9 数据源依赖

| 字段 | 来源 | 状态 |
|---|---|---|
| 实时报价 `current_price` | akshare spot_em / fetch_realtime_prices | ✅ 已用（intraday_risk_check） |
| 量比 `volume_ratio` | akshare spot_em '量比' | ✅ 已用（PR3 zhuang_distribution） |
| 涨跌幅 `day_change_pct` | akshare spot_em '涨跌幅' | ✅ 已用（PR3） |
| 5min K 线 | akshare stock_zh_a_minute / spot_em historical | ✅ 已接入（[[session_2026_06_09_realtime_data_intraday_5min]]） |
| **VWAP 累计** | 自算：Σ(price×volume)/Σ(volume) 自 09:30 起 5min 累计 | ❌ 新写：`intraday/vwap.py::compute_vwap_today` 纯函数 + cache（PR2 同步） |

## §10 5 条 Backstop check

- **#1 18 条证伪墙**：T 信号是已有持仓的执行层，不改 entry/exit alpha；不撞 [[tp_runner_sweep_falsified_2026-06]] (出场层) 也不撞 momentum/value/regime 类证伪 ✓
- **#2 双窗口 4y/8y 同向 PASS**：advisory 阶段**不撬 yaml 也不改回测**；如未来落 auto-execute 前需要 90+ 天实盘验证 T 信号 alpha；PR1-5 不动 yaml ✓
- **#3 实盘 < 30 笔不撬 frontier**：本 spec 是 advisory + 持仓内调仓，**不改实盘策略 alpha / 不改组合权重 / 不改 5 腿配比**；只是在 A_mom 现有持仓上加一层执行优化建议 ✓
- **#4 PM 决策权**：advisory only，PM 手动下单；T 信号事件入 alerts_sent 表 + Telegram，**程序不替代决策** ✓
- **#5 采集 vs alpha 分离**：T 信号事件写独立 alerts_sent 表 alert_type，**不污染 entry_features / exit_features**；T 触发后续若有 retrospective 学习走独立 t_signals_retrospective 表（PR6+） ✓

## §11 反对的设计选择（明文）

- **不引入 mean-reversion alpha 信号源到选股层** — T 是 sub-execution 不是 alpha 通道
- **不在 entry_features 加 t_signal_count** — pollute 因子层学习；T 数据独立表
- **不扩到 HK / US** — HK 实盘账户未开通；US baseline 负 Sharpe 不上实盘
- **不在盘前/盘后触发** — 仅 09:30+5min 至 15:00 时段；早盘集合竞价 + 尾盘 14:57-15:00 集合也跳过
- **不持仓 T 卖光所有底仓** — qty_ratio 最大 0.7，永远保留 ≥ 30% 底仓
- **不触发 buy 加大底仓** — qty_ratio 最大 0.7 BUY 也只是补回之前的 SELL 部分，不超过原仓位

## §12 后续 PR 路线图（不在 PR1）

- **PR2** (next): `intraday/core.py` 实现 `evaluate_t_signals` 让 PR1 24 case 全绿 + `intraday/vwap.py` 新增 VWAP 累计纯函数
- **PR3**: `config/intraday.yaml` t_signals 段 + `scripts/intraday/intraday_t_signals.py` 调度（5min loop）
- **PR4**: alerts_sent alembic enum 扩展 + Telegram message template
- **PR5**: dashboard 前端 T signals 区段（建议卖 / 建议买 / 当日已发 T 计数）
- **PR6** (实盘≥30 笔 closed 后): T 信号 retrospective 报表（L5 self-learning 同模式）
- **PR7+** (实盘验证 6+ 个月 + alpha 显著后): IBKR HK / 同花顺 A 股 auto-execute 接口

## §13 关联

- [[project_north_star]] 支柱 3 后半段 — 本 spec 落实
- [[session_2026_06_07_pr5_intraday_telegram]] — Telegram + alerts_sent 复用框架
- [[session_2026_06_06_zhuang_risk_parity]] — PositionSnapshot 扩展模板
- [[session_2026_06_09_realtime_data_intraday_5min]] — 5min K 线数据源
- [[session_2026_06_09_pr3_zhuang_distribution_dashboard_poll]] — 量价信号字段（volume_ratio / day_change_pct）现成
- [[tp_runner_sweep_falsified_2026-06]] — 出场层 alpha 饱和，未来增量在 T 执行层（本 spec）
- [[zhuang_deprecated_2026-06]] — strategy_name='zhuang' skip 来源
- [[feedback_harness_first_pr_split]] — spec-first 5 PR 拆分纪律
- [[session_2026_06_08_self_learning_pipeline]] — 5 条 Backstop 来源

## §14 不变量（即使 PR2-5 实现也不能违反）

1. **当日净持仓量永不变** — A 股合规硬约束；BUY qty 永不 > 同日已发 SELL qty 之和
2. **qty_ratio ∈ [0.2, 0.7]** — 永不卖光底仓也永不超过 70% 调仓
3. **T 信号不改 stop_loss / take_profit** — 这两个由支柱 2 趋势出场决定，T 信号读不写
4. **break_stop 后 T 全面禁用** — 止损路径优先
5. **advisory only** — PR1-5 永远不下单
6. **strategy_name 白名单** — 只有 equity_factor 三市场 + market=a_share 过滤；任何新策略入实盘前需明文加入 t_signals.strategies 白名单
