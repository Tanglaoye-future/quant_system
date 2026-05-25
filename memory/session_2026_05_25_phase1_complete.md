---
name: session-2026-05-25-phase1-complete
description: 2026-05-25 全天 session — Phase 1 全系列完成（1-A/B/C/D），12-cell 跨市场回测矩阵，前后端动态解耦，大厂规范确立
metadata:
  type: project
---

## 完成内容

### 1-A: options 策略-市场解耦
- options 包按 equity_factor 模板拆 strategies/+markets/
- underlying/vol_proxy/exchange/currency 全部参数化
- QQQ/VXN/SMART/USD 硬编码 → config 字段
- commit `8b2b5cd`, 详见 [[options_decouple_2026-05]]

### 1-B: equity_factor 放开 deployments 多市场
- 取消"一市多策略"装配抛错
- 新增 raw["deployments"][sname][mname] 二维索引
- equity_momentum 同时部署 a/hk/us 三市场 (hk/us disabled)
- commit `494fcf6`, 详见 [[equity_factor_multi_deploy_2026-05]]

### 1-C: zhuang 抽象 markets 层
- ZhuangDataLoader + ZhuangBacktester 加 market 参数
- config/zhuang.yaml 新增 markets 子字典 (a_share + hk_small 占位)
- DuckDB store 用 self.market 替代硬码 "a_share"
- 8 个 sweep scripts 零改动 (默认 market=a_share)
- commit `6e73bc1`, 详见 [[zhuang_market_dispatch_2026-05]]

### 1-D: HK 调研 — 退回先调研
- akshare HK 接口在用户网络不通 (push2.eastmoney.com)
- yfinance HK 可用但缺 turnover + 历史市值 → survivorship-bias
- 结论: 工程投入换不到可信回测结论 → 退
- commit `feb801b`, 详见 [[zhuang_hk_research_2026-05]]

### 12-cell 跨市场回测矩阵
- 6 cell × 2 窗口 = 12 个回测并行 4 worker
- DuckDB read_only 多进程安全 (QUANT_DUCKDB_READ_ONLY=1 env)
- parallel_audit.py driver + cross_market HTML report section
- 完整结果: data/cross_market_audit_logs/_summary.csv
- commit `d82c23e` + `b1322bd`

关键发现:
- equity_momentum cross hk_share 4y Sharpe **0.64** DD **-6.0%** (transferability 有数据支撑)
- equity HK 原生 4y Sharpe **1.08** (最佳单 cell)
- zhuang 4y Sharpe **1.47** DD **-2.4%** (最稳)
- US 全败 (NASDAQ100 MAG7 集中市, 等权因子无效)

### 前后端动态解耦 — registry 驱动的策略-市场矩阵
- new: `report/registry/` (domain + resolver)
- new: `config/cells.yaml` (UNSUPPORTED/BLOCKED 声明)
- API: /api/matrix 动态输出 14 cell, /api/markets 改用 registry
- 前端: TabNav/SystemStatusBar/DashboardPage 全数据驱动
- 新组件: CellStatusBadge, StrategyCard, MarketSection
- 14 cells: A 股 4, 港股 5, 美股 5
- commit `1142d6d`

## 确立的代码规范

大厂标准核心原则，后续开发遵循:

1. **低耦合高内聚**: 领域模型 (domain.py) 与编排逻辑 (resolver.py) 分离；API 层只消费 registry，不直接读 config
2. **不可变数据**: frozen dataclass 作领域对象，纯函数式 resolver (无副作用)
3. **渐进迁移不硬切**: 旧端点保留格式兼容，前端 matrix 优先 + 旧组件回退
4. **声明式配置**: cells.yaml 替代硬编码 Python 常量；加新 cell 不改代码
5. **YAGNI**: 不提前抽象 (registry 是单文件 resolver 而非 5 模块微服务)；不做 base 继承
6. **双窗口验证才落 yaml** (延续 [[feedback_user_collab_style]] 第 3 条)
7. **Commit 按逻辑单元打包** (延续 [[feedback_user_collab_style]] 第 5 条)
8. **异步等待不轮询** (延续 [[feedback_user_collab_style]] 第 1 条)

## 待办

- Phase 1-E: options HSI 双部署 — blocked on IBKR 港股期权权限确认
- zhuang HK 数据 — 等用户网络打通 eastmoney + 历史市值数据源
- 9-cell 完整矩阵需持续维护 (加新策略/市场时更新 cells.yaml)

## 验证记录

- pytest 104/104 通过
- TypeScript npx tsc --noEmit 零错误
- 12-cell 回测全完成, _summary.csv 已落地
- 前端 localhost:5173 动态渲染, API /api/matrix 200 OK

**Why:** 这是策略-市场解耦从设计到落地的完整 session，确立了项目后续迭代的技术标准和代码规范.
**How to apply:** 后续开发参考 registry 模式添加新策略-市场组合；遇类似问题参考 1-D 的调研方法论 (数据源可行性扫描 → 退回或接入).
