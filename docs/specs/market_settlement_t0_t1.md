# Spec — equity_factor backtester settlement mode 市场独立化

## 背景

equity_factor `Backtester.run()` ([backtest.py:1-11](../../src/quant_system/strategies/equity_factor/engine/backtest.py)) 把
"信号 D 日盘后 → D+1 开盘价成交 + 当日买入不能当日卖" 当成跨市场固定常量。
但实际三市场结算规则不同：

| 市场 | 入场 settlement | 卖出 settlement | 同日买卖 |
|---|---|---|---|
| A 股 | T+1 | T+1 | ❌ 必须次日 |
| HK | T+0 | T+0 | ✅ 当日可平 |
| US | T+0 | T+0 | ✅ 当日可平 |

当前实现对 HK / US 多套了一天延迟（Step 3 `if pos.entry_date == day_dt: continue` 用 A 股 T+1 锁仓语义）。
HK 策略 v1→v14 / A1' 南向 gate 的所有结果，可能在 T+0 下重新校准 ≥+0.1 Sharpe（保守估计：少一天 trail 触发延迟）。

## 改动范围（最小化）

| 文件 | 改动 |
|---|---|
| `src/quant_system/market.py` | `MarketContext` 加 `settlement_mode: str`（`"t+0"` / `"t+1"`），默认按市场名兜底（a_share=t+1，其他 t+0） |
| `config/markets/a_share.yaml` | 显式 `settlement_mode: "t+1"`（self-documenting） |
| `config/markets/hk_share.yaml` | 显式 `settlement_mode: "t+0"` |
| `config/markets/hk_hsi.yaml` | 显式 `settlement_mode: "t+0"` |
| `config/markets/us_share.yaml` | 显式 `settlement_mode: "t+0"` |
| `config/markets/us_qqq.yaml` | 显式 `settlement_mode: "t+0"` |
| `src/quant_system/strategies/equity_factor/engine/backtest.py` | `Backtester.__init__` 加 `settlement_mode: str = "t+1"`（默认兼容旧调用）；Step 3 `if pos.entry_date == day_dt` 仅在 `settlement_mode=="t+1"` 时锁仓；docstring 头注释更新 |
| `scripts/backtest/backtest.py` | 入口读 `market_ctx.settlement_mode` 传给 Backtester；CLI 不暴露（市场配置驱动） |
| `tests/equity_factor/test_settlement_mode.py` | 新文件，4 case 覆盖（详见 验收） |

## 不做（Backstop 严守）

- ❌ **不改 alpha 逻辑** — 入场 signal / factor weight / RSI 带 / 量能门槛 / 资金流 widen 一行不动
  （[[a1prime_southbound_gate_falsified_2026-06]] 明文 reject "动 HK entry filter / RSI / 资金流"）
- ❌ **不改 zhuang T+1** — zhuang 是 A 股庄股专属，commit 7f34bf8 T+1 切换是 correctness fix，不动
- ❌ **不改 lot size** — A 股 100 股一手在 HK / US 是简化但不破坏 Sharpe 性质；本 PR 范围外
- ❌ **不改 daily_equity / 实盘交易闭环** — 仅回测执行层语义；实盘 T+0/T+1 由经纪商 settlement 决定，本 PR 不影响
- ❌ **不在 entry 侧引入"日内 / 盘前"信号** — settlement 改的只是"D+1 入场后能否当日 D+1 close 评估出场"，入场 timing 仍是 D+1 open（close-based signal 约束）

## 语义精确定义

T+0 vs T+1 在本 backtester 的差别**仅在 Step 3 "评估持仓 (今日盘后)" 这一处**：

```python
# 当前（A 股语义全局）：
if pos.entry_date == day_dt:
    continue   # 当日买的不能当日卖

# 改后：
if self.settlement_mode == "t+1" and pos.entry_date == day_dt:
    continue   # 仅 T+1 市场锁
```

**T+0 市场下的执行序**（HK / US）：
- D 日 close 后：信号触发 → pending_buys
- D+1 open：执行入场 → `pos.entry_date = D+1`
- **D+1 close 后：Step 3 评估持仓**（HK / US 可以触发出场信号）→ pending_sells
- D+2 open：执行出场

**T+1 市场下的执行序**（A 股）：
- D 日 close 后：信号触发 → pending_buys
- D+1 open：执行入场 → `pos.entry_date = D+1`
- D+1 close 后：Step 3 跳过该 pos（因 entry_date == day_dt）
- D+2 close 后：Step 3 评估持仓 → pending_sells
- D+3 open：执行出场

→ HK / US 出场延迟从 2 天压到 1 天（最小持仓周期 2 → 1 天）。

## 验收

### 单测（tests/equity_factor/test_settlement_mode.py 4 case）

1. **test_a_share_t1_locks_same_day_exit** — settlement_mode="t+1" + 入场当日 stop_loss 命中 → Step 3 跳过，next-day 评估
2. **test_hk_share_t0_allows_same_day_exit** — settlement_mode="t+0" + 入场当日（即 D+1 close）stop_loss 命中 → 加入 pending_sells，D+2 open 出场
3. **test_us_share_t0_allows_same_day_exit** — 同 2 但 market=us_share
4. **test_default_settlement_mode_is_t1** — Backtester(...) 不传 settlement_mode 时默认 "t+1"，与旧行为完全一致（无回归）

### 集成（HK 双窗口 backtest）

跑 `equity_hk_momentum` 4y (2022-2026-05-25) + 8y (2018-2026-05-25)：
- 记录 t+1 baseline（当前） vs t+0（本 PR）双窗口 Sharpe / 年化 / DD / WR / trades / max_hold
- 落 `memory/hk_t0_recalibration_2026-06.md`
- **不修 yaml** — yaml 改动是后续独立 PR（Backstop #4 PM 决策权）

### pytest 不回归

`pytest tests/equity_factor/` 通过基线（当前 313+）。

## Out-of-scope（follow-up）

- A 股 T+0 当日卖出禁止延伸到"次日是涨停板"等约束（已超出 settlement 层）
- HK / US lot size 真实化（HK 各股不同 lot, US 1 股）
- 实盘 IBKR / 港股账户 T+0 出场指令路由（PR 不动 daily_run）
- v5 组合层 grid 在 HK T+0 校准后是否需要重跑（PM 决策）

## 关联

- [[hk_optimization_2026-05]] — HK v1→v14 baseline（T+1 假设下）
- [[a1prime_southbound_gate_falsified_2026-06]] — HK sleeve 饱和判定（T+1 假设下）— 本 PR 后可能撬动
- [[v5_t1_recalibration_2026-06]] — zhuang T+1 切换前例，本 PR 是 settlement 语义校准的姐妹任务
- [[feedback_harness_first_pr_split]] — 本 spec 是 harness-first 第一步
