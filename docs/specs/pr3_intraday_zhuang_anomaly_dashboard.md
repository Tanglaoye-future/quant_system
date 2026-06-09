# PR3 — zhuang 盘中派发预警 + 前端 dashboard auto-poll

**接续** [[pr2_intraday_watchlist_breakout]]。3 PR 中 PR3（收尾）。

## 范围

1. **zhuang 派发预警 `zhuang_distribution_warning` (warning)**：持仓 zhuang 股盘中"今日涨幅高 + 量比放大" → 庄家可能在派发。仅推送提示，不自动平仓。
2. **PositionSnapshot 加 `volume_ratio` + `day_change_pct`**（Optional）：复用 PR2 `fetch_realtime_quote_with_vol_ratio_a_share`，统一一次 spot_em 调用。
3. **fetch_realtime_quote_with_vol_ratio_a_share 扩 `change_pct`**：返回 `{code: {price, vol_ratio, change_pct}}`，持仓 path 也迁移用它（PR1 simple price fetch 弃用但保留以防回滚）。
4. **前端 dashboard auto-poll**：`useReportData` 加 `pollIntervalMs` 默认 60s；`document.visibilityState !== 'visible'` 时暂停。
5. **config/intraday.yaml** 加 `zhuang_distribution:` 节。

**不在范围**：
- 自动平仓 / 自动减仓（Backstop #4）
- 1min/30s polling（默认 60s；网络 / API 限频考虑）
- zhuang sleeve 加新 entry 信号（撞证伪 16 + 17 条 efficient set）
- HK / US 持仓异动（spot_em 仅 A 股；HK 没量比字段）

## 触发条件 (zhuang_distribution_warning)

**全部满足**：
1. `strategy_name in cfg.zhuang_strategies` （默认 `["zhuang"]`）
2. `day_change_pct ≥ zhuang_distribution_change_pct_min`（默认 0.04 = 4%）
3. `volume_ratio ≥ zhuang_distribution_vol_ratio_min`（默认 2.0；缺失保守降级 skip vol filter）

severity: **warning**
message: `🚨 [庄股派发预警] {symbol} 今日 {chg:+.2%} / 量比 {vr:.2f} ｜ 可能进入派发期, 考虑减仓`

## 设计决策

- **Snapshot 复用 PositionSnapshot**：加 Optional 字段 `volume_ratio` / `day_change_pct`；现有持仓 alert 不读这俩，不会破坏既有逻辑。
- **One spot_em call**：从 PR1 的简单 price fetch 切换到 PR2 的 quote fetch（扩字段后）。spot_em 单次拉全市场 ~5000 行 ~1s；持仓 + 候选股共用一次，减一半 API 调用。
- **dedup 沿用 once-per-day**：alerts_sent UNIQUE 不变 → 无 alembic migration。
- **不做"5min 涨幅"**：用户原始描述 "5min 内涨幅 > 2%" 需要维护内存状态（跨 cron 周期）。简化为 "今日累计涨幅" — spot_em '涨跌幅' 字段直接给。物理意义更稳：今日大涨 4% + 放量 = 派发概率高。
- **前端 polling**：默认 60s（balance UX vs 后端负载）；`visibilityState !== 'visible'` 暂停（tab 隐藏不耗电）；window focus 后立即刷新一次。

## 配置 (config/intraday.yaml 新增节)

```yaml
zhuang_distribution:
  enabled: true
  change_pct_min: 0.04          # 今日涨幅下限
  vol_ratio_min: 2.0            # 量比下限
  strategies: ["zhuang"]
```

## 前端 polling 设计

`useReportData` hook 签名扩展：

```ts
useReportData({ pollIntervalMs: 60000 })
```

行为：
- 首次 mount 触发 fetch（与现状一致）
- 在 trading hours visible tab 上每 60s 自动 refetch
- tab 隐藏 → 清理 interval；可见 → 重启 + 立即 fetch 一次
- error 不触发 retry 风暴（用 ref 守 ongoing fetch）

## 验收门

1. `pytest tests/intraday/` 全绿（42 既有 + ≥ 5 zhuang_distribution case）
2. `pytest tests/` 全绿
3. `cd frontend && npm run build` 成功（tsc + vite build）
4. dry-run smoke：zhuang 路径不抛错

## 不动

- alembic / alerts_sent schema
- yaml 策略阈值 / weights / 5 因子
- daily 决策 / backtest

## Backstop 5 条

- #1 17 条证伪：不调 yaml ✓
- #2 双窗口 8y：不改 yaml ✓
- #3 实盘 < 30 笔：不撬 frontier ✓
- #4 PM 决策权：仅推送"考虑减仓"，0 自动平仓 ✓
- #5 采集 ≠ alpha：alert ≠ decision ✓

## 后续 (out of harness)

- 30s/1min 更激进 polling 频率（需先评估 spot_em 限流风险）
- websocket / SSE 替代 polling（架构升级，独立 PR）
- HK 量比数据源接入（需付费 L1 行情或第三方）
- zhuang sleeve 5min 涨幅维度（要持久化中间状态，独立 PR）
