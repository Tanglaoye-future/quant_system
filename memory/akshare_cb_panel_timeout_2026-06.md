---
name: akshare-cb-panel-timeout-2026-06
description: 2026-06-16 launchd 触发 daily_cb 时 akshare bond_zh_cov_value_analysis 单 ticker curl_cffi Timeout 141s 拖死整个 944 code panel → daily ⚠ 失败. 教训：长循环远程调用每只必须 per-call retry + 全 Exception 容错, 不能让单 ticker 抛 SystemExit
metadata:
  type: project
---

## 事件

**触发**: 2026-06-16 16:30 launchd 跑 daily_cb.py 第 [2/4] 拉 cb_panel cold 944 只可转债.
**症状**: `curl_cffi.requests.exceptions.Timeout: Failed to perform, curl: (28) Operation timed out after 141738 milliseconds with 13597 bytes received`
**call site**: `loader.load_panel` → `ak.bond_zh_cov_value_analysis(symbol=code)` 在某一 code 上挂.
**后果**: Traceback 一路冒到 `daily_cb.py` SystemExit → launchd 标记 ⚠ 失败 → 整个 panel 没更新 (但因为前一晚手跑过, JSON 还在, 前端不受影响).

## 根因

老版 try/except 只捕获 `(TypeError, KeyError, AttributeError, ValueError)` — 上一轮 [[cb-data-probe-2026-06]] dea817f 修的是 akshare 内部 `pd.DataFrame(data_json["result"]["data"])` NoneType 解析错（920/946 backfill 卡点）.

但**网络层异常** (`curl_cffi.curl.CurlError`, `curl_cffi.requests.exceptions.Timeout`, `ConnectionError`, 远程 500 等) 不在 catch 列表里 → 单 ticker 网络卡 = 整 panel 死.

## 修法 (2026-06-16, 见 loader.py:222-258)

per-code 调用包成 3 attempt:
1. **解析异常** (TypeError/KeyError/AttributeError/ValueError) → 立即 skip, `fail_parse++`, 不重试 (数据形态问题, 重试无用)
2. **网络异常** (catch-all `Exception`) → `time.sleep(1.5*(attempt+1))` 短退避, 重试 2 次, 仍挂 → skip + `fail_net++` + stderr 打 code+异常类型
3. 收尾打 `[cb_panel] missing=N ok=X fail_parse=Y fail_net=Z` 一行 stats, 便于 daily log 复盘

**关键约束**: 不向上抛, 让 `load_panel` 跑完所有 missing → daily_cb 继续走 [3/4] strategy / [4/5] write JSON, 单 ticker 失败仅意味着 active universe 略缩水.

## 教训 (推广到其他 daily 长循环远程调用)

凡是 daily / launchd 触发 + 远程 API + 大循环 (>50 code), 必须遵守:

1. **per-call try/except + retry** — 不要在循环外面一个大 try, 单 call 失败就 break 全局
2. **except 列要分层**: 解析错 (skip) vs 网络错 (retry) — 两类语义不同
3. **catch-all `Exception`** 兜底, 永远不让 akshare 内部漏的异常逃出循环
4. **stats counter** 收尾打印, 便于事后分析 (单纯 fail 计数 vs network vs parse)
5. **不要 sys.exit / raise** 在 loop 内 — daily 是 best-effort, 一只挂了不该拖死整轮

相关已知 akshare HTTP 抽风:
- A_mom universe filter 拉 hs300 daily 也有类似问题 (见 [[2026-06-15 A_mr KeyError]] 的 0/300 cache build 偶发)
- panic dashboard 已对 sector / sentiment 加了 3x retry, 是好榜样

## 当时影响

- 实际 launchd 计数 `失败计数: 0` (CB 是 ⚠ warn 不入 FAIL_COUNT, 设计如此)
- 但 launchd 日志里 CB 这一项是失败的 — PM 看 daily summary 会有疑虑
- 前端 quant_cb.json 没被覆盖, A 股 tab 的 CB advisory card 仍显示前一晚手跑数据
