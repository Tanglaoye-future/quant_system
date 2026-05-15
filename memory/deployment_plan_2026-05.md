---
name: 实盘部署计划 2026-05-15（四 universe 35/30/15/20 配置）
description: 8 年回测 Sharpe 1.198 后的实盘部署蓝图；4 账户配资（HK + A + QQQ + GLD）+ 季度再平衡
type: project
---

## 资金配置（基础资金 = 100%，v3 2026-05-15 升级为 5-asset 多策略）

| 账户 | 占比 | 标的 | 策略 |
|---|---|---|---|
| **HK 港股账户** | 25% | HSCHK100 成份股 | `daily_run --market hk_share` |
| **A 股账户 — 子策略 A** | 25% | HS300 momentum | `daily_run --market a_share --strategy bottomup_timing` |
| **A 股账户 — 子策略 B** | 15% | HS300 mean-reversion | `daily_run --market a_share --strategy mean_reversion` |
| **US ETF 账户** | 15% | QQQ ETF | 被动买入持有 |
| **黄金 ETF 账户** | 20% | GLD（境外）或 518880（华安黄金 ETF，境内）| 被动买入持有 |

**升级原因**（详见 `memory/multistrat_2026-05.md`）：A_mom vs A_mr 相关性 -0.172（负相关！），5-asset 多策略组合 Sharpe **1.225 / DD -7.94% / Vol 6.11%**，比 v2 4-asset 1.198 高 +0.027 同时 DD 更小、Vol 更低。

## 启动准备清单

### 1. 券商账户（用户操作）

- [ ] HK 港股账户（支持 hs100 成份；可选融资 / 期货）
- [ ] A 股账户（支持 hs300 成份）
- [ ] US 美股账户（持有 QQQ，0 操作）
- [ ] 黄金 ETF 通道（境内直接走 A 股账户买 518880；境外走 US 账户买 GLD）

### 2. 资金转入

按 35 / 30 / 15 / 20 分配。**注意**：HKD / CNY / USD 汇率波动会让账户占比漂移，初始配置以本币计价（按 transfer 时即期汇率换算）。

### 3. 策略服务端

只有 HK + A 两个账户跑策略：

```bash
# HK（35% 资金）
python scripts/daily_run.py --market hk_share --capital 350000

# A 股（30% 资金）
python scripts/daily_run.py --market a_share --capital 300000
```

US 账户买入 QQQ 后**不动**；黄金账户买入 GLD/518880 后**不动**。再平衡时调整。

### 4. 风控阈值

| 触发条件 | 行动 |
|---|---|
| HK 账户 30 天 DD > 15% | 暂停 daily_run，等 MA200 恢复 |
| A 股账户 30 天 DD > 15% | 暂停 daily_run，等 MA60 恢复 |
| GLD 30 天 DD > 20% | 维持仓位（被动持有）；下次再平衡评估 |
| QQQ 30 天 DD > 25% | 维持仓位（被动持有）；下次再平衡评估 |
| 单仓最大 20% | 已写在 strategy.single_position_pct_max |
| 持仓上限 10 只 | strategy.position_max_count |

## 再平衡规则

**频率**：每季度末（3 / 6 / 9 / 12 月最后一个交易日）

**逻辑**：

```
target = {HK: 0.35, A: 0.30, QQQ: 0.15, GLD: 0.20}
current = {账户实际市值占比}

for market, target_w in target.items():
    drift = current[market] - target_w
    if abs(drift) > 0.05:        # 偏离超 5pp 才动
        transfer to/from 该账户
```

**5pp 容忍带**：避免频繁交易摩擦。

## 业绩监控

### 月度 KPI

- 各账户单独 Sharpe（YTD）
- 组合 Sharpe（按 35/30/15/20 加权 daily return 重算）
- 与回测 Sharpe 1.198 的偏离度

### 警报阈值

- 实盘组合 Sharpe 连续 3 月 < 0.5 → 停盘检视
- 任一主动账户（HK / A）max DD > 20% → 该账户暂停
- 跨账户日收益相关性 60 天滚动 > 0.5 → 重新评估配比（历史 ρ ≤ 0.12）

## 已验证的关键不变量（来自回测 + 多 universe 分析）

1. HK 策略对 HSCHK100 beta = 0.155（MA200 门控已剥离大半 beta）
2. A 股策略对 HS300 beta ≈ 0.16（类似）
3. 4 个 universe 日收益相关性：HK↔A 0.00, HK↔QQQ -0.04, HK↔GLD 0.01, A↔QQQ 0.00, A↔GLD 0.04, QQQ↔GLD 0.12
4. HK on-regime hedge r=0.3 + A 股 on-regime hedge r=0.3 已生效（synthetic short overlay）
5. GLD 8 年单独 Sharpe 0.74 / +165% / DD -22% — 独立 alpha 源

## us_share 主动策略状态

**归档不上实盘**（config.yaml 已 `enabled: false`）。原因：8 年 Sharpe -0.05 / 总收益 +7% vs QQQ +241%。NASDAQ100 是 MAG7 集中市，均权 momentum 策略不适配。

## TLT / GBTC 不入选

- **TLT**: 8 年 Sharpe **-0.08**（加息周期长债大跌），即便低相关也无法拉 Sharpe
- **GBTC**: 73% 年化波动太极端，加入组合反而拖累 Sharpe（虽然总收益 +253%）

## 实盘交付物（用户验收）

1. ✅ HK / A 两个市场各自 8 年回测全部 PASS（admission_pass=True）
2. ✅ us_share 已 deprecated；QQQ 被动持有替代
3. ✅ 4-asset 组合 Sharpe 1.198 / DD -8.88% / 总收益 +109%（grid search 最优）
4. ✅ memory 文件齐全（项目+M0审计+HK+A+多 universe+四 universe+部署）
5. ⏳ 实盘部署后 3 个月数据验证（用户实际跑后）

## 风险/限制（明文）

1. **历史 ≠ 未来**：8 年相关性可能在未来漂移（2020 疫情期间所有市场短暂同步暴跌）
2. **GLD 牛市可能不持续**：2018-2026 期间金价 1200→2500+，未来若实际利率高企，GLD 可能 underperform
3. **再平衡成本**：4 账户跨市场 transfer 有税务 + 汇率摩擦，季度再平衡是平衡频率
4. **货币风险**：HKD/USD/CNY 三币种，HKD 联汇缓冲了汇率冲击，USD 持有的 QQQ/GLD 受 CNY 升贬影响
5. **黑天鹅**：2020-03 类全市场暴跌会突然把相关性推至接近 1，组合 DD 可能超 -9% 预算

**Why:** 2026-05-15 完成多资产扫描后的部署计划升级；加入 GLD 后回测 Sharpe 从 1.014 → 1.198；按「测试盘必须先赢」原则已具备实盘启动资格。
**How to apply:** 实盘启动前必读本文件；运行中每月检查 KPI 与警报阈值；如需调整配比，先回测验证再实施。
