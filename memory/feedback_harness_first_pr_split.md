---
name: feedback-harness-first-pr-split
description: 2026-06-07 起本仓所有非琐碎改动必须先写 harness spec (验收契约) 再动代码，每步独立成 PR，禁止流式 commit 长串直推 main
metadata:
  type: feedback
---

# Harness-first + PR 拆分（2026-06-07 起强制）

用户 2026-06-07 明确："未来整个项目做的时候都必须先定义 harness，然后每一个步骤都分解成 pr 来完成，之前的流式生成将不在被允许"。

## 规则

### 1. Harness 先行（PR0）

任何非琐碎改动（新增字段 / 新表 / 新 endpoint / 新策略 / 风控阈值）开工前必须先写 `docs/specs/<topic>.md`，含：

- **范围声明**：本次改哪个子策略 / 哪个 M 节点 / 哪个层（数据 / 引擎 / 报表 / 前端）
- **JSON schema diff**：报表 / API 字段的增删
- **DB schema diff**：PG / DuckDB 表的增删（含 verify_dualwrite 影响）
- **pytest 集成测试用例名**：先列名（spec 内 placeholder），后续 PR 实现
- **M0 audit 影响**：是否扩 `audit_m0_outputs.py` 检查项
- **手测 step**：dashboard / CLI 走一遍的清单
- **失败模式**：known unknowns、TODO、推迟项
- **PR 拆分表**：PR1..PRn 列表 + 依赖图 + 每个 PR 的入口 / 出口契约

spec.md 是后续所有 PR 的 source of truth，PR review 时要比对 spec。

### 2. 每步独立成 PR

中等粒度：1 PR = 1 后端步骤 + 单测 + memory 更新。前后端要拆 2 个 PR（schema 先稳，再接前端）。

**PR ready 门**：
- 单测 / 集成测试全绿
- 短回测 + M0 audit PASS（如触及 strategy 层）
- verify_dualwrite 一致（如触及 JSON / DB schema）
- 默认 OFF 时与 baseline 字节级一致（新阈值默认 enabled: false）

**禁止**：
- 一次 push 3+ commit 直推 main（06-04 / 06-05 / 06-06 三连均犯）
- 跨 PR 范围（如 PR1 顺手改 PR2 的字段）
- PR 内含 TODO 字样的功能（"先占坑后续完善"）

### 3. 流式生成禁令

不允许：
- 一气推 5 commit 没有中间 review 点
- "顺手修" 一个不相关问题混进同一 commit
- 在 spec.md 没写下来的字段上加代码

合法的例外：
- 纯 typo / 注释 / memory 更新
- spec.md / MEMORY.md 索引本身

**Why**: 06-04 实盘风控 v1 (4 commit) + 06-05 dashboard one-click (5 commit) + 06-06 zhuang risk parity (3 commit) 三连 12 个 commit 全部流式直推 main，缺独立 review 单元、缺中间 revert 点。一旦上线后某 commit 引入回归（如 portfolio_alerts verify 假阳要 06-05 才暴露），git bisect 范围不清晰。

**How to apply**:
- 用户给"持仓改进 / 风控扩展 / 新策略接入"这类需求 → 先 AskUserQuestion 确认 spec 范围，再 Write spec.md（PR0），再开第一个 PR
- "按顺序做完"模式仍生效，但是按 PR-by-PR 推进，每个 PR 完成后等用户 review（除非用户明确 "全部 PR 一气做完"）
- 关联 [[feedback-user-collab-style]] 第 8 条（测试做完再 commit）+ 第 6 条（commit 按逻辑单元）

### 范围之外（仍可流式）

- bug fix 1-line 改动
- memory / docs 更新
- CLI prompt 调整
- 紧急生产事故修复（事后补 spec）

## 关联

- [[feedback-user-collab-style]] — 协作风格基础规则（本条扩展第 6、8 条）
- [[session-2026-06-06-zhuang-risk-parity]] — 最后一次流式生成 session
- [[session-2026-06-04-realtime-risk-v1]] — 06-04 4 commit 直推（本条规约的反面教材）
