# Memory Index

- [quant_system project overview](project_quant_system.md) — Repo structure, key modules, scripts, and design principles for the Chinese A-share & HK quant trading system
- [quant_system M0–M终 milestones and audit standards](project_quant_milestones.md) — Mandatory M-node definitions, M0 artifact contracts, universal audit checklist, anti-patterns, and key commands; apply to every code change in this repo
- [A 股中线策略优化计划](strategy_optimization_plan.md) — 2026-05 周计划：3 级优先级任务、回测对照表、当前进度；每次会话开始必读
- [HK 策略 2026-05 优化记录](hk_optimization_2026-05.md) — v1→v10 迭代结果、关键洞察（HK 价值因子反 alpha、on-regime hedge 优于熊市对冲）、未完成方向
- [A 股从 HK 移植实验（E 阶段）](a_share_e_transfer_2026-05.md) — L1/L2 不可移植（市场结构 + 数据现实差异），L3 hedge 可移植 +0.05 Sharpe，+fcf_yield +0.02
- [双 universe 组合分析 2026-05](multi_universe_2026-05.md) — HK + A 股相关性≈0，50/50 组合 Sharpe 0.85 / DD -7.9%（实施仅需双账户拆分，零引擎改造）
- [三 universe 组合分析 2026-05](three_universe_2026-05.md) — 加被动 QQQ 替代失败的 us_share 主动策略，45/35/20 配比 Sharpe **1.014** / DD -9.1%（突破对冲基金门槛）
- [实盘部署计划 2026-05](deployment_plan_2026-05.md) — 三账户分资金 + QQQ 被动 + 季度再平衡；启动清单、风控阈值、KPI 监控；us_share 已 enabled: false 归档
