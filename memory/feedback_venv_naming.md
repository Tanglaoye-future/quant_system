---
name: feedback-venv-naming
description: 本仓 Python venv 用 venv/ 不带 dot；但 macOS UF_HIDDEN 即便在非 dot venv 也会让 .pth 失效(2026-05-28 实测)，run_daily.sh 靠 export PYTHONPATH=src 兜底
metadata:
  type: feedback
---

## 规则

新建或重建 Python venv 时**必须**用 `venv/` 不能用 `.venv/`：

```bash
python3 -m venv venv          # ✅
# python3 -m venv .venv       # ❌ 会导致 editable install 完全失效
```

`.gitignore` 已列 `venv/`；scripts/serve_api.sh、deploy/run_daily.sh、README.md、所有 backtest 脚本统一引用 `venv/bin/python`。

## Why

macOS 对所有 dot-prefixed 文件/目录（`.git` / `.claude` / `.venv`）自动设 BSD `UF_HIDDEN` flag，flag 会被新建文件继承。

Python 3.14 起 `site.py addpackage()` 严格按 `UF_HIDDEN` 跳过 `.pth` 文件 ——> 整个 `.venv/lib/.../site-packages/` 下所有 `__editable__.<name>.pth` 都被 skip ——> `pip install -e .` 完全不生效，`import quant_system` 报 ModuleNotFoundError。

`chflags -R nohidden .venv` 只是临时；Finder/Spotlight 扫描会再次设回，因为目录名仍是 dot 开头。**真正修复就是不用 dot 前缀。**

无关诊断假设（已排除）：
- 不是 iCloud Drive（`brctl status` 否定）
- 不是 setuptools 主动设的（`touch` 普通文件也会继承 hidden）
- 不是 `__editable__` 文件名（用 `quant_system.pth` 也一样）
- 不是 Claude Code Write 工具沙箱（独立验证）

## How to apply

- 任何文档 / 脚本 / 自动化里**禁止**写 `.venv`；写 `venv`
- 人为 `python3 -m venv .venv` 导致的 import 失败：直接 `rm -rf .venv && python3 -m venv venv` 重建（不要 workaround）

### 2026-05-28 修正：非 dot 的 `venv/` 也会中招

实测发现即使用 `venv/`（非 dot），`venv/lib/python3.14/site-packages/__editable__.quant_system-0.2.0.pth`
**仍被打了 UF_HIDDEN flag**（文件名也不带 dot）—— "非 dot venv 就能根治" 的结论不成立，机制比"dot 前缀继承"更复杂。
当天 `./deploy/run_daily.sh` 跑 daily 时 zhuang + report builder 全 `ModuleNotFoundError: quant_system`，而 daily_equity.py 因自带 `sys.path.insert` 不受影响。

- run_daily.sh 原有的 `chflags -R nohidden site-packages` 兜底**不可靠**：经 TCC（Full Disk Access）路径调用时会被静默阻塞（`2>/dev/null || true` 吞掉错误）。
- **可靠兜底 = `export PYTHONPATH="$REPO_ROOT/src"`**（已加进 run_daily.sh），彻底不依赖 .pth。这是自动化脚本的正解；之前"禁止 PYTHONPATH workaround"的前提（venv/ 命名即根治）已被证伪。
- 手动重建 venv 无用（已经是 venv/）；手动 `chflags -R nohidden venv/lib/.../site-packages` 可临时恢复 import，但会再次被设回。
- IDE（VSCode 等）的 interpreter 设置同样指向 `venv/bin/python`
- sitecustomize.py 方案不可行：Homebrew Python 自带一个 sitecustomize 占用了这个名字，stdlib 优先级高于 venv site-packages
- Python 3.14 site.py 没有 env var 禁用 hidden skip
