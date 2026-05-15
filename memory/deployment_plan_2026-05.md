---
name: 实盘部署计划 2026-05-15（三 universe 45/35/20 配置）
description: 8 年回测 Sharpe 1.014 后的实盘部署蓝图；分账户配资 + QQQ 被动 + 季度再平衡
type: project
---

## 资金配置（基础资金 = 100%）

| 账户 | 占比 | 标的 | 策略 |
|---|---|---|---|
| **HK 港股账户** | 45% | HSCHK100 成份股 | `daily_run --market hk_share` |
| **A 股账户** | 35% | HS300 成份股 | `daily_run --market a_share` |
| **US ETF 账户** | 20% | QQQ ETF | 被动买入持有 |

## 启动准备清单

### 1. 券商账户（用户操作）

- [ ] HK 港股账户（支持 hs100 成份，融资 / 期货可选）
- [ ] A 股账户（支持 hs300 成份）
- [ ] US 美股账户（持有 QQQ 即可，0 操作）

### 2. 资金转入

按 45 / 35 / 20 分配。**注意**：HKD / CNY / USD 汇率波动会让账户占比漂移，初始配置以本币计价（按 transfer 时即期汇率换算）。

### 3. 策略服务端

每个账户独立跑 `scripts/daily_run.py`：

```bash
# HK
python scripts/daily_run.py --market hk_share --capital 450000

# A 股
python scripts/daily_run.py --market a_share --capital 350000
```

US 账户**不跑策略**，季度再平衡时买卖 QQQ。

### 4. 风控阈值（依据回测 v9/v14 admission_pass）

| 触发条件 | 行动 |
|---|---|
| HK 账户 30 天 DD > 15% | 暂停 daily_run，等 MA200 恢复 |
| A 股账户 30 天 DD > 15% | 暂停 daily_run，等 MA60 恢复 |
| 单仓最大 20% | 已写在 strategy.single_position_pct_max |
| 持仓上限 10 只 | strategy.position_max_count |

## 再平衡规则

**频率**：每季度末（3 / 6 / 9 / 12 月最后一个交易日）

**逻辑**：

```
target = {HK: 0.45, A: 0.35, QQQ: 0.20}
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
- 组合 Sharpe（按 45/35/20 加权 daily return 重算）
- 与回测 Sharpe 1.014 的偏离度

### 警报阈值

- 实盘组合 Sharpe 连续 3 月 < 0.3 → 停盘检视
- 任一账户 max DD > 20% → 该账户暂停
- HK-A 实盘日收益相关性 60 天滚动 > 0.5 → 重新评估配比（历史 ρ=0.007）

## 已验证的关键不变量（来自回测）

1. HK 策略对 HSCHK100 beta = 0.155（MA200 门控已剥离大半 beta）
2. A 股策略对 HS300 beta ≈ 0.16（类似）
3. 三市场日收益相关性 ≤ 0.05（独立性极强）
4. HK on-regime hedge r=0.3 + A 股 on-regime hedge r=0.3 已生效（synthetic short overlay）

## us_share 主动策略状态

**归档不上实盘**（config.yaml 已 `enabled: false`）。原因：
- 8 年 Sharpe -0.05 / 总收益 +7% vs QQQ +241%
- NASDAQ100 是 MAG7 集中市，均权 momentum 策略不适配

后续可探索方向（非优先）：
- 仅交易 MAG7 子集 + 长持
- 加入 NDX 期权对冲 tail
- 接 Polygon 实时数据替代 akshare

## 实盘交付物（用户验收）

1. ✅ 3 个市场各自 8 年回测全部 PASS（admission_pass=True for HK + A，US 用 QQQ 代替）
2. ✅ 组合 Sharpe 1.014 / DD -9.1% / 总收益 +94%（grid search 最优）
3. ✅ memory 文件齐全（项目+M0审计+HK+A+多 universe+部署）
4. ⏳ 实盘部署后 3 个月数据验证（用户实际跑后）

## 风险/限制（明文）

1. **历史 ≠ 未来**：8 年相关性可能在未来漂移（2020 疫情期间所有市场短暂同步暴跌）
2. **再平衡成本**：3 账户跨市场 transfer 有税务 + 汇率摩擦，季度再平衡是平衡频率
3. **货币风险**：HKD 与 CNY 联汇制 → HK 对组合影响有限；USD 持有的 QQQ 受 CNY 升贬影响
4. **黑天鹅**：2020-03 类全市场暴跌会突然把相关性推至接近 1，组合 DD 可能超 -9% 预算

**Why:** 2026-05-15 完成所有可行的算法优化后的正式部署计划；按「测试盘必须先赢」原则，回测 Sharpe 1.014 已具备实盘启动资格。
**How to apply:** 实盘启动前必读本文件；运行中每月检查 KPI 与警报阈值；如需调整配比，先回测验证再实施。
