---
name: zhuang-market-dispatch-2026-05
description: 2026-05-25 Phase 1-C — zhuang 子策略包加 market 参数 + markets 子字典支持多 market dispatch；hk_small 占位为 Phase 1-D 接入铺路
metadata:
  type: project
---

## 背景

[[options_decouple_2026-05]] 和 [[equity_factor_multi_deploy_2026-05]] 完成后，zhuang 仍单市场硬编码（loader 全 baostock A 股；engine output_tag = `zhuang_a_share_*`）。9-cell 矩阵 zhuang × hk_share ⚠️ 数据+loader 大改才能跑；Phase 1-C 做架构准备，Phase 1-D 接入 HK provider + 跑回测验证算法对 HK 庄股有效性。

## 设计选择：最小破坏路径 (非 split config)

[[strategy_market_decouple_2026-05]] 模板下 zhuang 应该拆 `config/strategies/zhuang_v1.yaml + config/markets/{a_share, hk_small}.yaml`，但**没有这样做**。原因：

1. zhuang 当前**只 1 个算法**（zhuang_v1, L1-L5 已落地）；split config 价值在"算法独立迭代"，zhuang 无此诉求
2. **8 个 scripts/backtest/*_zhuang.py 用 yaml.safe_load 不走装配器**，强拆 config 会破坏所有 sweep 脚本
3. 真正的诉求是"HK 也能跑"，loader+backtest 加 market 参数即可

折中：**保留 config/zhuang.yaml 单层结构**，新增 `markets:` 子字典支持多 market dispatch。

## 数据结构

**config/zhuang.yaml** 新结构:
```yaml
default_market: a_share

# Legacy 顶层 universe 保留 (向下兼容 sweep scripts; ZhuangDataLoader fallback)
universe: {...}

# 多 market dispatch (Phase 1-C 新增)
markets:
  a_share:
    enabled: true
    data_provider: baostock
    benchmark: sh.000905           # 中证 500
    fees: {stamp_tax: 0.001}
    universe: {...}
  hk_small:
    enabled: false                  # Phase 1-D 接入后翻 true
    data_provider: hk_akshare       # 占位; Phase 1-D 真实接入
    benchmark: HSI
    fees: {stamp_tax: 0.0013}       # HK 双边
    universe: {...}
```

**ZhuangDataLoader(config, refresh_days, market="a_share")**:
- market 参数默认 a_share (向下兼容 sweep scripts)
- 优先用 `config["markets"][market]`; 缺失回退顶层 universe (legacy single-market dict)
- `self.market_cfg` 暴露给 ZhuangBacktester (拿 fees / benchmark)
- `self.data_provider` 决定数据源: baostock → 当前路径；hk_akshare/hk_yfinance → NotImplementedError (Phase 1-D 接入)
- DuckDB store 调用 `store.has_code(self.market, code)` 不再硬码 "a_share"

**ZhuangBacktester(config, loader)**:
- stamp_tax 优先 `loader.market_cfg.fees.stamp_tax`，回退 `backtest.stamp_tax` (legacy)
- market_trend_index 优先 `loader.market_cfg.benchmark`，回退 `strategy.market_trend_index`
- output_tag = `zhuang_{loader.market}_{start}_{end}` (a_share 时仍是 `zhuang_a_share_*` 历史命名兼容)

## 关键设计决策

**1. 不强制构造时检查 baostock**
- `_require_bs()` 从 __init__ 移到 _login()
- **Why**: pytest 测试机器 (venv) 没装 baostock，但用户应能跑 unit test 验证架构 (test 不真 login)
- **How to apply**: 新 provider 接入时同样模式 (检查推迟到真用时); __init__ 只做参数 validate

**2. hk_small 在 __init__ 立即 NotImplementedError**
- 不让 hk_small ZhuangDataLoader 构造成功 (provider 还没接入)
- **Why**: 早失败 (fail-fast) 比让用户跑了一半才发现拉数据无 provider 好
- **How to apply**: Phase 1-D 真实现 hk_akshare provider 后, 把 NotImplementedError 分支删掉

**3. legacy fallback 不写 warn**
- 旧 config (顶层 universe 没 markets 字段) 静默走 fallback
- **Why**: sweep scripts 都还在 legacy 模式; 加 warn 会污染所有 sweep 输出
- **How to apply**: 跑完 Phase 1-D 把 sweep 脚本逐个迁移到新结构后再加 deprecation warn

## 验收记录

- pytest 全套件 **93/93 通过** (含 11 个新 test_market_dispatch.py: markets 字段验证 / loader dispatch / legacy fallback / backtester market wiring)
- 8 个 sweep_zhuang scripts 不改动 (ZhuangDataLoader 默认 market=a_share, 顶层 universe fallback 仍工作)
- daily_zhuang.py / backtest_zhuang.py 加 --market 参数支持显式指定

## 不要做

- 不要在 Phase 1-C 直接接入 HK provider 数据源 (akshare/yfinance HK 小盘股 universe) — 这是 Phase 1-D 的责任，需要先调研 universe 数据源 + benchmark 选型
- 不要重命名 output_tag `zhuang_a_share_*` → `zhuang_a_share_small_*` 之类; 历史回测结果目录都用此命名
- 不要把 zhuang 拆成 split config (strategies/ + markets/) — YAGNI; 等真有 zhuang_v2 算法或 Phase 2 实现 cross-strategy 共享逻辑时再做

## 未来扩展指南

- **Phase 1-D 接入 HK provider**: 在 ZhuangDataLoader 加 `elif self.data_provider == "hk_akshare"` 分支实现 _fetch_universe_hk / _fetch_daily_hk; markets/hk_small/universe 改实际筛选规则; benchmark 选 (HSI? HSCEI? HSCHK小盘 index?); 翻 markets.hk_small.enabled=true
- **strategy timing 跨 market 调优**: 当前 `strategy.*` 节在跨 market 共享; 如 HK 庄股需不同 max_hold_days/take_profit_pct, 加 `markets.<m>.strategy_overlay:` 子字典 + ZhuangBacktester 读取时合并 (类似 [[equity_factor_multi_deploy_2026-05]] 的 timing_overlay 思路)
- **多策略对照** (zhuang_v2): 真升级 split config 时, 8 个 sweep scripts 改走 `quant_system.config.load_config` 装配器

**Why:** zhuang 包架构准备好支持多 market dispatch, Phase 1-D 接入 HK provider 后即可跑回测；实盘 daily_run 保持 a_share 默认零改动.
**How to apply:** 改 zhuang 算法逻辑改 `strategy.*` 节 (跨 market 共享); 改 universe/benchmark/费率改 `markets.<m>` 节; 跑 cross-market 实验用 `--market hk_small` (Phase 1-D 启用后).
