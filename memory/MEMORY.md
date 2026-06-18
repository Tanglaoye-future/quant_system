# Memory Index

按主题分区。每条 single-line hook (~150 char). ⭐ 标 cold-start 必读. 详细叙事进各 memory 文件本体.

## 🌟 北极星 + 当前焦点 (cold-start 必读)

- [项目北极星 — 4 支柱硬框架](project_north_star.md) ⭐⭐⭐ — 2026-06-14 确立 / 06-15 扩展; 每次 yaml/策略/架构改动前必 cross-check; 撞框架外默认拒绝
- [2026-07-01 CB 首次实盘 rebalance PM 操作手册](cb_double_low_2026_07_01_pm_operations.md) ⭐⭐⭐ — 6 phase 流程 + 5 异常 fallback + 9 月决策点; 7/1-9/30 唯一 reference
- [Project overview](project_quant_system.md) — repo 结构 + 模块 + 设计原则
- [M0-M终 milestones + audit](project_quant_milestones.md) — M-node 定义 + 产物契约 + 通用 checklist
- [策略优化计划 (active)](strategy_optimization_plan.md) — 2026-05 起 3 级优先级任务清单 + 当前进度

## 📊 CB 双低 sleeve (PR1-12 + ETF 支线)

### CB 工程闭环 (PR1-12)
- [CB 立项 + 数据 probe PASS 2026-06](cb_data_probe_2026-06.md) ⭐⭐ — A 股 v7 饱和后唯一通过 4 支柱 + akshare 4 端点 + 容量 < 100M
- [CB PR1-7 全闭环 oneshot session](session_2026_06_16_cb_pr1_7_oneshot.md) ⭐⭐⭐ — 单 session 9 commit 14hr 立项→spec→loader→strategy→backtester→双窗口 PASS→v7 STRONG PASS→yaml+daily 落地
- [CB PR5 — 4y/6y 双窗口同向 PASS](cb_double_low_pr5_4y6y_2026-06.md) ⭐⭐⭐ — Sharpe +0.839/+1.419, CAGR 25.13%, DD -14.87%, 首个有数据支撑新方向自 v7 + 18 证伪后
- [CB PR6 — v7 组合层叠加 STRONG PASS](cb_double_low_pr6_v7_overlay_2026-06.md) ⭐⭐⭐ — 6 候选 4 dominate; Top1 A_mom→CB 15% Δ+0.13/+0.28; CB 与 A_mr -0.156 hedge
- [CB PR7 — yaml + daily advisory](cb_double_low_pr7_yaml_daily_2026-06.md) ⭐⭐⭐ — Option 1 CB 5%(A_mom 抽); v7 实盘配比 HK50/A_mom15/QQQ10/GLD10/BTC10/CB5; advisory only 不接 journal
- [CB PR8 — journal + portfolio_history schema](cb_double_low_pr8_journal_portfolio_2026-06.md) — 复用 journal_trades 共享表(strategy='cb_double_low' + market='cb_a' + entry_features JSONB); 反例: 中途自作主张 ingest_cb 撞 PR7 advisory 不入 DB 决策回滚
- [CB PR9 — daily rebalance signal](cb_double_low_pr9_rebalance_signal_2026-06.md) — 反查 Journal 输出 BUY/SELL/HOLD 三栏 + rebalance/maintenance mode (day<=5 启发式) + urgent/deferred 对称
- [CB PR10 — 实时风控接 intraday](cb_double_low_pr10_intraday_risk_2026-06.md) — close<85 + 强赎临近 ≤30d 推 Telegram; 复用 AlertEvent 通道; 不做 dual_low_score 实时 (PR9 daily 已覆盖); 不做 T+0 (risk-parity 豁免)
- [CB PR11 — closed_trades + cb_exit_taxonomy + HTML section](cb_double_low_pr11_closed_trades_html_2026-06.md) — 6 CB layer (SCORE_EXIT/STOP_LOSS/FORCE_REDEEM/REBALANCE/DELISTED/OTHER) + close_cb_trade wrapper + Journal.update_exit_features 浅合并
- [CB PR12 — self_learning_pipeline 加 CB sleeve](cb_double_low_pr12_self_learning_2026-06.md) — 修 A_mom 桶吞 CB bug + §5 exit_type sleeve-aware; 5 条 Backstop 严守; 9 月 ≥30 笔触发首次有意义报表
- [akshare CB panel 单 ticker 网络异常 per-code retry](akshare_cb_panel_timeout_2026-06.md) — load_panel 网络异常 per-code 兜底, 单 ticker 挂不再拖死 panel

### 支线 probe
- [行业 ETF 轮动 probe 2026-06](etf_industry_rotation_probe_2026-06.md) — 整体 avg |corr_HS300|=0.629 ≥ 0.6 硬否决; 9 只周期+中游科技 corr<0.6 待 9 月 CB retrospective 后重审; 主题/整体 28 行业/跨资产 三路径明确归档

## 💰 V5 / V6 / V7 组合层

- [V7 efficient frontier 2026-06](v7_efficient_frontier_2026-06.md) ⭐⭐⭐ — Top1 HK50/A_mom20/A_mr0/QQQ10/GLD10/IBIT10; 4Y Sharpe +1.842 / 8Y +1.455 / DD -12.5%; supersede v5
- [V7 实盘部署计划 2026-06](deployment_plan_v7_2026-06.md) ⭐⭐⭐ — 3 账户 + W0-W5 持仓上限路径 + 季度再平衡 ±5pp; HK 账户是 blocker; v7b (HK 0%) reverse fallback
- [V5 efficient frontier 2026-05](v5_efficient_frontier_2026-05.md) — +IBIT/+TLT/+CSI1000 全负贡献; 5 组合层路径全证伪 → v5 是真 efficient frontier; 已 supersede by v7
- [V5 T+1 重校准 2026-06](v5_t1_recalibration_2026-06.md) — zhuang T+1 后 v5 8y 2.231→1.801; grid 真最优砍 zhuang 到 10-15%; 5 选项 PM 决策; supersede v5_efficient_frontier
- [V5 grid HK T+0 重校准 2026-06](v5_grid_hk_t0_recalibration_2026-06.md) — HK T+0 重跑 v5 grid 双窗口 Top1 与 T+1 identical; v5 frontier 不被 T+0 改写
- [V6 regime overlay 证伪 2026-05](v6_regime_overlay_2026-05.md) — 双 MA200 动态权重全窗口 2.142 < v5 静态 2.231; 4 段微优但 2025-26 反弹 -0.40 rebalance lag; v5 = efficient frontier
- [P1 权重 + P2 zhuang capacity 2026-05](portfolio_p1_p2_weights_capacity_2026-05.md) — 6-asset grid 1.86→2.22 最优 (zhuang 40 / A_mom 降); P1+ 稳健性 2022 v4→v5 转正
- [P3 A_mr + Options BCS baseline 2026-05](portfolio_p3_amr_options_baseline_2026-05.md) — A_mr 弱 (纯 hedge 价值); Options BS 近似 Sharpe 1.2-1.4 准-QQQ 替代; A_mr DuckDB stale-data bug 捕获
- [Multi universe (HK+A) 2026-05](multi_universe_2026-05.md) — HK+A 相关性≈0, 50/50 Sharpe 0.85 / DD -7.9%
- [Three universe (+QQQ) 2026-05](three_universe_2026-05.md) — 45/35/20 Sharpe 1.014 / DD -9.1%, 突破对冲基金门槛
- [Four universe (+GLD) 2026-05](four_universe_2026-05.md) — 35/30/15/20 Sharpe 1.198 / DD -8.88%; TLT/GBTC 排除
- [Multistrat + Vol targeting 2026-05](multistrat_2026-05.md) — +A_mr 5-asset 25/25/15/15/20 Sharpe 1.225; 杠杆不改 Sharpe
- [实盘部署计划 2026-05](deployment_plan_2026-05.md) — 5-asset 配置 / 季度再平衡 / KPI; 已 supersede by v7
- [部署 checklist 2026-05](deploy_checklist_2026-05.md) — Step 0-6 + launchd + 首月 KPI + 紧急停盘流程

## 🇨🇳 Equity factor (HK / A 股 / US)

### 主腿迭代
- [Equity_factor L7 实盘修复 2026-05](equity_factor_l7_2026-05.md) — Pullback 入场全失败 → C3 出场优化 (regime+partial+collar) 4Y Sharpe +174% / DD 改善 5pp
- [Equity_factor L8 fcf_yield 因子层 2026-05](equity_factor_l8_2026-05.md) — fcf_yield 双窗口负贡献; L8D2 fcf=0 落 yaml 4Y +0.10/8Y +0.13; DD 恶化 2.7pp trade-off
- [Equity_factor L9-A regime partial_exit 2026-05](equity_factor_l9_partial_regime_2026-05.md) — 牛市跳 partial 全平; 4Y ma200 0.844 / 8Y 0.363; 已落 yaml
- [Equity_factor multi-deploy 2026-05](equity_factor_multi_deploy_2026-05.md) — equity_momentum 列 3 市场 (hk/us 默认 disabled); cross-market 命令行解锁

### HK
- [HK 策略 v1-v10 优化 2026-05](hk_optimization_2026-05.md) — HK 价值因子反 alpha + on-regime hedge 优于熊市对冲
- [HK AH premium alpha 微研究 2026-05](hk_ah_premium_research_2026-05.md) — 5 只 H+A 8Y, z60≥1 lift +0.32pp 但 std 大; 按 zhuang_hk 模板"先调研不实现"
- [HK T+0 recalibration 2026-06](hk_t0_recalibration_2026-06.md) — Backtester market-aware settlement; HK 4Y Sharpe +0.059 / 8Y +0.065 双窗口同向 PASS; A1' 需在新 baseline 重审
- [HK TP runner sweep 证伪 2026-06](tp_runner_sweep_falsified_2026-06.md) — 12 变体 0 同向 PASS; 4Y stop=3.0 改善但 8Y 反向; TP 5×ATR 死代码不能动; 第 18 条证伪

### A 股 - mean reversion
- [A_mr rebuild + v6 grid 反向洞察 2026-05](a_mr_rebuild_v6_grid_2026-05.md) — A_mr hedge 价值 > solo, 砍 A_mr 反而组合恶化; 保留 v5
- [A_mr v2 证伪 (4 路径全死)](a_mr_v2_falsified_2026-05.md) — v1/v2/v6/regime 全 plateau -0.27~-0.34; A_mr = noise diversification 不是 alpha; 未来不再投 strategy 层

### A 股 - 跨市场
- [A_share 从 HK 移植 (E)](a_share_e_transfer_2026-05.md) — L1/L2 不可移植; L3 hedge 可移植 +0.05 Sharpe; +fcf_yield +0.02
- [A1 北向死 + A1' 南向 pivot 2026-06](a1_northbound_dead_southbound_alive_2026-06.md) — 北向 akshare 2024-08 起停更永久封死; pivot 到南向 overlay
- [A1' 南向 gate 证伪 2026-06](a1prime_southbound_gate_falsified_2026-06.md) — 4Y -0.058 + base rate spurious; HK sleeve 当前架构饱和 → 四层 efficient set 同构升级
- [A2 CSI1000 L9-B paradox 证伪 2026-06](a2_csi1000_l9b_paradox_falsified_2026-06.md) — ROIC×ROE Spearman 0.92-0.95 + AR YoY 季节性 artifact; 第 15 条证伪 + 五层 efficient set
- [Equity C ensemble 4Y PASS / 8Y FAIL](equity_factor_c_ensemble_falsified_2026-06.md) — 4Y +0.082 → 8Y -0.052; paradox 第 6 类 (窗口依赖); 第 17 条; AMBIGUOUS ≡ SOFT-FALSIFY
- [Equity_factor L9-B ROIC/AR 证伪 2026-05](equity_factor_l9b_falsified_2026-05.md) — ROIC -0.096 (与 ROE 重复) + AR YoY -0.031 (行业属性); L8D2 = HS300 efficient set; 与 zhuang L1-E 同构

### US
- [SP500 负结果 2026-05](sp500_negative_2026-05.md) — 503 ticker 工程完整, 4Y Sharpe -0.18 FAIL; 换 universe 不救美股 momentum
- [US fundamentals via yfinance 2026-05](us_fundamentals_yfinance_2026-05.md) — yfinance 93/93 cache; US 4Y baseline -0.22 不变, 待 quality sweep / 换 universe / 维持
- [US T+0 recal 不对称 2026-06](us_t0_recalibration_asymmetry_2026-06.md) — SP500 4Y +0.153/8Y +0.031 同向; NASDAQ100 4Y -0.195/8Y -0.029 反向 (MAG7 集中度 + 高 RSI 早出场)

## ⚙️ 实时风控 + 日内 T

- [盘中实时风控 v1 (持仓 v2 PR5 收官) 2026-06-07](session_2026_06_07_pr5_intraday_telegram.md) — alerts_sent dedup + TelegramSender + intraday/core.py evaluate_alerts + nohup --loop; 21 case + 281/281 pytest
- [日内做 T 执行层 PR1-5 闭环 2026-06](intraday_t_execution_pr1_5_2026-06.md) — A 股 advisory only + 3 层综合触发 + 25 case + 6 不变量代码层强制; ≥90 天/30 笔不撬; auto-execute/HK/US 扩展 out-of-scope
- [盘中实时风控 v0 audit 2026-06-04](session_2026_06_04_realtime_risk_v1.md) — 用户首次实盘 4 只 A_mom "回撤"焦虑; safety margin + 组合层 alerts; max DD + Step 3 推迟
- [Self-learning pipeline + 实盘亏损诊断 2026-06-08](session_2026_06_08_self_learning_pipeline.md) ⭐ — 真问题=Bug A (VARCHAR32) + Bug B (alembic dormant) + Bug C (DuckDB stale-flock); 5 PR pipeline; 5 条 Backstop; 313/313 pytest

## 🔧 基建 / 架构

- [三层解耦 P0-P3 + journal Postgres 2026-05](db_decouple_phase0_2026-05.md) — 单 repo 强边界; journal SQLite 迁 PG; daily_equity 现硬依赖 PG; builder JSON 降级冷备
- [DuckDB 数据层迁移 2026-05](duckdb_migration_2026-05.md) — 三策略统一 data/quant.duckdb; loader DB-first + CSV fallback
- [前后端分离 Apple 风格改造 2026-05](frontend_backend_refactor_2026-05.md) — FastAPI + React/Vite/Tailwind; 自动开平仓; 3 daily 串联
- [前端 single-pane 2026-06](frontend_single_pane_2026-06.md) — Phase 3 消弭 HTML 孤岛; rebuild_html_report→noop; 新数据走 JSON+API+前端组件
- [策略-市场解耦 2026-05](strategy_market_decouple_2026-05.md) — equity_factor 内 strategies/+markets/ 拆分; MarketContext 抽象
- [Options 解耦 Phase 1-A 2026-05](options_decouple_2026-05.md) — options 包按 equity_factor 模板拆; underlying/vol_proxy 参数化; hk_hsi 占位
- [Monthly KPI 报表脚手架 2026-05](monthly_kpi_scaffold_2026-05.md) — scripts/reporting/monthly_kpi_report.py + 10 单测; 2026-06-30 首次 checkpoint
- [仓库迁出 Documents 计划](migration_out_of_documents_plan.md) — ~/Documents/projects/quant_system → ~/quant_system 消除 TCC 阻塞 launchd; 8 步

## 🚫 庄股 (Zhuang) — 2026-06-14 弃用

- [Zhuang 弃用决策 2026-06-14](zhuang_deprecated_2026-06.md) ⭐ canonical — 违反支柱 1+2; config disable + 代码归档; 15-25% 权重暂留现金; 重启需先扩框架 5 步
- [Zhuang 优化 v1→L5 2026-05](zhuang_optimization_2026-05.md) — Sharpe 0.944→1.806; L1-E 入场 + L4 出场收紧 + L5 score 加权
- [Zhuang L1/L2/L3 实验 2026-05](zhuang_l1_l2_l3_experiments_2026-05.md) — entry filter / accumulation weight / exit rule 三层全记录
- [Zhuang L4 出场 combo4 2026-05](zhuang_l4_experiments_2026-05.md) — 6Y Sharpe 1.39→1.63 落 yaml
- [Zhuang L5 score 分级 sizing 2026-05](zhuang_l5_experiments_2026-05.md) — 3%/5%/8% 6Y Sharpe 1.63→1.81 收益 +48→+76%
- [Zhuang L6-A weights→equal 2026-05](zhuang_l6a_weights_2026-05.md) — equal (0.20×5) 双窗口同向赢 baseline; sleeve→组合放大率 ≈0.45×
- [Zhuang L7-A position_max_count 证伪](zhuang_l7a_falsified_2026-05.md) — 6/8/10 同分 Sharpe 1.505; cap 永不 binding; 真瓶颈在入场严格度
- [Zhuang L7-B score 阈值反向证伪](zhuang_l7b_falsified_2026-05.md) — 70→67→65 单调下 1.505→0.925→0.843; L1-E sweet spot 确认
- [Zhuang L8 fundamentals gate 证伪](zhuang_l8_fundamentals_falsified_2026-05.md) — winner/loser ROE>0 73% vs 79% 反向; 误杀 47% ≈ 随机; 跳完整 sweep
- [Zhuang gap-up + score precheck 双证伪 2026-06](zhuang_gap_score_precheck_falsified_2026-06.md) — gap-up 5%+ 是唯一正收益 bin; score 缺失 84%; alpha 在 lottery-ticket 尾部
- [Zhuang overlay 5-asset 2026-05](zhuang_overlay_2026-05.md) — 与 5-asset 相关性≈0; 10% Sharpe 1.30→1.35 / DD -7.94→-7.01
- [Zhuang L4-combo4 后 6-asset overlay](zhuang_overlay_combo4_2026-05.md) — 单资产 Sharpe 2.35; 25% 把组合 1.91→2.21 / DD -7.6→-5.1
- [Zhuang sweep 2026-06-12 (B1-B6)](zhuang_sweep_2026-06-12.md) — 6 类 16 变体 3Y+8Y; extreme tiered sizing [70,85]→[2,5,10]% 8Y Sharpe +0.029 落 yaml
- [Zhuang market dispatch (HK 占位) 2026-05](zhuang_market_dispatch_2026-05.md) — ZhuangDataLoader 加 market 参数; hk_small 占位 NotImplementedError
- [Zhuang HK 调研 2026-05](zhuang_hk_research_2026-05.md) — HK provider 数据源全 blocked + 庄股先验存疑; 退回先调研
- [Case 600584 -14.32% 三重 gap 2026-06](case_2026_06_08_600584_distribution.md) — 实盘 6-1 advisory PM 没卖 + DuckDB 4 天 stale + "已跌穿"无视觉差; 拿住做训练样本; M4+M5 修法

## 📅 Sessions (chronological, 倒序)

### 2026-06 (CB + closure)
- [2026-06-16 CB PR1-7 oneshot](session_2026_06_16_cb_pr1_7_oneshot.md) ⭐⭐⭐ — 见上 CB 区
- [2026-06-09 实时数据 intraday 5min](session_2026_06_09_realtime_data_intraday_5min.md) — 5min poll 升级 + akshare 限频处理
- [2026-06-09 PR3 zhuang distribution dashboard poll](session_2026_06_09_pr3_zhuang_distribution_dashboard_poll.md) — distribution alerts 接前端
- [2026-06-09 PR2 watchlist breakout](session_2026_06_09_pr2_watchlist_breakout.md) — daily_screen_breakout + watchlist asof 滚动
- [2026-06-08 self-learning pipeline](session_2026_06_08_self_learning_pipeline.md) ⭐ — 见上风控区
- [2026-06-07 PR5 盘中实时 Telegram](session_2026_06_07_pr5_intraday_telegram.md) ⭐ — 见上风控区
- [2026-06-07 PR4 HK+A_mr 副腿回归](session_2026_06_07_pr4_hk_amr_regression.md) — 8 case 锁字段集 v1 在副腿生效; 纯测试 PR; 260/260
- [2026-06-07 PR3 options BCS 持仓字段](session_2026_06_07_pr3_options_positions.md) — options_positions 表 + breach_alerts (DTE<7/loss>50%) + 前端表
- [2026-06-07 PR2 max_drawdown peak DD](session_2026_06_07_pr2_max_drawdown.md) — peak DD 接 PortfolioRisk + drawdown_pct 阈值 + 前端展示; 236/236
- [2026-06-07 PR1 portfolio_history 基建](session_2026_06_07_pr1_portfolio_history.md) — portfolio_history 表 + UPSERT + 7 case; 227/227
- [2026-06-06 zhuang 风控对齐 equity](session_2026_06_06_zhuang_risk_parity.md) — 持仓表加 entry/current/stop/tp; banner; verify_dualwrite sync pop
- [2026-06-05 dashboard one-click + 止盈视图](session_2026_06_05_dashboard_oneclick.md) — POST /api/daily/run 一键 + take_profit 接持仓表 + MA60 移除前端
- [2026-06-04 实盘风控 v1 audit](session_2026_06_04_realtime_risk_v1.md) — 见上风控区
- [2026-06-01 收工 + backlog handoff](session_2026_06_01_handoff.md) ⭐ — 15 证伪 + 五层 efficient set; 下个 alpha 通道仅剩 C ensemble / 新数据源 / 真做空 / 实盘 KPI

### 2026-05 (frontier 探索)
- [2026-05-31 收工 + backlog](session_2026_05_31_handoff.md) — 已被 06-01 supersede 历史归档
- [2026-05-28 组合层 >> 单策略迭代方法论](session_2026_05_28.md) — L9-A + P1 grid 1.86→2.22 + P2 capacity + P3 baseline
- [2026-05-27 HK bug + US yfinance + launchd TCC](session_2026_05_27.md) — HK daily 参数 bug + yfinance 接入 + SP500 universe + launchd TCC 阻塞
- [2026-05-25 Phase 1 完成](session_2026_05_25_phase1_complete.md) — A/B/C/D + 12-cell 矩阵 + 前后端解耦

## ❌ 反例 / 证伪 (历史 reference, 不再尝试)

(也分散在上述各区, 此处汇总便于 cross-check 17 条 falsified manifest)

- [反向情绪/capitulation 4 重证伪 2026-06](capitulation_strategy_falsified_2026-06.md) — 用户 14% 是盘中 execution alpha 不可系统化; 第 16 条 + paradox 第 5 类
- A_mr v2 4 路径 / 17 条证伪 manifest 全列见 [scripts/research/learn_from_trades.py](#) FALSIFIED_PATTERNS

## 📝 Project meta / 实盘 case / 协作风格

- [实盘入场诊断 + zhuang 闭环 2026-05](project_live_entry_diagnosis_2026-05.md) — "持仓都在亏"四步; entry_score=0 已查清 (非 bug); 真问题=只上 A_mom 腿, 已补 zhuang 闭环
- [Feedback — Harness-first + PR 拆分](feedback_harness_first_pr_split.md) ⭐ — 改动前先 spec / 独立 PR / 禁止流式 commit
- [Feedback — 用户协作风格](feedback_user_collab_style.md) — yaml/实盘改动前 AskUserQuestion; 双窗口验证; idle 提建议; commit 按逻辑单元
- [Feedback — 视觉异常先截图](feedback_screenshot_first.md) — "弹了个东西/漂位/颜色异常"先 AskUserQuestion 截图不瞎猜
- [Feedback — venv 命名 (必须 venv/)](feedback_venv_naming.md) — .venv/ 撞 macOS UF_HIDDEN + Python 3.14 site.py 让 .pth 全失效
