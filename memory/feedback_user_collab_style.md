---
name: feedback-user-collab-style
description: 本仓 user 的协作节奏偏好 — "按顺序做完" 自主推进、yaml/实盘改动前 AskUserQuestion、idle 时可主动提建议、commit 按逻辑单元打包
metadata:
  type: feedback
---

## 1. "按顺序做完" 模式

用户给出多步任务后说 "按顺序把任务做完" / "继续完成任务"，期望我：

- 用 TaskCreate 列出 task 并自主推进，不每步都问
- 遇到 blocker（pth import 失败等）自主诊断 + 修复，不打断用户
- 异步等待时（长 backtest 等）告知预计时长后等通知，不轮询
- 全部完成后简洁汇报（表格 + 几行小结），不堆解释

**Why**: 用户在我处理过程中通常在做别的事，不希望被频繁确认打断。
**How to apply**: 看到"按顺序"/"继续"/"完成下去"这类指令，默认走自主推进路径；只在改动实盘配置或不可逆操作前用 AskUserQuestion 卡一下。

## 2. 实盘 / yaml 配置改动前必须问

`config/strategies/*.yaml` 是实盘配置（季度再平衡 5-asset 组合，见 [[deployment_plan_2026-05]]）。改 weights / timing 参数前必须用 AskUserQuestion 给出 2-3 个选项让用户选。

**Why**: yaml 数字直接影响实盘交易，不可逆程度高；用户保留最终决定权。
**How to apply**: 即使数据上"赢家"很明确（如 L8D2 4y/8y 双窗口都赢），仍要列出 trade-off（DD 恶化等）让用户拍板；不要替他做决定。

## 3. 双窗口验证才落 yaml

任何因子 / timing 改动要先 4y (2022-2026) sweep 找 winner，再 8y (2018-2026) verify，**两个窗口同向才落地**。

**Why**: L7-C3 形成的规律 + L8 沿用，单 4y 窗口可能选偏（如 L8-base 4y 0.579 vs 8y 0.063 差异巨大说明 4y 不够代表性）。
**How to apply**: 出 4y winner 后立即跑 8y verify (~80 min/case)；不要因"4y 太香"就直接落，必等 8y 印证。

## 4. Idle 期间可主动提建议

异步等待（长 backtest 等）时，主动列出"可并行的事"让用户选。本会话例子：

- 8y verify 跑时，问了"要不要 a) 永久修 pth b) 截图 zhuang 候选 c) 跑 unit test"
- 用户选 c → 接着主动建议补直接覆盖 publication_lag 的 unit test

**Why**: 用户接受这种"既然在等不如顺手做点"的提议，节省整体周期。
**How to apply**: idle 时主动列 2-3 个相关候选（不要太多），用户拒绝就继续等。不要静默 sleep 浪费机会。

## 5. Commit 按逻辑单元打包，不按文件

一次 commit 含完整逻辑单元（实验脚本 + unit test + yaml 改动 + memory + index）。本会话两次成功示范：

- `9aa2897`: L8 实验 = 3 个 sweep 脚本 + 8 个 unit test + yaml + memory + MEMORY.md 索引
- `800685d`: venv 重命名 = 10 处文件引用 + memory + index，一次性

**Why**: 用户期望 git log 可读，每个 commit 是一个可独立 revert 的语义单元。
**How to apply**: 不要"先 commit 一部分占坑再 commit 后续"；等所有相关改动到位（包含 memory）后一次提交。commit message 用 HEREDOC 含背景+决策+验证清单（如 4y/8y 数据、test 通过数）。
