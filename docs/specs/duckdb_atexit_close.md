# Spec — DuckDB stale-flock 修复：进程退出自动 close

## 背景

实盘 2026-06-08 第二次 daily 运行时 zhuang 挂在：

```
_duckdb.IOException: Could not set lock on file ".../data/quant.duckdb":
Conflicting lock is held in PID 87590
```

PID 87590 = `scripts/daily/daily_zhuang.py`（先前那次崩溃 / 未正常退出的实例）。
重启 zhuang 进程时撞自己留下的 stale flock；杀掉 zombie 后立即 reproduce 干净跑通。

Root cause:
- 进程异常退出 / 被 SIGKILL / Bug A cascade 崩溃 时 **DuckDBStore.close()
  从未被调用**，文件 fd 暂留 → 系统层 flock 残留几秒~几分钟
- 当前代码：`DuckDBStore.close()` 存在 (`duckdb_store.py:77`) 但**没有任何 entry
  script 在 main()/atexit 主动调它**
- `daily_zhuang.py` / `daily_equity.py` / `intraday_risk_check.py` 全是
  loader.get_daily → store._connect()，连 try/finally 都没

## 改动范围（最小）

| 文件 | 改动 |
|---|---|
| `src/quant_system/data/duckdb_store.py` | module-level WeakSet 跟踪所有活实例 + atexit hook 一次性 close 所有活 store |
| `tests/data/test_duckdb_store_atexit.py` | 新增；2 case：(a) atexit close 释放 flock，新 connect 可重入；(b) close() 后再 connect 自动重连不抛 |

## 设计决策

### 用 WeakSet 而非 list
list 会 retain instance 引用 → 即使 caller drop store，进程内还活 → 内存泄漏。
WeakSet 在 instance 没其他引用时自动剔除 → atexit 只 close 真活的。

### atexit 一次性注册（不是每次 store ctor）
module-level 标志 `_atexit_registered` 防重复注册；首次 DuckDBStore() 触发。

### close() 已幂等
`duckdb_store.py:77-81` 已有 `if self._con is not None: ... self._con = None`，
重复 close 安全；atexit 与显式 close 不冲突。

### 不强制走 get_default_store() 单例
zhuang / equity_factor loader 各自 `DuckDBStore(path)` 当前形态保留 —
本 PR 仅加防御不重构调用方。单例化是更深改动，未来若再撞同进程冲突再做。

## 验收

- pytest tests/data/test_duckdb_store_atexit.py 2/2 pass
- pytest tests/ 不回归（基线 282）
- 手动 reproduce：
  1. kill -9 一个正在 connect 的 daily_zhuang.py（模拟 Bug A cascade）
  2. 立即重启 daily_zhuang.py
  3. 期望：第二次跑无 IOException（atexit 在 SIGKILL 不触发 → 本 PR 不解 SIGKILL 场景，但解决普通异常退出 + 正常 Ctrl-C + Python unhandled exception 三类）

## 不做（明文）

- 不改 zhuang / equity_factor loader（保留 `DuckDBStore(path)` 各自 new）
- 不引入 get_default_store() 单例化（更大重构，未来再单独 PR）
- 不解 SIGKILL（atexit 不触发；只能由 OS fd 回收 → 用户操作层）
- 不动 intraday loop（它不用 DuckDB，无需改）
- 不动 daily_zhuang.py 主流程 try/finally（atexit module 级覆盖即够）

## 关联

- [[session_2026_06_07_pr5_intraday_telegram]] — intraday loop 不用 DuckDB 已确认
- [[duckdb_migration_2026-05]] — DuckDB 层架构起源
- 06-05 daily 崩溃链：Bug A (exit_reason VARCHAR(32)) → cascade kill daily_zhuang → DuckDB
  fd 残留 → 06-08 zhuang 启动撞 stale lock
