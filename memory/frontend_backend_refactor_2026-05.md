---
name: frontend-backend-refactor-2026-05
description: 2026-05-22 将报告系统从 Python 静态 HTML 改造为 FastAPI + React 前后端分离 + Apple 风格设计 + 自动开平仓闭环
type: project
---

## 改造动机

原报告系统是 `builder.py` 生成单一静态 HTML，暗色交易终端风格，用户反馈"太丑"。要求：
1. Apple 官网风格（明亮、毛玻璃、SF 字体、大圆角）
2. 真正的前后端分离应用

## 架构

```
[Daily Scripts] ──write──> [report/data/*.json] ──read──> [FastAPI :8000] ──REST──> [React/Vite :5173]
    (不改动)                  (数据源不变)              (新增)                 (新增)
```

Daily 脚本继续写 JSON 不动。后端纯读取层，前端通过 Vite proxy 代理 `/api` → `:8000`。

## 关键文件

| 层 | 文件 | 说明 |
|---|---|---|
| 后端入口 | `src/quant_system/report/api/main.py` | FastAPI app + CORS |
| 后端路由 | `src/quant_system/report/api/routes.py` | /api/health, /api/report/quant, options, zhuang, summary |
| 前端入口 | `frontend/src/main.tsx` → `App.tsx` | React 应用入口 |
| 数据获取 | `frontend/src/hooks/useReportData.ts` | fetch /api/report/summary |
| 类型定义 | `frontend/src/types/index.ts` | 9 个 TS 接口，与 JSON schema 对齐 |
| 设计 token | `frontend/src/index.css` | 毛玻璃、配色、字体、动效 |
| 启动脚本 | `scripts/serve_api.sh` | uvicorn 一键启动 |

## Apple 设计系统

- 背景 `#f5f5f7` / 卡片 `rgba(255,255,255,0.72)` + `backdrop-blur(24px)` / 圆角 `1.25rem`
- 字体 `SF Pro Display, -apple-system`
- 强调 Apple Blue `#0071e3` / 正 `#30d158` / 负 `#ff453a`
- TabNav iOS 风格分段控件
- 加载 fadeIn 动画 + 表行 hover 过渡

## 同时落地的自动交易闭环

本轮一并解决了"信号→开仓→持仓监控→平仓"的手动缺口：

1. **自动开仓**: `daily_equity.py` Step 3 买入信号自动录入 journal（`--dry-run` 仅预览）
2. **自动平仓**: `RiskMonitor.daily_check()` 检测到 exit 信号自动调用 `journal.close_trade()`
3. **HTML 串联**: 每个 daily 脚本写 JSON 后自动调 `rebuild_html_report()`

详见 [[equity_factor_l7_2026-05]]、[[deployment_plan_2026-05]]。

## 日常使用

```bash
# 终端 1: API（常驻）
./scripts/serve_api.sh

# 终端 2: 前端（常驻）
cd frontend && npm run dev

# 终端 3: 策略
python scripts/daily/daily_equity.py --market a_share
python scripts/daily/daily_zhuang.py
python scripts/daily/daily_options.py --no-ibkr

# 浏览器 http://localhost:5173
```

## 前端组件

`App → Layout → DashboardPage`
- `SystemStatusBar` (3 张概览卡片)
- `TabNav` (A 股中线 / QQQ 期权 / 庄股小盘)
- `QuantSection` (MetricGrid + DataTable 买入信号 + DataTable 持仓)
- `OptionsSection` (MetricGrid + 信号详情)
- `ZhuangSection` (MetricGrid + DataTable TOP 15)

## 数据流

全部 API 端点返回 JSON，前端 `useReportData` hook 在 mount 时 fetch `/api/report/summary`，手动刷新按钮重新拉取。空 JSON 文件时显示引导文案（"请运行 daily 脚本"）。

**Why:** 用户反馈报告太丑，要求 Apple 风格前后端分离；同时补齐了开平仓自动闭环。
**How to apply:** 启动 API + 前端两个常驻服务，跑策略后浏览器看报告；API 端口 8000，前端端口 5173。
