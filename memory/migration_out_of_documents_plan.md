---
name: migration-out-of-documents-plan
description: 仓库从 ~/Documents/projects/quant_system 迁至 ~/quant_system 完成 2026-06-14（消除 TCC 阻塞 launchd/cron，daily 自动化恢复）
metadata:
  type: project
---

# 迁移计划：仓库移出 Documents（消除 TCC 调度阻塞）

**执行完成 2026-06-14** ✅ — 8 步全部跑完，TCC 阻塞解除经 launchd kickstart 验证（stderr 空，stdout 完整 daily 流程跑完）。intraday loop 重启 PID 41435，launchd `com.quant.daily` 重 load `last exit=0`，crontab 旧行清除。执行记录段在文件尾部。

**Why**: macOS TCC (Full Disk Access) 拦截 `/bin/bash` 和 `/usr/sbin/cron` 读取 `~/Documents/` 保护目录，导致 launchd 和 crontab 均已配好但无法执行 `run_daily.sh`（日志持续 `Operation not permitted` 自 2026-05-15 起）。intraday loop 因从终端 nohup 起（继承用户 Documents 权限）反而不受影响。

**决定（2026-06-14）**:
- 目标路径: `~/quant_system`
- 调度机制: launchd（单选，crontab 行删除）
- 原路径: 不留 symlink，干净切掉

## 当前基线 (2026-06-14)

| 组件 | 状态 | 备注 |
|---|---|---|
| intraday loop | PID 3483 跑着 | nohup 从终端起，不受 TCC 影响 |
| launchd | loaded 但 TCC 拦截 | `com.quant.daily` 仍 loaded，每天 16:30 报 Operation not permitted |
| crontab | `30 16 * * 1-5 ...run_daily.sh` | 存在但同样被 TCC 卡，logs/cron.log 停在 2026-05-15 |
| API server | 未运行 | port 8000 空闲 |
| vite dev | 未运行 | port 5173 空闲 |

## 执行步骤

### 1. 停所有运行中进程
```bash
kill 3483  # intraday loop (或 pgrep -f intraday_risk_check | xargs kill)
launchctl unload ~/Library/LaunchAgents/com.quant.daily.plist
```

### 2. 物理 mv 仓库
```bash
mv ~/Documents/projects/quant_system ~/quant_system
ls -la ~/quant_system/.git  # 验证
```

### 3. 改 3 个硬编码路径文件
- `CLAUDE.md`: 调度段、绝对路径示例
- `deploy/com.quant.daily.plist`: ProgramArguments / WorkingDirectory / StdOutPath / StdErrPath
- `memory/session_2026_05_27.md`: 补一行迁移记录

### 4. 重建 venv
```bash
cd ~/quant_system
rm -rf venv
python3.14 -m venv venv
venv/bin/pip install -e .[dev]  # 或其他 extras
venv/bin/python -c "import quant_system; print('OK')"
pytest tests/ -q --tb=short 2>&1 | tail -5
```

### 5. 重启 intraday loop
```bash
cd ~/quant_system
nohup venv/bin/python scripts/intraday/intraday_risk_check.py --loop &
pgrep -fl intraday_risk_check
tail -f logs/intraday.log  # 等一个 entry
```

### 6. launchd 重新 load
```bash
cp ~/quant_system/deploy/com.quant.daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.quant.daily.plist
launchctl list | grep quant
```

### 7. 删 crontab 行
```bash
crontab -l | grep -v quant_system | crontab -
crontab -l  # 确认只有行保留
```

### 8. 端到端验证 + commit
```bash
cd ~/quant_system
./deploy/run_daily.sh --no-options  # 完整 daily，看 HTML 生成正常
# 等一个交易日看 launchd 日志:
tail -5 logs/launchd_stderr.log  # 应安静无 Operation not permitted
```
commit: plist + CLAUDE.md + memory 三件套。

## 验证标准
- launchd_stderr.log 安静（无 Operation not permitted）
- intraday.log 持续写入
- report HTML 正常生成
- 旧路径 `~/Documents/projects/quant_system` 不存在
- `git remote -v` 正常（仓库未损坏）

## 执行记录 (2026-06-14)

| Step | 结果 | 备注 |
|---|---|---|
| 1. 停进程 | ✅ | intraday PID 3483 kill; launchd unload |
| 2. mv 仓库 | ✅ | `.git`/`venv`/data 全保留; `git remote -v` origin Tanglaoye-future/quant_system 正常 |
| 3. 改 3 文件 | ✅ | plist 4 处路径; CLAUDE.md Daily 调度段重写; session_2026_05_27.md 追加更新 |
| 4. 重建 venv | ✅ | python3.14 + `pip install -e .[dev,api,db]` + 补 pyarrow; pytest 375/380 pass (5 失败: 4 us_fundamentals pre-existing parquet engine, 1 zhuang market dispatch pre-existing config 漂移与 zhuang 弃用一致) |
| 5. 重启 intraday | ✅ | PID 41435; 日志写入正常 ("not in trading window" — 收盘后预期) |
| 6. launchd reload | ✅ | last exit code 0 (此前 126 = TCC denied) |
| 7. 删 crontab | ✅ | grep 验证无 quant 行 |
| 8. end-to-end | ✅ TCC | launchd kickstart: stderr 空, stdout 完整 daily 流程跑完 (失败计数=3 全 pre-existing: A_mom/A_mr name_map bug + options verify_dualwrite MISMATCH 比对 stale options.json) |

**Pre-existing bug surfaced** (非迁移引入, 独立 commit 修):
- `scripts/daily/daily_equity.py:315` `UnboundLocalError: name_map` — `name_map` 在 line 404 才赋值, T+1 入场锁块在 line 311-316 提前用. commit ea8674e 引入. 修法: T+1 块移到 name_map 之后, 或者在 T+1 块前提前 build name_map.

**HTML 报告**: 自 [[frontend_single_pane_2026-06]] 起 single-pane dashboard 替代 HTML, 无 `strategy_report_2026-06-14.html` 是预期, 不是 regression.

## 后续
- launchd 下个工作日 16:30 自动跑, 看 `logs/launchd_stderr.log` 仍空
- A 股 daily bug 修后, 失败计数应降到 ≤1 (options 待 IBKR/options 当日跑)
