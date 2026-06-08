# Spec — zhuang 跌穿 stop loss 红色告警（M4）

## 背景

实盘 600584 长电科技 case:
- 2026-06-01 close 75.65 < stop_loss 77.13 — **已跌穿 stop 1.9%**
- 但 zhuang 出场是 advisory (不自动平), daily 输出仅显示 "⚠ 临界"（与 "距 stop +0.8%" 同一警告级别）
- 用户 8 天没注意到 → 6-8 收盘 70.30 = **-14.32% / 跌穿 stop 8.86%**

设计漏洞：`CRITICAL_MARGIN = 0.01` 把"距 < 1%"和"已跌穿 N%"用同一种 ⚠ 标记，
PM 看不出区别 → 工作流 gap。

## 改动范围

| 文件 | 改动 |
|---|---|
| `scripts/daily/daily_zhuang.py` | dist < 0 区分为 `STOP_BREACHED` 状态; 显示 🔴 跌穿 X%; 持仓段头部加 "🔴 N 只已跌穿" banner |
| JSON output | 持仓 dict 加 `stop_breach: bool` 字段 |
| `tests/zhuang/test_stop_breach_alert.py` | 3 case: 跌穿识别 / 健康 vs 临界 vs 跌穿三级状态 / JSON 字段 |

## Backstop 严守

- **#1** 不改 zhuang advisory 出场逻辑 (alpha 路径不动)
- **#2** 不改 yaml 阈值
- **#5** 0 新计算 — 复用现有 dist_to_stop_pct
- pure observability — daily 输出层 + JSON 字段

## 三级告警逻辑

```python
if dist_to_stop_pct is None:
    state = "unknown"
elif dist_to_stop_pct < 0:
    state = "breached"   # 🔴 已跌穿 X% (advisory, 立即手工决策)
elif dist_to_stop_pct < CRITICAL_MARGIN:  # 0.01
    state = "critical"   # ⚠ 临界 (margin < 1%)
else:
    state = "normal"
```

## Markdown 输出对比

### 改前 (600584 6-8)
```
600584  浮盈 -14.32%  止损 77.13 (距 -8.86%)  ...  持有 6 天 ⚠ 临界
⚠ 1/3 只贴近止损 (margin < 1%)
```

### 改后
```
600584  浮盈 -14.32%  止损 77.13 (距 -8.86%)  ...  持有 6 天 🔴 跌穿 8.86%
🔴 1 只已跌穿 stop loss (advisory 不自动平 — 立即手工决策)
⚠ 0 只贴近止损 (margin < 1%)
```

## 验收

- pytest tests/ 不回归 (base 325)
- daily_zhuang 06-08 重跑: 600584 显示 "🔴 跌穿 8.86%" + 头部 banner
- 既有 600655 / 000810 (dist > 0 健康) 输出零变化
- JSON 加 `stop_breach: bool` 字段, dashboard 后续可消费

## 不做（明文）

- 不改 zhuang advisory → auto-close (alpha 改动, 需双窗口验证, 留 backlog)
- 不动 zhuang stop_loss 算法 (静态 ATR-stop)
- 不接入 A_mom (A_mom auto-close 已存在, dist < 0 理论不出现)
- 不接 Telegram 推送 (intraday 已有, 本 PR 仅 daily 输出层)

## 关联

- [[case_2026_06_08_600584_distribution]] — 600584 教训沉淀
- [[session_2026_06_04_realtime_risk_v1]] — 06-04 风控 v1 (CRITICAL_MARGIN 设计来源)
- 06-08 conversation: 用户决定"拿住当教训" → 工作流 gap 必须修
