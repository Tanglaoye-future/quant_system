---
name: frontend-single-pane-2026-06
description: Phase 3 前端消弭 HTML 报告孤岛，全量数据接入 React dashboard
metadata:
  type: project
---

前端 dashboard 是后端所有结果的唯一查看入口。后端不再生成独立 HTML 报告。

**Why:** 用户要求消除后端数据报告孤岛，所有结果/信息映射到前端 dashboard，以后只通过前端查看。

**How to apply:** 后续任何新增数据产出（如 KPI、新的 scan 结果）必须：
1. 写到 `report/data/<name>.json`
2. 在 `routes.py` 加 `/api/report/<name>` 端点
3. 在前端加 TypeScript 类型 + API client + 组件渲染
4. 绝不再写 standalone HTML 文件

## 变更清单

- `src/quant_system/report/api/routes.py` — 新增 `GET /api/report/panic`
- `frontend/src/types/index.ts` — PanicData + 9 个子类型
- `frontend/src/api/client.ts` — `getPanic()`
- `frontend/src/pages/PanicSection.tsx` — 新建，8 子区块
- `frontend/src/pages/DashboardPage.tsx` — Panic tab
- `frontend/src/hooks/useReportData.ts` — panicData fetch
- `frontend/src/App.tsx` — 传递 panicData
- `src/quant_system/report/builder.py` — `rebuild_html_report()` → no-op
- `deploy/run_daily.sh` — 移除 HTML builder 步骤
- `scripts/reporting/daily_panic_dashboard.py` — 不再输出 HTML
