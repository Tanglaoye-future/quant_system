---
name: options-decouple-2026-05
description: 2026-05-25 Phase 1-A — options 子策略包按 equity_factor 模板拆 strategies/+markets/，underlying/vol_proxy/exchange/currency 全部参数化以支持 QQQ + HSI 双部署
metadata:
  type: project
---

## 背景

[[strategy_market_decouple_2026-05]] 完成 equity_factor 解耦后，options/zhuang 仍单市场硬编码。9-cell 可行性矩阵显示 options × hk_share ⚠️ 可达（IBKR 全球支持港股期权），Phase 1-A 做架构准备，Phase 1-E 等用户确认 IBKR HK 期权权限后跑 HSI 双部署。

## 改造范围

**新增 yaml**:
- `config/strategies/options_bull_call_spread.yaml` — 算法层（iv_engine 阈值/entry Delta/exit/momentum/signal_grades）
- `config/markets/us_qqq.yaml` — underlying=QQQ, vol_proxy=^VXN, exchange=SMART, currency=USD, contract_multiplier=100
- `config/markets/hk_hsi.yaml` — HSI 占位（contract_multiplier=50, HKFE/HKD）；策略 deployments 不含 hk_hsi → 不会被装配进 raw['markets']

**入口** `config/options.yaml`: 改为分裂结构（strategies + markets 引用列表），保留 broker/account 共享层

**装配器** `src/quant_system/config.py` `_assemble_split`: 扩展市场扩展键 + 算法扩展键白名单兼容 options 节（iv_engine/entry/exit/momentum/signal_grades 与 underlying/vol_proxy_ticker/exchange/currency/contract_multiplier/display）。equity_factor 现有字段集是白名单子集 → 零回归

**broker/ibkr.py**: `get_price/get_option_chain/get_option_quote/get_option_positions` 都把 exchange/currency 提为参数（默认 SMART/USD 保留兼容）。chain 内部 `if chain.exchange != exchange:` 不再写死 SMART

**signals/momentum.py + iv/engine.py**: ticker 移除默认值（必传），docstring 改通用；compute_ivr 加 cache_filename 参数自动按 ticker 推导 `vol_proxy_<NAME>.csv` 避免多 market 缓存互相覆盖

**utils/display.py**: print_signal_card / print_no_signal 接受 underlying_label / vol_label / currency_symbol / contract_multiplier 四个参数；所有硬编码 "QQQ" / "VXN" / "$" / "×100" 走参数

**scripts/daily/daily_options.py**: 拆为 `_select_markets` + `_run_one_market` + `main`，支持 `--market <name>` 显式选择，未指定时循环所有 enabled。report JSON 输出名按 market 区分（us_qqq → options.json 保留兼容；其他 → options_<market>.json）

## 关键设计决策

**1. 默认行为零变化**
- 入口 `config/options.yaml` 走分裂后，命令 `python scripts/daily/daily_options.py --no-ibkr` 默认只跑 us_qqq（hk_hsi deployment 未启用，不在 raw['markets']）
- **Why**: 用户协作风格"yaml/实盘改动前问"，本次仅架构，不动 IV 阈值/Delta/出场参数等任何策略数字
- **How to apply**: 改 options 策略数字才需 AskUserQuestion；本次纯架构 commit 不需要

**2. broker default 保留 SMART/USD**
- `get_option_chain(symbol, dte_min, dte_max, exchange="SMART", currency="USD")` 留默认
- **Why**: 历史调用方（测试、旧脚本）不传也能正常工作；新调用方（daily_options 多 market）显式传 market_ctx
- **How to apply**: Phase 1-E 跑 HSI 时显式传 exchange="HKFE", currency="HKD"

**3. IVSnapshot.vxn_current 字段名保留**
- 实际承载任意 vol_proxy（^VXN / VHSI / ...）的当前值，但字段名仍叫 vxn_current
- **Why**: 改名要级联 report builder + 前端 JSON 消费者；性价比不高
- **How to apply**: 新代码读 IVSnapshot 时把 vxn_current 视为"vol_proxy 当前值"语义

**4. 一市多策略检测保留**
- config.py 第 109-114 行抛错没解除（Phase 1-B 才解除）
- **Why**: 当前没有"两个 options 策略同 market 跑对照实验"诉求

## 验收记录

- pytest tests/options/ — **29/29 通过**（含 9 个新 test_config_split.py 用例）
- pytest tests/equity_factor/ tests/zhuang/ — **44/44 通过**（装配器扩展白名单零回归验证）
- daily_options.py --no-ibkr 端到端跑通：banner `[us_qqq] QQQ (SMART/USD)` + 参数化 print_no_signal + options.json 写盘 + HTML 报告重建

## 未来扩展指南

- **跑 HSI 双部署** (Phase 1-E): 修改 `config/strategies/options_bull_call_spread.yaml` 的 deployments 加 `- market: hk_hsi, enabled: true`；需先确认 IBKR 账户开通港股期权权限 + 验证 VHSI 在 yfinance 可拉
- **加新 underlying market** (如 SPY/IWM): 新建 `config/markets/<name>.yaml`，在入口 `markets:` 加一行，策略 deployments 加 market 条目
- **新期权策略** (Iron Condor / Bear Put Spread 等): 新建 `config/strategies/<name>.yaml`，kind 起新值；当前 daily_options 只处理 Bull Call Spread，新策略要在 daily 端 dispatch

## 不要做

- 不要把 IVSnapshot 改名 vxn_current → vol_proxy_current，跨边界字段，rename 成本高于收益
- 不要在 markets/hk_hsi.yaml 把 enabled 直接打开 —— 等 Phase 1-E 用户确认 IBKR 港股期权权限后再改
- Phase 1-A 留下的小遗留：`./venv/bin/python` 直跑脚本仍需 PYTHONPATH=src（.pth 没被 site.py 解析），是 pre-existing venv 安装问题，跟解耦无关，pytest 跑得通（conftest 注入 sys.path）

**Why:** 解耦完成后 options 子策略可以像 equity_factor 一样"算法独立迭代后部署到任意支持市场"；hk_hsi 占位让 Phase 1-E 只需翻 enabled + 验证数据可行性两件事.
**How to apply:** 改 options 算法（IV 阈值/Delta/出场规则）改 strategies/options_bull_call_spread.yaml；改 broker/合约规格 改 markets/<m>.yaml；daily 入口 --market 参数已支持多 market 循环.
