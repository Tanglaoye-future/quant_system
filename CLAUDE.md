# quant_system — Claude Code 项目规则

## Session 启动

**每次会话开始时，自动读取 `memory/` 下所有文件。** 这些文件是跟随 repo 的持久记忆，包含项目概览和 M0–M终里程碑审计标准，是强制性的，不可跳过。

## 开发规范

### 改代码前

1. 将用户需求映射到对应 **M 节点**（M0/M1/M2/M3/M4/M5/M终）
2. 打开相关模块 + `config.yaml`，理解现有实现后再修改

### 改代码后（每次必须执行）

```powershell
# 1. 单元测试
powershell -File scripts/run_acceptance.ps1

# 2. 短回测验收
python scripts/backtest.py --start 2026-01-01 --end 2026-02-28 --refresh-days 999

# 3. M0 产物审计
python scripts/audit_m0_outputs.py data/backtest/<strategy>_<market>_<start>_<end>
```

所有门控必须通过，才算完成。

### 回复格式

每次完成代码变更后，说明：
- 触达哪个 M 节点
- 运行了哪些验收命令
- 输出目录在哪里

## 记忆文件

记忆保存在 `memory/`，随 repo 一起提交和同步：

| 文件 | 内容 |
|------|------|
| `memory/project_quant_system.md` | 项目结构、模块职责、关键脚本 |
| `memory/project_quant_milestones.md` | M0–M终定义、审计清单、反模式、命令速查 |
