# Claude 对话存档 | 2026-04-29 | 回测引擎完工 + M1 全市场扩展

**项目**: `quant_system` — A股中线量化交易系统  
**日期**: 2026-04-29  
**会话时长**: 约 5 小时（含后台任务监控）  
**终端 PID**: 11728 | **工作目录**: `C:\Users\Lenovo\projects\quant_system`

---

## 一、会话核心目标

搭建 A 股中线量化交易系统回测引擎，验证 `bottomup_timing` 策略，并扩展选股池到全 A 市场（M1 阶段）。

---

## 二、完成事项

### 2.1 预 enrich cache 优化（20× 加速）

**问题**: 每天对每只股票重复 enrich，580 天 × 300 只 = 17.4 万次重算，单次 screen 780s。  
**方案**: `_build_enriched_cache()` 一次性预热所有 universe 股票，`screen()` / `evaluate()` 复用 cache。  
**结果**: 单次 screen 从 15s → 0.77s（20 倍加速），全段 2 年回测约 25 分钟。

**关键代码变更** (`bottomup_timing.py`):
- 新增 `_enriched: dict[str, object]` + `_cache_built: bool`
- 新增 `_build_enriched_cache()` 方法，预热时打印 `50/300 → 完成`
- `screen()` 和 `evaluate()` 开头调用 `self._build_enriched_cache()`
- 替换 `scan_today_entries` 为直接查 `self._enriched` + `entry_signal_from_enriched`
- 替换 `trailing_stop` / `exit_signal` 为 `trailing_stop_from_enriched` / `exit_signal_from_enriched`

---

### 2.2 第一次全段回测（虚高，后发现 Bug）

**配置**: `bottomup_timing` | 2024-04-01 → 2026-04-27 | 501 交易日 | HS300 (300 只)

| 指标 | 数值（Bug 前虚高） |
|------|----------------|
| 总收益 | **+76.09%** ← 虚高 |
| 年化收益 | +32.92% |
| Sharpe | +0.83 |
| 最大回撤 | -23.98% |
| 胜率 | 41.14% (350 笔) |
| 平均盈利 | +10.82% |
| 平均亏损 | -6.13% |
| 盈亏比 | 1:1.76 |
| HS300 同期 | +32.69% |
| 超额收益 | +43.40% |
| 准入判定 | PASS |

**发现异常**: 第 70 天净值从 988k 跳到 1,464k（5 天 +48%），触发深查。

---

### 2.3 回测 Bug 发现与修复

**根本原因**: `pending_sells` 累积重复 position。  
某只持仓触发 EXIT 信号后留在卖出队列等次日开盘，但当日 `evaluate()` 再次评估并 append 一次，多次卖出同 1 份持仓导致 cash 虚增。

**修复** (`quant_system/engine/backtest.py`):

```python
# Step 1: 卖出前防双扣
for pos, reason in pending_sells:
    # 防御: 该 symbol 可能已被前一笔 pending_sells 卖掉, 跳过
    if pos.symbol not in positions:
        continue
    ...

# Step 3: 评估前过滤已在队列的
already_pending = {p.symbol for p, _ in pending_sells}
for sym, pos in list(positions.items()):
    if pos.entry_date == day_dt:
        continue
    if sym in already_pending:
        continue   # 已在卖出队列, 不重复评估/append
    ...
```

---

### 2.4 真实回测结果（Bug 修后）

**配置**: `bottomup_timing` | 2024-04-01 → 2026-04-27 | 501 交易日 | HS300

| 指标 | Bug 前（虚高） | Bug 后（真实） | 变化 |
|------|-----------|-----------|------|
| 总收益 | +76.09% | **+43.56%** | -32.5% |
| 年化收益 | +32.92% | **+19.95%** | -13.0% |
| Sharpe | +0.83 | **+0.83** | 持平 |
| 最大回撤 | -23.98% | **-19.73%** | 改善 4.25% |
| 胜率 | 41.14% | **42.86%** (336 笔) | 改善 1.7% |
| 平均盈利 | +10.82% | **+11.24%** | 改善 |
| 平均亏损 | -6.13% | **-5.83%** | 改善 |
| 盈亏比 | 1:1.76 | **1:1.93** | 改善 |
| 超额收益 | +43.40% | **+10.87%** | -32.5% |
| 准入判定 | PASS | **PASS** | — |

**期间修复的所有 Bug**:

| Bug | 影响 | 状态 |
|-----|------|------|
| `cache_min <= "2018-01-01"` 永远 False | 每次重拉数据，screen 780s→15s | ✅ 修 |
| `dict.get(default=...)` 关键字错误 | 报告生成崩溃 | ✅ 修 |
| 末日强制平仓跳过 `bar=None` 的 position | 净值 -99% 假数字 | ✅ 修 |
| `pending_sells` 累积重复 position | cash 双扣，收益虚增 32% | ✅ 修 |

---

### 2.5 用户需求升级

**用户不满意当前指标**，提出：
- 胜率至少 55%（当前 42.86%，差 12 个点）
- 盈亏比至少 3:1（当前 1.93，差 1.07）
- 选股池扩到 **A+H 全市场**（当前偷懒只用 HS300）

**Claude 规划 M1-M5 五阶段**:

| 阶段 | 内容 | 预期收益 |
|------|------|--------|
| M1 | A+H 全市场接入 | 胜率 +3-5%，盈亏比 +0.3-0.5 |
| M2 | 港股全市场接入 | 进一步补充 alpha |
| M3 | 入场信号收紧（催化剂/形态/黑名单） | 胜率 +6-10% |
| M4 | 止盈策略大改（trailing 分级，取消硬止盈） | 盈亏比 +0.7-1.2 |
| M5 | 资金管理优化（Kelly/行业暴露上限） | 回撤 -3-5%，Sharpe +0.1-0.2 |

---

### 2.6 M1 执行：全 A 市场数据预热

**代码变更**:

1. **`quant_system/data/loader.py`** — 新增 `a_all` universe 分支:
   ```python
   elif name == "a_all":
       df = ak.stock_info_a_code_name()
       df = df[~df["name"].str.contains("ST", na=False)]
       df = df[~df["code"].str.startswith("9")]
       df = df[["code", "name"]].reset_index(drop=True)
   ```
   同时修复 hs300/zz500/zz1000 的 rename columns bug（之前少了这行）。

2. **`config.yaml`** — 改为:
   ```yaml
   universe: a_all   # 原来 hs300
   ```

3. **`scripts/prefetch_a_universe.py`** — 新建 76 行脚本，单线程顺序拉全 A daily cache，实时写 `data/prefetch_progress.txt`，失败记录到 `data/prefetch_failed.txt`。

**prefetch 执行结果**（截至会话结束）:
- Universe: 4996 只（5511 - ST - B股）
- 已完成: ~3550 只（76%）
- 失败: 221 只（4.7%，集中在 6xx 段退市代码）
- ETA 剩余: 约 45 分钟
- prefetch 进程在后台继续运行

**multiprocessing 并发测试失败原因**: `py_mini_racer`（akshare 内部 JS 引擎）非线程安全，多进程 `mp.Pool` + `python -c` 在 Windows + Python 3.14 不兼容，直接采用单线程方案。

---

## 三、当前系统架构

```
quant_system/
├── config.yaml              # universe: a_all（已改）
├── scripts/
│   ├── backtest.py          # 回测主入口
│   ├── daily_run.py         # 盘后实盘推荐（在 quant_system/ 下，不在 FinceptTerminal/）
│   └── prefetch_a_universe.py  # 新建：全 A 数据预热
├── quant_system/
│   ├── data/loader.py       # 支持 hs300/zz500/zz1000/a_all universe
│   ├── engine/backtest.py   # T+1 回测引擎（Bug 已修）
│   └── strategies/bottomup_timing.py  # 预 enrich cache 优化后版本
└── data/
    ├── cache/               # daily price cache（已有 3422+ 只）
    ├── prefetch_progress.txt  # prefetch 实时进度
    └── prefetch_failed.txt  # prefetch 失败列表
```

---

## 四、未完成 / 下一步

1. **等 prefetch 完成**（还差约 45 分钟，后台已启动）
   - 完成后运行: `python scripts/backtest.py --start 2024-04-01 --end 2026-04-27`
   - 对比全 A 市场 vs HS300 的胜率/盈亏比提升

2. **处理 221 只 prefetch 失败**（均为退市股，基本可忽略）
   - 查看 `data/prefetch_failed.txt` 确认

3. **M2-M5 待执行**（先看 M1 效果再决定是否继续）

---

## 五、实盘使用

```bash
# 进入正确目录（注意不是 FinceptTerminal!）
cd C:\Users\Lenovo\projects\quant_system

# 每天盘后运行
python scripts/daily_run.py
```

---

## 六、注意事项

- `bottomup_timing` 真实年化 ~20%，超额 +11%（非虚高的 +32%）
- 最大回撤可能 -20%，上实盘要有心理准备
- 港股池（H 股）尚未接入，属于 M2 阶段
- prefetch 脚本不能同时开两个（会冲突），检查 `prefetch_progress.txt` 确认状态
