---
name: feedback-screenshot-first
description: 用户报告"前端弹了什么/位置不对/视觉异常"时，先让贴截图再诊断，不要瞎猜根因
metadata:
  type: feedback
---

# 用户报告视觉问题 → 先让截图再诊断

用户反馈"点按钮弹了个黑框在右上角" → 我直接顺着 macOS subprocess / posix_spawn / LaunchServices / Framework Python 一路猜，加了一堆 `nohup + preexec_fn + setsid` hardening 推上 commit。

用户回"还是有黑框" → 让贴截图 → 截图打开一看，**就是我自己代码 `setShowLog(true)` 自动展开的浮层** + Tailwind `bottom-4` 被父元素 transform 漂位到右上。

整套 macOS 根因猜测全错。

**Why**: 视觉异常的根因往往是前端代码（CSS / state / event），但描述文字易让人 jump to system-layer 的 exotic 解释。截图能在 5 秒内排除 80% 的错猜方向。

**How to apply**:
- 用户报告"弹了个东西 / 位置不对 / 颜色奇怪 / 闪烁 / 卡在哪 / 显示成 XXX" → 立刻 AskUserQuestion 或直接请求截图 / 录屏，**不要先去翻系统层代码**
- 截图到手再 prioritize：
  1. 先看是不是自己代码（grep `setShowLog` / `setOpen` / `useState` 之类的 toggle）
  2. 再看 CSS 定位（Tailwind 类被父元素 transform/filter 覆盖是常见坑）
  3. 最后才查浏览器/OS 层
- 用户提供路径时：`Read` 直接看图（多模态可视化）
- 如果用户描述含"右上角 / 漂位 / 弹层"等关键词，CSS positioning bug 的概率 >> 系统弹窗
- commit / push 前如果只靠文字描述就改了一大堆系统层代码，先停下来要截图

**关联**: [[session_2026_06_05_dashboard_oneclick]] commit `6539240` 是这次教训的修复 commit
