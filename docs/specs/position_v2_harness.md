# 持仓 v2 Harness — 4 项改动的验收契约

**作者**: Claude Code（与用户 2026-06-07 对齐）
**状态**: DRAFT — 待用户 review 后冻结，后续所有 PR 比对本文件
**前置**: [[session_2026_06_06_zhuang_risk_parity]]（v1 截止快照）
**方法论**: [[feedback_harness_first_pr_split]]（harness-first + PR 拆分）

---

## 0. 范围 & 不动项

### 0.1 本次 4 项改动

| 项 | 简称 | M-节点 | 子策略 | PR |
|---|---|---|---|---|
| (a) | **max_drawdown peak**（真历史 peak DD） | M5（RiskMonitor） | equity_factor + zhuang | PR1 + PR2 |
| (b) | **Step 3 盘中实时监控** | 新增 layer（盘中 cron） | 全策略 | PR5（待授权） |
| (c) | **options BCS 持仓 schema** | M5 / 新数据通道 | options | PR3 |
| (d) | **HK_mom / A_mr 持仓回归** | M5（regression） | equity_factor 副腿 | PR4 |

### 0.2 不动项（明令）

- 策略 entry/exit 逻辑（`signals.py`, `exit_taxonomy.py`）—— 本次纯 observability + 风控阈值
- M0/M1/M2/M3/M4 任何节点
- yaml 现有权重（季度再平衡 v5 efficient frontier）
- daily 调度方式（手动跑 `./deploy/run_daily.sh`，launchd TCC 阻塞决策不动）

### 0.3 PR 全局门控（每个 PR 必须全绿才合并）

1. `pytest tests/` 全绿（**不允许新增 skip**）
2. 短回测 `scripts/backtest/backtest.py --start 2026-01-01 --end 2026-02-28 --refresh-days 999` PASS（仅 PR 触及 strategy 层时需要；PR1/PR3/PR4/PR5 无需）
3. `scripts/backtest/audit_m0_outputs.py` PASS（仅 strategy 层；其余 PR skip）
4. `verify_dualwrite.py` 一致（每个 PR 必须；新加 derived 字段要同步 pop list，避免 06-05 假阳回归）
5. 默认 OFF 时 daily 输出与 baseline 字节级一致（除 schema/字段增量；alert 阈值 yaml `enabled: false`）

---

## 1. 现状基线（不要再 audit 一次）

### 1.1 PositionRisk 当前形态 (`src/quant_system/strategies/equity_factor/risk/monitor.py`)

```python
@dataclass
class PositionRisk:
    trade_id, symbol, market, entry_date, entry_price, entry_size: ...
    current_date, current_price, pnl_pct, pnl_amount, hold_days: ...
    prev_stop, new_stop, action, reason, exit_layer: ...
    # safety margin v1（06-04 / 06-05 落地）
    ma_long, dist_to_stop_pct, dist_to_ma_long_pct: Optional[float]
    take_profit, dist_to_target_pct: Optional[float]
```

### 1.2 PortfolioRisk 当前形态

```python
@dataclass
class PortfolioRisk:
    n_positions, cost_basis, market_value: ...
    unrealized_pnl, unrealized_pnl_pct: ...
    max_single_weight, n_at_risk, worst_drawdown_pct: ...
    alerts: list[str] = []           # 06-04 落地，PortfolioRiskConfig 触发
    # ⚠ worst_drawdown_pct 当前是「单只最差浮亏」，不是组合层 peak DD
```

### 1.3 PortfolioRiskConfig 当前阈值

```python
@dataclass
class PortfolioRiskConfig:
    enabled: bool = False
    max_single_weight_pct: Optional[float] = None      # 0.30
    unrealized_pnl_floor_pct: Optional[float] = None   # -0.05 (equity) / -0.07 (zhuang)
    exit_signal_ratio_max: Optional[float] = None      # 0.50
    # ⚠ portfolio_drawdown_pct 字段不存在（本次 PR2 新增）
```

### 1.4 DB schema 现状（alembic）

- `journal_trades` / `journal_snapshots` — 个股层
- `strategy_runs` / `positions` / `signals` — daily run 快照
- `zhuang_trades` / `zhuang_snapshots` — zhuang 独立 ledger
- **缺 `portfolio_history`**（PR1 新增）
- **缺 `options_positions`**（PR3 新增）

### 1.5 verify_dualwrite 当前 pop list (`scripts/daily/verify_dualwrite.py:109-116`)

```python
# quant kind:
payload.pop("portfolio_alerts", None)
# zhuang kind:
payload.pop("portfolio_alerts", None)
```

每个 PR 加 derived 字段都必须更新本 list（教训：06-05 漏 pop 真写第一次才暴露）。

### 1.6 前端 columns 当前形态 (`frontend/src/components/tableColumns.tsx`)

- `positionColumns` (`QuantPosition`): symbol / name / 距止损 / 距止盈 / pnl_pct
- `zhuangPositionColumns` (`ZhuangPosition`): code / name / 距止损 / 距止盈 / pnl

---

## 2. PR1 — portfolio_history 表 schema + 写入路径

### 2.1 范围

仅 **基建**：建表 + 收尾写入。不暴露字段、不前端、不计算 peak DD（PR2 做）。

### 2.2 DB schema diff

新增 alembic migration `c1d2e3f4a5b6_add_portfolio_history.py`:

```sql
CREATE TABLE portfolio_history (
    id              SERIAL PRIMARY KEY,
    asof            DATE        NOT NULL,
    strategy_name   VARCHAR(64) NOT NULL,
    market          VARCHAR(32) NOT NULL,
    n_positions     INTEGER     NOT NULL,
    cost_basis      FLOAT       NOT NULL,
    market_value    FLOAT       NOT NULL,
    unrealized_pnl  FLOAT       NOT NULL,
    unrealized_pnl_pct FLOAT    NOT NULL,
    created_at      TIMESTAMP   NOT NULL DEFAULT now(),
    UNIQUE (asof, strategy_name, market)
);
CREATE INDEX ix_portfolio_history_asof ON portfolio_history (asof);
CREATE INDEX ix_portfolio_history_strategy ON portfolio_history (strategy_name, market);
```

**UPSERT** 语义（同 asof+strategy+market 重跑覆盖，不重复堆历史）。

### 2.3 写入路径

- `daily_equity.py` 收尾段：`port` 算完后 `portfolio_history_repo.upsert(...)`
- `daily_zhuang.py` 同款
- `daily_options.py` 暂不接（PR3 处理 options_positions 表，与 portfolio_history 解耦）

### 2.4 JSON schema diff

**无**（PR1 不暴露给报表/前端，PR2 时一并加）。

### 2.5 verify_dualwrite

- `portfolio_history` 表不是 JSON 镜像，verify_dualwrite **不读** 该表
- 但要确保 PR1 没在 JSON 里加字段（否则 verify 会 MISMATCH）
- 测试：PR1 跑完，`verify_dualwrite.py --asof <today>` PASS（与 PR1 前一致）

### 2.6 pytest 用例（新增 `tests/equity_factor/test_portfolio_history.py`）

| 用例名 | 验证 |
|---|---|
| `test_upsert_inserts_new_row` | 空表写入，1 行存在 |
| `test_upsert_idempotent_same_asof` | 同 asof+strategy+market 第二次写入覆盖不堆 |
| `test_upsert_different_strategies_coexist` | equity_factor + zhuang 同日双写互不覆盖 |
| `test_upsert_different_dates_accumulate` | 60 天序列 60 行 |

### 2.7 M0 audit 影响

**无**（portfolio_history 不是 M0 产物，audit script 不变）。

### 2.8 手测 step

```bash
# 1. 跑 migration
alembic upgrade head
# 2. 跑 daily（dry-run 不写）
python scripts/daily/daily_equity.py --asof 2026-06-07 --no-write
# 3. 跑真写
./deploy/run_daily.sh --no-options
# 4. 验证表
psql -c "SELECT * FROM portfolio_history WHERE asof = '2026-06-07';"
# 5. 同日再跑一次（验证 UPSERT 不堆）
./deploy/run_daily.sh --no-options
psql -c "SELECT COUNT(*) FROM portfolio_history WHERE asof = '2026-06-07';"  # 应该 = 2（equity + zhuang）
```

### 2.9 失败模式 / 已知 unknown

- 历史 backfill：本表只从今日起累积，前 0 天历史不回填（不影响 60d KPI，60d 后才有数据）
- A_mr / HK_mom 也走 daily_equity.py 同 code path，自动接入；options 不接（schema 不同）

---

## 3. PR2 — max_drawdown_pct 计算 + 接入 PortfolioRisk + 前端

### 3.1 范围

读 PR1 表算真 peak DD → 接 PortfolioRisk → yaml 阈值 → 前端 banner。

### 3.2 PortfolioRisk diff

```python
@dataclass
class PortfolioRisk:
    # ... (existing) ...
    peak_market_value: Optional[float] = None        # 历史窗口内峰值 market_value（持仓 equity proxy）
    drawdown_from_peak_pct: Optional[float] = None   # (current_mv - peak_mv) / peak_mv ≤ 0
```

注：保留 `worst_drawdown_pct`（单只最差），不改语义；新字段独立。

### 3.3 PortfolioRiskConfig diff

```python
@dataclass
class PortfolioRiskConfig:
    # ... (existing) ...
    portfolio_drawdown_pct: Optional[float] = None   # |drawdown_from_peak_pct| > X 触发 alert
    drawdown_lookback_days: int = 60                 # peak 计算窗口（默认 60 个交易日）
```

### 3.4 计算逻辑（new 函数 `compute_drawdown_from_history`）

**Equity proxy**: 本系统 journal 不跟踪 cash 余额（manual execution），所以 peak DD 只能用 **`market_value` 作为持仓 equity proxy**。
- 含义：监控的是「持仓市值」的 peak/trough，**不是**账户净值
- 已知失真：开新仓 → market_value 阶跃上升（被当成"赚钱"），平仓 → 阶跃下降（被当成"亏钱"）；纯价格波动的窗口数学正确
- 兜底：`unrealized_pnl_floor_pct`（已有阈值）从 pnl 维度独立判定，不依赖 history → 即使 dd proxy 被"开仓阶跃"污染，账户层 stop 仍生效

```python
def compute_drawdown_from_history(
    history_repo, strategy: str, market: str, asof: str,
    current_market_value: float, lookback_days: int = 60,
) -> tuple[float | None, float | None]:
    """返回 (peak_mv, drawdown_from_peak_pct)；空 history 返 (None, None)。"""
    rows = history_repo.list_recent(strategy, market, asof, lookback_days)
    if not rows:
        return None, None
    peak = max(r.market_value for r in rows)
    peak = max(peak, current_market_value)
    if peak <= 0:
        return None, None
    dd = (current_market_value - peak) / peak     # ≤ 0
    return peak, dd
```

### 3.5 yaml diff

`config/equity_factor.yaml`:
```yaml
portfolio_risk:
  enabled: false           # 实盘上线时改 true
  portfolio_drawdown_pct: -0.08   # v5 历史 -7.94% 留 headroom
  drawdown_lookback_days: 60
```

`config/zhuang.yaml`:
```yaml
portfolio_risk:
  enabled: true            # 已上线
  portfolio_drawdown_pct: -0.10   # zhuang sleeve 历史 -7%（[[zhuang_overlay_combo4_2026-05]]）
  drawdown_lookback_days: 60
```

### 3.6 JSON schema diff（`report/data/quant.json` / `zhuang.json`）

```jsonc
{
  "portfolio_summary": {
    "n_positions": ...,
    "cost_basis": ...,
    "market_value": ...,
    "unrealized_pnl_pct": ...,
    "peak_market_value": 812340.5,                  // NEW
    "drawdown_from_peak_pct": -0.0245         // NEW
  },
  "portfolio_alerts": [...]                    // 已存在；本 PR 可能新增一条 "组合层回撤 -8.2%（阈值 -8%）"
}
```

### 3.7 verify_dualwrite

- `peak_market_value` / `drawdown_from_peak_pct` 是 derived，不入 `strategy_runs` 表
- `verify_dualwrite.py` 加 pop：
  ```python
  payload.pop("peak_market_value", None)
  payload.pop("drawdown_from_peak_pct", None)
  ```

### 3.8 前端 diff

- `QuantPortfolioSummary` type 加 `peak_market_value?: number | null` + `drawdown_from_peak_pct?: number | null`
- `StrategyCard` 摘要段加 `组合层回撤 -X.X% (peak ¥Y)`
- `portfolio_alerts` banner 已有，新阈值触发会自动并入

### 3.9 pytest 用例（扩 `tests/equity_factor/test_portfolio_risk.py`）

| 用例名 | 验证 |
|---|---|
| `test_compute_drawdown_empty_history_returns_none` | 空 history 返回 (None, None) |
| `test_compute_drawdown_60_day_series` | 模拟 equity 100→120→90 序列，peak=120, dd=-0.25 |
| `test_compute_drawdown_current_above_peak` | 当前 = 新峰，dd=0 |
| `test_portfolio_drawdown_alert_below_threshold` | dd=-0.09, 阈值-0.08 → alerts 增加 1 条 |
| `test_portfolio_drawdown_alert_disabled_when_none` | 阈值 None → 无 alert |
| `test_portfolio_drawdown_disabled_when_enabled_false` | enabled=false → 不算 peak（早返） |

### 3.10 M0 audit 影响

**无**（PortfolioRisk 不在 M0 产物里）。

### 3.11 手测 step

```bash
# 1. PR1 已合，portfolio_history 表有 ≥1 行
# 2. 临时插入造假 peak：
psql -c "INSERT INTO portfolio_history (asof, strategy_name, market, n_positions, cost_basis, market_value, unrealized_pnl, unrealized_pnl_pct) VALUES ('2026-06-01', 'equity_factor', 'a_share', 4, 800000, 870000, 70000, 0.0875);"
# 3. 跑 daily
./deploy/run_daily.sh --no-options
# 4. 检查 JSON
cat report/data/quant.json | jq '.portfolio_summary.peak_market_value, .portfolio_summary.drawdown_from_peak_pct'
# 5. 前端 dashboard 应显示 "组合层回撤 -X.X%"
# 6. 临时把 yaml 阈值改 -0.01，再跑 → alerts banner 应红显
```

### 3.12 失败模式 / 已知 unknown

- 首日（无历史）peak_market_value = current_equity，dd=0，alert 永不触发（by design）
- 60d 累积期间 alert 偏保守
- `worst_drawdown_pct`（旧字段）继续保留，前端两个字段并显（操盘人看「单只」+「组合」两层）

---

## 4. PR3 — options BCS 持仓 schema + 字段对齐

### 4.1 范围

options BCS spread 字段独立，与 stock 持仓表完全不同 schema。新增独立表 + 独立前端组件。

### 4.2 现状

`src/quant_system/strategies/options/engine/monitor.py:22` `PositionAlert` 只对单个 leg 触发预警，**无 spread 级聚合**。

### 4.3 DB schema diff

新增 alembic migration `d2e3f4a5b6c7_add_options_positions.py`:

```sql
CREATE TABLE options_positions (
    id              SERIAL PRIMARY KEY,
    asof            DATE        NOT NULL,
    underlying      VARCHAR(16) NOT NULL,   -- QQQ / SPY / HSI
    spread_type     VARCHAR(16) NOT NULL,   -- "BCS" (Bull Call Spread)
    long_strike     FLOAT       NOT NULL,
    short_strike    FLOAT       NOT NULL,
    expiry          DATE        NOT NULL,
    contracts       INTEGER     NOT NULL,
    debit_paid      FLOAT       NOT NULL,   -- per contract
    max_profit      FLOAT       NOT NULL,   -- (short_strike - long_strike - debit_paid) × 100
    max_loss        FLOAT       NOT NULL,   -- debit_paid × 100
    current_value   FLOAT,                  -- IBKR 拉的 spread mid price
    days_to_exp     INTEGER     NOT NULL,
    pnl_pct         FLOAT,                  -- (current_value - debit_paid) / debit_paid
    breach_alerts   JSONB,                  -- ["DTE<7", "loss>50%", ...]
    created_at      TIMESTAMP   NOT NULL DEFAULT now(),
    UNIQUE (asof, underlying, long_strike, short_strike, expiry)
);
CREATE INDEX ix_options_positions_asof ON options_positions (asof);
```

### 4.4 JSON schema diff（`report/data/options.json`）

新增段：
```jsonc
{
  "underlying": "QQQ",
  // ... existing ...
  "spreads": [                              // NEW
    {
      "long_strike": 480,
      "short_strike": 490,
      "expiry": "2026-09-19",
      "contracts": 2,
      "debit_paid": 4.50,
      "max_profit": 1100,
      "max_loss": 900,
      "current_value": 5.20,
      "days_to_exp": 104,
      "pnl_pct": 0.1556,
      "breach_alerts": []
    }
  ]
}
```

### 4.5 verify_dualwrite

- `spreads` 直接对应 DB 表，**入** verify
- options kind 已支持 schema 校验路径，加 `payload.get("spreads")` 与 DB 比对
- 字段允许 null（current_value/pnl_pct 拉不到时）

### 4.6 前端 diff

- 新组件 `OptionsPositionTable.tsx`（列：underlying / strikes / DTE / debit / current / pnl% / alerts）
- `StrategyCard` options 块替换原 PositionAlert 列表
- `OptionsSpread` TS type 与 JSON schema 对齐

### 4.7 pytest 用例（新增 `tests/options/test_options_positions.py`）

| 用例名 | 验证 |
|---|---|
| `test_upsert_new_spread` | 写入新 spread |
| `test_upsert_idempotent_same_strikes` | 同 5-tuple 第二次覆盖 |
| `test_breach_alerts_dte_under_7` | DTE=5 → breach_alerts 含 `"DTE<7"` |
| `test_breach_alerts_loss_50pct` | pnl=-0.55 → breach_alerts 含 `"loss>50%"` |
| `test_pnl_pct_formula` | debit 4.5 / current 5.2 / pnl_pct = 0.1556 ± 1e-4 |
| `test_max_profit_max_loss_math` | strikes 480/490 / debit 4.5 / contracts 2 → max_profit=1100, max_loss=900 |
| `test_spreads_empty_when_no_positions` | 无 IBKR position 时 spreads=[] |

### 4.8 M0 audit 影响

**无**（options 不走 equity_factor M0 流程，options 有自己的回测路径不在本次范围）。

### 4.9 手测 step

```bash
# 1. 跑 migration
alembic upgrade head
# 2. 跑 daily 带 options（需 IBKR 已连）
./deploy/run_daily.sh
# 3. 检查 JSON
cat report/data/options.json | jq '.spreads'
# 4. 检查 DB
psql -c "SELECT * FROM options_positions WHERE asof = CURRENT_DATE;"
# 5. dashboard options 卡片应有 spread 表（不是单 leg alert）
```

### 4.10 失败模式 / 已知 unknown

- IBKR 不可达时 `spreads=[]`（不抛错，与现状 PositionAlert 一致）
- HK 期权 spread_type=BCS 占位（实际是 HSI options），先做 QQQ；HK 推迟
- 不动 daily_options 决策逻辑（仍是 monitor 风格 alert，不自动平 spread）

---

## 5. PR4 — HK_mom / A_mr 持仓回归测试 + e2e 验证

### 5.1 范围

验证 06-04/06-05/06-06 的 safety margin + portfolio_alerts + take_profit 全部三条腿（HK_mom / A_mr）实际生效。**只写测试，不改 prod 代码**；如发现漏继承，在同 PR 内补丁。

### 5.2 现状

- `equity_factor` 主腿（A_mom）已端到端验过
- `HK_mom`：理论上同 code path，但 `RiskMonitor(market="hk")` 实战未走 e2e
- `A_mr`：[[a_mr_v2_falsified_2026-05]] 后保留 hedge 价值，仍在 deployment_plan 配比；持仓回归未跑

### 5.3 DB schema diff

**无**（仅测试 PR）。

### 5.4 JSON schema diff

**无**（仅测试 PR；如发现 hk/a_mr 输出字段与 a_mom 不一致，本 PR 内补到一致）。

### 5.5 verify_dualwrite

- 测试中模拟 HK_mom + A_mr 各 1 仓 → 跑 daily → `verify_dualwrite.py` PASS（应已对齐）

### 5.6 pytest 用例（新增 `tests/equity_factor/test_position_v1_regression_secondary_legs.py`）

| 用例名 | 验证 |
|---|---|
| `test_hk_mom_position_has_dist_to_stop` | HK_mom 1 仓 → daily_check 输出含 `dist_to_stop_pct` |
| `test_hk_mom_position_has_take_profit` | HK_mom 1 仓 → 含 `take_profit` + `dist_to_target_pct` |
| `test_hk_mom_portfolio_alerts_when_enabled` | HK_mom yaml `portfolio_risk.enabled: true` + 浮亏-6% → alerts 含触发文案 |
| `test_a_mr_position_has_dist_to_stop` | A_mr 1 仓 → 同上字段齐全 |
| `test_a_mr_position_has_take_profit` | A_mr → take_profit 字段 |
| `test_a_mr_portfolio_alerts_when_enabled` | A_mr alerts 触发 |
| `test_a_mr_uses_hedge_yaml_thresholds` | A_mr 默认 alert 阈值与 A_mom 不同（hedge 性质允许更宽 floor） |
| `test_json_schema_uniform_across_three_legs` | a_mom / hk_mom / a_mr 三策略 JSON shape 完全一致（dict key set 相等） |

### 5.7 M0 audit 影响

**无**（仅测试）。

### 5.8 手测 step

```bash
# 1. fixture 模拟 hk_mom + a_mr 1 仓
pytest tests/equity_factor/test_position_v1_regression_secondary_legs.py -v
# 2. 临时插 hk_mom 真持仓（dev DB）跑一次 daily
PYTHONPATH=src python scripts/daily/daily_equity.py --strategy hk_mom --asof 2026-06-07 --no-write
# 3. 检查 JSON shape
diff <(cat report/data/quant.json | jq '.[] | select(.strategy=="equity_factor_a_mom") | keys') \
     <(cat report/data/quant.json | jq '.[] | select(.strategy=="equity_factor_hk_mom") | keys')
```

### 5.9 失败模式 / 已知 unknown

- HK_mom / A_mr 实盘当前 0 仓，e2e 全靠 fixture
- 如发现 yaml `portfolio_risk` 段在 hk/a_mr 缺失，本 PR 一并补（仍默认 `enabled: false`）
- 这是回归 PR，期望 **测试基本一开始就绿**；如不绿，PR 内含修复，commit message 写清楚补丁项

---

## 6. PR5 — Step 3 盘中实时 cron + 推送（**待用户授权**）

### 6.1 范围

N 分钟 cron 拉最新价 → 比对 portfolio_history 当日 stop_loss → 触发 push（email / Slack / 桌面）。

### 6.2 用户授权要求

[[session_2026_06_04_realtime_risk_v1]] 明确："要等 Step 1/2 跑一段实盘体验后再决定要不要做。**未授权前不要自启动。**"

PR5 开工前**必须** AskUserQuestion 确认：
- 推送通道选哪种（email / Slack / 桌面通知）
- 频率（5min / 15min / 30min）
- 触发阈值（仅止损临界 / 含止盈临界 / 含组合层 alert）

### 6.3 DB schema diff

```sql
CREATE TABLE alerts_sent (
    id              SERIAL PRIMARY KEY,
    asof_ts         TIMESTAMP   NOT NULL,
    strategy_name   VARCHAR(64) NOT NULL,
    symbol          VARCHAR(32),
    alert_type      VARCHAR(32) NOT NULL,    -- "stop_loss_breach" / "take_profit_hit" / "portfolio_dd"
    payload         JSONB       NOT NULL,
    channel         VARCHAR(16) NOT NULL,    -- "email" / "slack" / "macos"
    delivered       BOOLEAN     NOT NULL DEFAULT FALSE,
    error           TEXT,
    created_at      TIMESTAMP   NOT NULL DEFAULT now()
);
CREATE INDEX ix_alerts_sent_asof_ts ON alerts_sent (asof_ts);
-- 防重发：同 strategy+symbol+alert_type 当日只发一次
CREATE UNIQUE INDEX uq_alerts_dedup ON alerts_sent (DATE(asof_ts), strategy_name, symbol, alert_type);
```

### 6.4 新脚本 `scripts/intraday/intraday_risk_check.py`

- launchd / cron 每 N 分钟跑 1 次
- 拉所有 open trade → 用 akshare 实时价 → 比对 `journal_trades.stop_loss_price`
- 触发 → 写 `alerts_sent` + 推送
- 防重：dedup index 保证当日同事件只推 1 次

### 6.5 yaml diff

```yaml
# config/intraday.yaml (新文件)
intraday_alerts:
  enabled: false                  # 用户授权后改 true
  channels:
    email: { enabled: false, to: "..." }
    slack: { enabled: false, webhook: "..." }
    macos: { enabled: true }
  triggers:
    stop_loss_proximity_pct: 0.005   # 距止损 < 0.5%
    portfolio_dd_threshold: -0.05
```

### 6.6 pytest 用例（新增 `tests/intraday/test_intraday_risk_check.py`）

| 用例名 | 验证 |
|---|---|
| `test_no_alert_when_safe` | 距止损 +5% → 0 alerts_sent |
| `test_alert_when_within_proximity` | 距止损 +0.3% → 1 alerts_sent |
| `test_dedup_within_same_day` | 同 trigger 第二次 cron → 不重发 |
| `test_dedup_resets_next_day` | 跨日 → 重发 |
| `test_channel_macos_dry_run` | macos 通道 dry-run 不抛错 |
| `test_disabled_when_enabled_false` | yaml enabled=false → 跳过所有 |

### 6.7 M0 audit 影响

**无**（intraday 不走 backtest 流程）。

### 6.8 失败模式 / 已知 unknown

- macOS Full Disk Access TCC 仍 block launchd → 用户决策手动起 cron 或 用 `nohup` 后台守护
- akshare 实时价：A 股有，HK 弱（盘中拉数据可能 stale），US 待评估
- 推送通道凭证管理（Slack webhook、email SMTP）：放 1Password / 环境变量，不进 yaml
- IBKR 期权盘中也要监控？本 PR **不含**，留 PR6 单独处理

---

## 7. PR 依赖图 & 顺序

```
PR0 (本 spec) ──┬─► PR1 (portfolio_history 表) ──┬─► PR2 (max_dd 计算)
                │                                │
                ├─► PR3 (options 表 + 字段)      └─► PR5 (intraday) [待授权]
                │
                └─► PR4 (hk/a_mr 回归) — 可独立并行
```

**推荐顺序**：PR0 → PR1 → (PR2 // PR3 // PR4 并行) → PR5（最后，需用户授权）

**串行约束**：PR2 必须在 PR1 后；PR5 必须在 PR1/PR3 后。

**估时**（按 commit / pytest / verify / memory 全套门控）：
- PR0：60 min（已 in flight）
- PR1：90 min
- PR2：120 min
- PR3：180 min（IBKR mock fixture 较重）
- PR4：60 min
- PR5：240 min（推送通道接入 + 用户决策环）

---

## 8. 验收门控总表（每个 PR 复检）

| 项 | PR1 | PR2 | PR3 | PR4 | PR5 |
|---|---|---|---|---|---|
| pytest 全绿 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 短回测 PASS | — | — | — | — | — |
| M0 audit PASS | — | — | — | — | — |
| verify_dualwrite 一致 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 默认 OFF 字节级一致 | ✓ | ✓ | ✓ | ✓ | ✓ |
| memory 更新（session_2026_06_XX） | ✓ | ✓ | ✓ | ✓ | ✓ |
| MEMORY.md 索引追加 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 手测 step 跑过 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 用户授权环 | — | — | — | — | ✓ |

---

## 9. 不在本 harness 内的事

- backfill 历史 portfolio_history（前 0 天）—— 60d 自然累积
- HK options（spread_type=BCS 占位）—— PR3 only QQQ
- intraday options 监控 —— PR6 单独
- portfolio_history 接入 monthly_kpi_report —— 单独迭代
- `worst_drawdown_pct` 语义改造 —— 保留旧字段不动

---

## 10. 修订记录

- 2026-06-07 v0.1 — 初稿（Claude Code 与用户对齐 4 项范围 + 中粒度 PR + 完整 harness 形态）
