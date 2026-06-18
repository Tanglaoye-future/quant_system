---
name: etf-industry-rotation-probe-2026-06
description: 行业 ETF 轮动支线 probe 结论 — 整体 universe 撞硬否决线 (avg |corr_HS300|=0.629 ≥ 0.6), 但 9 只周期+中游科技 ETF (银行/芯片/光伏/军工/煤炭/能源/钢铁/半导体) corr<0.6 有独立 alpha 候选; 立项 = 待 (条件性, 等 CB 9 月 retrospective 后重审)
metadata:
  type: project
---

# 行业 ETF 轮动支线 probe 结论

**日期**: 2026-06-18
**触发**: 2026-06-16 用户审计 CB sleeve 闭环时同步开 ETF 支线 ([[cb-double-low-pr8-journal-portfolio-2026-06]] session)
**Scope**: 不立 spec / 不写策略代码, 半天工出数据回答 3 个硬问题
**Script**: `scripts/research/etf_industry_probe.py` (独立 probe, 不进 strategies/)

## 一句话结论

**整体行业 ETF 轮动作为 sleeve 立项 = 拒** (平均 corr_HS300=0.629 ≥ 0.6 硬否决线, 与 A_mom 重合度过高).
**细分周期+中游科技子集立项 = 待** (9 只 corr<0.6, 但 sector tilts 而非通用 alpha, 设计风险高).
**优先级**: 低于 CB sleeve 已开闭环, 等 2026-09 CB 实盘 retrospective 后重审是否值得开发. 当前 ETF probe 工作结束, 不进 daily.

## 数据 baseline

| 项 | 值 |
|---|---|
| ETF candidate | 20 只主流行业 ETF (申万一级映射手选) |
| 历史窗口 | 6Y (start 2020-06-18, 共同窗口 2021-01-31 → 2026-06-30) |
| 月度数据 | 66 月共同窗口, 全 20 只均 ≥ 60 月 ✅ |
| 数据可用性 | akshare `fund_etf_hist_em` 拉取全通过, qfq 复权可用, **数据层零障碍** |

## 与 A_mom (HS300 proxy) 相关性 — 硬否决线 cross-check

**硬否决线**: `|corr_HS300| ≥ 0.6` = 与 A_mom 重复 alpha, 无新增价值.

### FAIL (corr ≥ 0.6) — 11 只

| ETF | corr_HS300 | corr_CSI500 | 月均收益 |
|---|---:|---:|---:|
| 地产ETF (515380) | **+0.994** | +0.814 | +0.25% |
| 家电ETF (159996) | +0.852 | +0.725 | +0.26% |
| 消费ETF (159928) | +0.819 | +0.537 | -0.85% |
| 券商ETF (512000) | +0.818 | +0.752 | +0.05% |
| 酒ETF (512690) | +0.743 | +0.489 | -0.90% |
| 医疗ETF (512170) | +0.726 | +0.695 | -1.19% |
| AI ETF (159819) | +0.720 | +0.828 | +1.65% |
| 新能车ETF (515030) | +0.697 | +0.746 | +0.66% |
| 5G ETF (515050) | +0.665 | +0.713 | +2.42% |
| 创新药ETF (159992) | +0.644 | +0.664 | -0.69% |
| 通信ETF (515880) | +0.617 | +0.714 | +3.07% |

**核心洞察**: 这 11 只全是 "中游消费 + TMT 成长" — 历史与 HS300 高度共动, A_mom (HS300 momentum 选股) 已覆盖.

### PASS (corr < 0.6) — 9 只

| ETF | corr_HS300 | corr_CSI500 | 月均收益 | 备注 |
|---|---:|---:|---:|---|
| 煤炭ETF (515220) | **+0.295** | +0.382 | +1.71% | 极独立, 但 2021-2024 煤价周期红利, 可重复性存疑 |
| 能源ETF (159930) | **+0.301** | +0.289 | +1.58% | 极独立, 同上周期判断 |
| 钢铁ETF (515210) | +0.491 | +0.681 | +0.60% | 周期独立但收益平庸 |
| 军工ETF (512660) | +0.501 | +0.770 | +0.34% | 政策驱动 sector tilts |
| 半导体ETF (512480) | +0.513 | +0.697 | **+1.89%** | 高收益 + 中独立, 候选 winner |
| 银行ETF (512800) | +0.516 | +0.122 | +0.55% | 与 HS300/CSI500 都低, 高股息防御资产 |
| 芯片ETF (512760) | +0.541 | +0.720 | **+1.77%** | 与半导体 ETF 相似, 重复 |
| 光伏ETF (515790) | +0.560 | +0.747 | +0.27% | 中下游科技, 中等 |
| 芯片ETF广发 (159995) | +0.561 | +0.720 | **+1.83%** | 与 512760/512480 高度同构 |

**核心洞察**:
- 9 只 PASS 集中在 **周期 (银行/煤炭/能源/钢铁) + 中游科技 (芯片/半导体/光伏/军工)**
- **真正"独立 alpha"窗口实际只有 5-6 维**: (a) 周期资源 4 只(煤/能/钢/银行) (b) 中游科技 3-4 只(芯片/半导体/光伏/军工)
- 内部高度同构: 芯片ETF/半导体ETF/芯片ETF广发 3 只两两相关性极高, 实际只 1 个有效维度

## 与 v7 其他资产相关性 (定性, 未独立算)

- **vs CB sleeve**: CB 与 PR6 sweep 显示与 BTC/QQQ/GLD ≈ 0 (独立资产类别). 行业 ETF 是 A 股 sector tilts, 与 CB **预期相关性低** (CB 跟着债底, ETF 跟着 A 股), 有 hedge 价值候选, 但需实测
- **vs HK 50%**: HK 港股动量与 A 股 sector ETF 估计 corr 0.5-0.7, 中度同构
- **vs QQQ 10% / GLD 10% / BTC 10%**: 跨资产, corr 0.0-0.3 估计, 独立

## 硬决策矩阵

| Option | 描述 | 决策 |
|---|---|---|
| (a) **整体 28 行业 ETF 等权轮动** | n_entry=5 月度 RS 选 top | ❌ **否决** — avg corr 0.629 撞硬线, 等同 sector-blend A_mom |
| (b) **9 只 PASS 子集 RS 轮动** | n_entry=3 月度 RS top | ⏳ **待** — 实际只 5-6 有效维度, design space 小, 但 ASIC + 防御候选有 angle |
| (c) **dual momentum + 周期/科技 binary 切换** | 月度根据宏观信号在"周期 4 只" 和 "科技 4 只"间切换 | ⏳ **待** — 与 v6 regime overlay 同构风险高 |
| (d) **风格 ETF (红利/小盘/价值/成长)** | 与 A_mom 重合中度 | 🔄 **未 probe** — 留 follow-up 半天工 |
| (e) **跨资产 ETF (A vs HK vs US vs 黄金 vs 债券)** | 撞 v7 组合层 | ❌ **否决** — v7 efficient frontier 已覆盖 |

## 立项 = 待 (条件性)

**当前不开发**, 等满足以下任一条件再重审:

1. **CB sleeve 9 月 retrospective ([[cb-double-low-pr12-self-learning-2026-06]]) 显示真 alpha 贡献** → 项目证明"窄 sector 轮动"模式可工程化, 此时 Option (b) 复用方法论低成本
2. **风格 ETF probe** (Option d) 显示与 A_mom 中度独立 (corr 0.4-0.6) + 红利策略历史 sharpe ≥ 1.0 → 立 spec 走风格轮动 sleeve
3. **A_mom 9 月样本累积后 retrospective 暴露明确弱区** (如 "周期股月度 alpha 显著差") → 用 PASS 9 只里对应 sector ETF 补位

**当前不开发的理由**:
- avg corr 0.629 撞硬线, 即使做 PASS 子集也只有 5-6 有效维, design space 太小, 边际 sharpe 增量预期 < 0.1
- CB sleeve 刚 PR1-12 工程闭环完成 (实盘 N=0), 精力应放在 CB 实盘验证而非新 sleeve 起跑
- ≥90 天 + ≥30 笔不撬 backstop 精神同样适用 — 新 sleeve 立项前先看现有 sleeve 实盘表现

## 不再 probe 的方向 (明确归档)

- **主题 ETF (半导体/新能源/医药/AI/军工)**: probe 数据显示主题 ETF (AI/医药/创新药/新能车/5G) 全在 FAIL 桶, corr_HS300 > 0.6, 重复 A_mom alpha. **归档不再做**
- **整体 28 行业等权轮动**: avg corr 0.629 硬线撞死. **归档不再做**
- **跨资产 ETF (A/HK/US/黄金/债券) 轮动**: v7 efficient frontier (HK 50% + A_mom 15% + QQQ 10% + GLD 10% + BTC 10% + CB 5% + A_mr 0%) 已覆盖, 撞组合层. **归档不再做**

## 文件清单 (本次 probe 产出)

| 文件 | 说明 |
|---|---|
| `scripts/research/etf_industry_probe.py` | probe 脚本 (独立, 不进 strategies/) — 20 只 ETF universe + 6Y monthly + HS300/CSI500 baseline + 相关性矩阵 + 硬否决线 cross-check |
| `memory/etf_industry_rotation_probe_2026-06.md` | 本文件 |

## 关联

- [[cb-double-low-pr8-journal-portfolio-2026-06]] (CB sleeve PR8 起点, ETF 支线同期开)
- [[cb-double-low-pr12-self-learning-2026-06]] (CB retrospective 是 ETF 是否重启的触发器之一)
- [[project-north-star]] 支柱 1 例外: 纯指数标的不在选股层, 但必须服务组合层分散 — ETF 立项前必须证明组合层 sharpe 增量
- [[v7-efficient-frontier-2026-06]] (跨资产 ETF 已覆盖, ETF 行业轮动需补的是 sector dispersion)
- [[a_mr_v2_falsified_2026-05]] (反趋势 alpha 已死, ETF 轮动若做必须只做 trend RS, 不做 mean reversion)
