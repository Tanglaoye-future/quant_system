---
name: equity-factor-l9-partial-regime-2026-05
description: 2026-05-27 equity_factor L9-A regime-aware partial_exit sweep — 4y winner ma200 Sharpe 0.844 (vs base 0.659)，8y ma200 Sharpe 0.363 vs base 0.277 同向但未到 ≥0.5 阈；落 yaml 决策待用户裁定
metadata:
  type: project
---

## 起点

L8D2 (fcf=0) 落地后状态：
- 4y Sharpe 0.675、8y Sharpe 0.195 / DD -19.5%（[[equity_factor_l8_2026-05]]）
- 最新 cross_market 12-cell 8y Sharpe 0.28 / 收益 +42.81% / 平均持有 12.3 天

诊断假设：partial_exit (TP 触发卖 50% + 余仓切松 trail) 在牛市段过早锁利，吃不到趋势。

## L9-A 改造（regime-aware partial_exit）

**思路**：基准指数 (HS300) 收盘 > MA(N) 时（"牛市"）跳过 partial_exit，TP 触发改走**全平**吃趋势；基准 <= MA(N) 时保留 partial 锁利原行为。

**代码改动**（已 commit pending — 工作区目前有 modified files 未提交）：
- `src/quant_system/strategies/equity_factor/timing/signals.py:107-108` — TimingConfig 加 `partial_exit_regime_filter: bool = False` + `partial_exit_regime_ma_days: int = 200`
- `signals.py:680-705` — `exit_step()` 多一个 `regime_above_ma` 入参；启用且 True 时 TP 命中走全平，禁用 / None 退化原 partial
- `engine/strategy.py:261-266` — 仅 `partial_exit_enabled + partial_exit_regime_filter` 同开时计算 MA
- `engine/strategy.py:402` — 按 asof 计算 regime_above_ma 传给 exit_step
- `scripts/backtest/run_l9_partial_regime_sweep.py` — 新 sweep 脚本，subprocess pool + QUANT_DUCKDB_READ_ONLY=1
- `tests/equity_factor/test_l9_partial_exit_regime.py` — 新单测

**新 yaml 配置开关**（落地时加到 `config/strategies/equity_momentum.yaml` timing 节）：
```yaml
partial_exit_regime_filter: true    # L9-A
partial_exit_regime_ma_days: 200
```
当前 yaml 未含这两行（默认 False，即 baseline）。

## 4y sweep 结果（2022-01-01 → 2026-05-25）

```
标签              Sharpe  年化     收益     DD      胜率    笔数
L9-A-ma200 ⭐    0.844   +11.2%   +56.4%   -12.8%  44.3%   370
L9-A-ma120       0.779   +10.5%   +52.2%   -12.9%  42.7%   363
L9-A-baseline    0.659   +8.9%    +43.3%   -13.6%  50.7%   414
L9-A-ma60        0.579   +7.9%    +37.5%   -13.1%  42.5%   346
```

**单调性符合预期**：ma200 > ma120 > baseline > ma60。ma 越长 = "牛市"判定越保守 = 过滤越纯。ma60 误把短期反弹也当牛市，反而比 baseline 差。

**胜率换 Sharpe trade-off**：ma200 胜率 44.3% 比 baseline 50.7% 低 -6pp，但单笔盈利更高 → Sharpe + 收益双升。这是 partial-skip 设计的预期副作用（少锁利 = 单笔回吐风险）。

## 8y 验证（2018-01-01 → 2026-05-25，每 case 挂钟 ~111 min）

| 标签 | Sharpe | 年化 | 收益 | DD | 胜率 | 笔数 |
|---|---|---|---|---|---|---|
| L9-A-baseline | +0.277 | +4.46% | +42.2% | -19.54% | 50.5% | 709 |
| L9-A-ma200 | **+0.363** | +5.41% | +52.9% | **-18.15%** | 43.2% | 630 |

**Δ**: Sharpe +0.086、收益 +10.7pp、DD 优 +1.4pp、胜率 -7pp（与 4y 同向 trade-off）。

## 落地决策（待用户裁定）

- 用户预设阈值是"8y Sharpe ≥0.5"，**0.363 未达**
- 但 4y/8y 双窗口 Sharpe / 收益 / DD 三项**同向**改进，方向稳健，胜率换 Sharpe 的 trade-off 一致
- 与 [[equity_factor_l8_2026-05]] L8D2 落地（8y +0.132，DD 恶化 2.7pp 仍落地）模板对比：本轮 8y Sharpe +0.086 略低于 L8D2 +0.132，但 DD **改善**而非恶化 → 综合 trade-off 更优
- **保守建议**：落 `partial_exit_regime_filter: true + partial_exit_regime_ma_days: 200`，但用户严格执行 ≥0.5 阈则不落

具体决策权在用户手上（[[feedback_user_collab_style.md]]：yaml 改动前 AskUserQuestion）。

## 工程踩坑（必记）

### 1. macOS 沙箱 0/300 cache 假失败

跑 8y sweep 时多次收到"完成"通知但结果是秒级失败 — 是子进程在 Claude Code 受限沙箱（非 all 权限）下读 `data/` 时 universe 拿到 0/300，全程没数据。表现：log 里 `prefetch 0/300`、`elapsed=0.5s`、Sharpe=0 或 NaN。

**Why**：默认沙箱对 `data/`（特别 DuckDB 文件）有读写隔离；子进程继承 env 但 TCC + sandbox 联合可能让 read_only 也失败。

**How to apply**：
- 长任务（回测 / sweep / prefetch）一律在用户本机终端跑，不要通过 agent 沙箱起子进程
- 或：让用户切到 all 权限模式（用户 2026-05-27 已采纳，详见 [[feedback_user_collab_style.md]] 更新点）
- 任何"超快完成"（实际预计 >1 min 的回测在几秒就结束）一律先验 log 里 `prefetch X/300` 数字是否正常，再信指标

### 2. 子进程 PYTHONPATH=src 显式注入

[[feedback_venv_naming.md]] 现象的延续：即便 venv/ 不带 dot，长生命周期下 macOS UF_HIDDEN 还是会反复让 site-packages 的 .pth 失效。修法：

- daily 入口 `deploy/run_daily.sh` 已自动 `chflags -R nohidden venv/lib/python3.14/site-packages/`（[[session_2026_05_27]] commit 793beb5）
- 子进程 sweep 脚本里**也要**显式设 `env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + ...`，详见 `scripts/backtest/run_l9_partial_regime_sweep.py:161`
- 否则 ProcessPoolExecutor fork 的子进程会随机 ModuleNotFoundError

### 3. DuckDB 并发读

`QUANT_DUCKDB_READ_ONLY=1` 子进程 env 必加，否则 4-worker 并行会出现 write lock 抢占。

### 4. 用 ThreadPoolExecutor + subprocess 而非 ProcessPoolExecutor

macOS sandbox 下 ProcessPoolExecutor 直接 fork 会撞 spawn 限制；改成 ThreadPoolExecutor 提交 subprocess.run 更稳。每个子任务独立 log 文件方便事后看数据加载是否正常。

## 后续指南

- **如果用户决定落 yaml**：改 `config/strategies/equity_momentum.yaml` timing 节加两行；跑 4y 短回测验证 yaml 解析无问题；commit 单独打包"L9-A-ma200 落地"逻辑单元
- **如果用户不落**：保留代码 + 单测在仓内（功能成型只是 yaml 默认 False），将来想试随时改 yaml 即可
- **下一轮探索方向**（用户未指）：partial_exit_pct / partial_exit_trail_mult 与 regime_filter 联动 sweep；或 m5_regime_exit 阈值在牛市段也跳过

## 不要做

- 不要因为 8y 未到 ≥0.5 就直接给 FAIL 结论 — 用户的阈值是参考非硬性，需让用户自己看 trade-off
- 不要把 ma60 当 "敏感版" 推荐 — 4y 已证明它误把噪音当趋势，比 baseline 还差
- 不要在没明确指令前提下擅自改 `equity_momentum.yaml`（[[feedback_user_collab_style.md]]）

**Why:** L9-A 是 L8 因子层探索完后转向出场策略层 regime-aware 改造的第一步；本轮严格 4y → 8y 双窗口，但 8y 边际改善小于 L8D2，是否落 yaml 边缘。
**How to apply:** 下次类似 timing 层 sweep（partial / collar / trail / regime_exit 阈值），复制本轮模板：(1) 改动 + 单测，(2) sweep 脚本带 subprocess pool + PYTHONPATH + DuckDB read_only，(3) 必须本机终端或 all 权限模式跑 long task，(4) 4y winner → 8y 同向才论是否落。
