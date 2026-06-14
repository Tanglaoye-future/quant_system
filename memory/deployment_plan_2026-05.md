---
name: 实盘部署计划 2026-06-12（趋势交易转向 — A_mr 停用 + 三市场全扫描）
description: 6 资产配资（HK + A_trend + A_trend_scan + zhuang + QQQ + GLD）+ 季度再平衡；2026-06-12 关停 A_mr/SP500/NASDAQ100，新增三市场全扫描趋势策略
type: project
---

## ⚠️ 2026-06-12 策略转向（趋势交易）

**关停**：A_mr mean_reversion（8y Sharpe ~0 纯噪音）、SP500 momentum（4y Sharpe -0.18）、NASDAQ100 momentum（8y Sharpe -0.05）

**新增**（回测验证中）：
- `equity_trend_scan_a` — A 股全市场纯量价趋势（3866 只）
- `equity_trend_scan_hk` — 港股全市场纯量价趋势
- `equity_trend_scan_us` — 美股全市场纯量价趋势

**保留**：equity_momentum (hs300) / equity_hk_momentum (hs100) 作为对照，待全扫描版回测通过后决定去留。

## 资金配置（基础资金 = 100%，待全扫描回测后重新 grid search）

| 账户 | 占比 | 标的 | 策略 |
|---|---|---|---|
| **HK 港股账户** | **25%** | HSCHK100 成份股 | `daily_run --market hk_share` |
| **A 股账户 — 子策略 A** | **10%** | HS300 momentum (L9-A) | `daily_run --market a_share --strategy equity_momentum` |
| **A 股账户 — 子策略 B** | 0% | ~~HS300 mean-reversion~~ (2026-06-12 停用) | 等待 trend_scan_a 回测结果替代 |
| **A 股账户 — zhuang ⭐** | **40%** | A 股 50亿-2000亿中小盘 | `daily_zhuang.py` |
| **US ETF 账户** | **5%** | QQQ ETF | 被动买入持有 |
| **黄金 ETF 账户** | **10%** | GLD（境外）或 518880（华安黄金 ETF，境内）| 被动买入持有 |

**v5 升级原因**：从量化对冲基金视角的组合层优化。

- **P1 grid search**（2020-2026, 27,237 组合）：v4 (20/20/10/20/15/15) Sharpe 1.86 → v5 (25/10/10/40/5/10) Sharpe **2.22 / DD -2.7%**。
- **P1+ 跨区间稳健性**：v5 在 5 个市场段 DD 全部更小；**2022 熊市 v4 是 -0.62（亏损年）而 v5 是 +0.47（盈利年）**。
- **2026-06-12 更新**：A_mr 停用后 10% 权重待重分配，趋势全扫描回测通过后重新 grid search 组合权重。

**⚠️ v5 的真实 trade-off — 防守倾斜**：v5 比 v4 更防守，在 beta 驱动的强反弹段（2020 疫情后 / 2023-24）少赚一点（ΔSharpe -0.38 / -0.18，但绝对 Sharpe 仍 >1.0 / >2.8）。换来全局更低 DD + 熊市抗跌。**若判断未来是持续大牛市，可回调 QQQ/GLD 权重吃 beta；若优先下行保护，维持 v5。**

**⚠️ v5 capacity 前提**：40% zhuang 仅在**总 AUM ≤ 30M RMB** 时无障碍。AUM 超 100M 必须把 zhuang 压回 20-25%，并把腾出的权重给 HK（流动性最好）。

旧 v4 数据存档：zhuang L4+L5 优化后单资产 Sharpe 2.35（2020-2026），与所有资产相关性 ≤0.06（详见 `memory/zhuang_overlay_combo4_2026-05.md`）。equity_factor 现为 L9-A（regime-aware partial），4y Sharpe 0.84 / 8y 0.36（详见 `memory/equity_factor_l9_partial_regime_2026-05.md`）。

## 启动准备清单

### 1. 券商账户（用户操作）

- [ ] HK 港股账户（支持 hs100 成份；可选融资 / 期货）
- [ ] A 股账户（支持 hs300 成份）
- [ ] US 美股账户（持有 QQQ，0 操作）
- [ ] 黄金 ETF 通道（境内直接走 A 股账户买 518880；境外走 US 账户买 GLD）

### 2. 资金转入

按 v5 = HK 25 / A_mom 10 / A_mr 10 / zhuang 40 / QQQ 5 / GLD 10 分配。**注意**：HKD / CNY / USD 汇率波动会让账户占比漂移，初始配置以本币计价（按 transfer 时即期汇率换算）。

### 3. 策略服务端

HK + A 两个账户跑策略（A 账户内含 momentum 10% + zhuang 40% = 50%；A_mr 已停用，10% 待重新分配）：

```bash
# HK（25% 资金，示例总资金 1M → 250K）
python scripts/daily/daily_equity.py --market hk_share --strategy equity_hk_momentum --capital 250000

# A 股 momentum L9-A（10%）
python scripts/daily/daily_equity.py --market a_share --strategy equity_momentum --capital 100000

# A 股 zhuang（40%）
python scripts/daily/daily_zhuang.py --capital 400000

# 新趋势全扫描（待回测验收后启用，capital_pct 待定）
# python scripts/daily/daily_equity.py --market a_share --strategy equity_trend_scan_a --capital 100000
```

US 账户买入 QQQ（5%）后**不动**；黄金账户买入 GLD/518880（10%）后**不动**。再平衡时调整。

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
# v5 (2026-05-28 grid search + 稳健性验证)
target = {HK: 0.25, A_mom: 0.10, A_mr: 0.10, zhuang: 0.40, QQQ: 0.05, GLD: 0.10}
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
