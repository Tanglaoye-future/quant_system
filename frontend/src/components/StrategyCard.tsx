import type { CellResponse, QuantData, ZhuangData, OptionsData, QuantSignal, QuantPosition, CBData } from '../types';
import CellStatusBadge from './CellStatusBadge';
import GlassCard from './GlassCard';
import MetricCard from './MetricCard';
import MetricGrid from './MetricGrid';
import DataTable from './DataTable';
import OptionsPositionTable from './OptionsPositionTable';
// ZHUANG_DEPRECATED 2026-06-14: zhuangColumns/zhuangPositionColumns 已不消费.
import { signalColumns, positionColumns /*, zhuangColumns, zhuangPositionColumns */ } from './tableColumns';

/** _source label → strategy_name 映射, 用于从 quant 合并数据中提取对应策略的信号/持仓 */
const SOURCE_TO_STRATEGY: Record<string, string> = {
  'A 股 · momentum': 'equity_momentum',
  'A 股 · mean-reversion': 'equity_mean_reversion',
  'HK 港股 · momentum': 'equity_hk_momentum',
};

interface Props {
  cell: CellResponse;
  showPlaceholder?: boolean;
  /** 详细数据 — 来自 ReportSummary */
  quantData?: QuantData;
  zhuangData?: ZhuangData;
  optionsData?: OptionsData;
  cbData?: CBData;
}

// ZHUANG_DEPRECATED 2026-06-14: zhuangData 形参保留以兼容 caller, 内部 _zhuangData unused.
export default function StrategyCard({ cell, showPlaceholder = true, quantData, zhuangData: _zhuangData, optionsData, cbData }: Props) {
  const { strategy_name, strategy_label, strategy_kind, status, has_data, blocker_reason, metrics } = cell;
  const isActive = status === 'active' && has_data;

  if (!isActive && !showPlaceholder) return null;

  // ── 提取该策略对应的详细数据 ──────────────────────────────────────
  let signals: QuantSignal[] = [];
  let positions: QuantPosition[] = [];
  // ZHUANG_DEPRECATED 2026-06-14:
  // let zhuangCandidates = _zhuangData?.top_candidates ?? [];
  // const zhuangPositions = _zhuangData?.positions ?? [];

  let portfolioAlerts: string[] = [];
  if (quantData && (strategy_kind === 'bottomup_timing' || strategy_kind === 'mean_reversion')) {
    // 找到匹配的 _source label
    const sourceLabel = Object.entries(SOURCE_TO_STRATEGY).find(([, s]) => s === strategy_name)?.[0];
    signals = (quantData.signals || []).filter(s => s._source === sourceLabel);
    positions = (quantData.positions || []).filter(p => p._source === sourceLabel);
    if (sourceLabel) {
      const prefix = `[${sourceLabel}] `;
      portfolioAlerts = (quantData.portfolio_alerts || [])
        .filter(a => a.startsWith(prefix))
        .map(a => a.slice(prefix.length));
    }
  }

  return (
    <GlassCard>
      {/* header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div>
          <div style={{ fontWeight: 600, fontSize: 15, color: 'var(--color-text)' }}>
            {strategy_label}
          </div>
          <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginTop: 2 }}>
            {strategy_kind}
          </div>
        </div>
        <CellStatusBadge status={status} />
      </div>

      {/* ── active: metrics + data tables ── */}
      {/* ZHUANG_DEPRECATED 2026-06-14: 整段 zhuang_kind 分支注释; 后端不再生产 zhuang.json (2026-06-09 stale). */}
      {/*
      {isActive && strategy_kind === 'zhuang' && (
        <>
          {(_zhuangData?.portfolio_alerts ?? []).length > 0 && (
            <div style={{
              marginBottom: 12,
              padding: '10px 14px',
              borderRadius: 8,
              background: '#ffe8e6',
              border: '1px solid #ff453a',
              fontSize: 13,
              color: '#c0392b',
              lineHeight: 1.6,
            }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>⚠ 组合层告警</div>
              {(_zhuangData?.portfolio_alerts ?? []).map((a, i) => (
                <div key={i}>· {a}</div>
              ))}
            </div>
          )}
          {_zhuangData?.portfolio_summary?.drawdown_from_peak_pct != null && (
            <div style={{
              marginBottom: 12, fontSize: 12, color: 'var(--color-text-secondary)',
            }}>
              组合层回撤 {(_zhuangData.portfolio_summary.drawdown_from_peak_pct * 100).toFixed(2)}%
              （peak ¥{Math.round(_zhuangData.portfolio_summary.peak_market_value ?? 0).toLocaleString()}）
            </div>
          )}
          <MetricGrid>
            <MetricCard label="当前持仓" value={zhuangPositions.length} sub="最大 6 仓" />
            <MetricCard label="候选数" value={zhuangCandidates.length} sub="score≥45" />
            <MetricCard label="最高分" value={zhuangCandidates[0]?.total?.toFixed(1) ?? '—'} sub="入场门槛 65" />
            <MetricCard label="市场趋势" value={_zhuangData?.market_trend ? '金叉' : '未达'} sub="CSI500 MA60" />
          </MetricGrid>
          {zhuangPositions.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: 'var(--color-text)' }}>
                当前持仓
              </div>
              <DataTable columns={zhuangPositionColumns} data={zhuangPositions} />
            </div>
          )}
          {zhuangCandidates.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: 'var(--color-text)' }}>
                今日候选 TOP 15
              </div>
              <DataTable columns={zhuangColumns} data={zhuangCandidates.slice(0, 15)} />
            </div>
          )}
        </>
      )}
      */}

      {isActive && (strategy_kind === 'bottomup_timing' || strategy_kind === 'mean_reversion') && (
        <>
          {portfolioAlerts.length > 0 && (
            <div style={{
              marginBottom: 12,
              padding: '10px 14px',
              borderRadius: 8,
              background: '#ffe8e6',
              border: '1px solid #ff453a',
              fontSize: 13,
              color: '#c0392b',
              lineHeight: 1.6,
            }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>⚠ 组合层告警</div>
              {portfolioAlerts.map((a, i) => (
                <div key={i}>· {a}</div>
              ))}
            </div>
          )}
          {quantData?.portfolio_summary?.drawdown_from_peak_pct != null && (
            <div style={{
              marginBottom: 12, fontSize: 12, color: 'var(--color-text-secondary)',
            }}>
              组合层回撤 {(quantData.portfolio_summary.drawdown_from_peak_pct * 100).toFixed(2)}%
              （peak ¥{Math.round(quantData.portfolio_summary.peak_market_value ?? 0).toLocaleString()}）
            </div>
          )}
          <MetricGrid>
            <MetricCard label="买入信号" value={signals.length} sub="今日触发" />
            <MetricCard label="当前持仓" value={positions.length} sub="最大 10 仓" />
            <MetricCard label="市况门" value={quantData?.market_gate ? 'OK' : (quantData?.market_gate === false ? 'CLOSE' : '—')} sub={quantData?.market_gate_msg?.slice(0, 20) ?? ''} />
            <MetricCard label="基准" value={quantData?.benchmark_close ?? '—'} sub={`MA60 ${quantData?.benchmark_ma60 ?? '—'}`} />
          </MetricGrid>

          {signals.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: 'var(--color-text)' }}>
                今日买入候选
              </div>
              <DataTable columns={signalColumns} data={signals} />
            </div>
          )}

          {positions.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: 'var(--color-text)' }}>
                当前持仓
              </div>
              <DataTable columns={positionColumns} data={positions} />
            </div>
          )}

          {signals.length === 0 && positions.length === 0 && (
            <div style={{ padding: '16px', textAlign: 'center', color: 'var(--color-text-secondary)', fontSize: 13 }}>
              今日无信号，无持仓 — 等待市况触发
            </div>
          )}
        </>
      )}

      {isActive && strategy_kind === 'bull_call_spread' && (
        <>
          <MetricGrid>
            <MetricCard label="IVR" value={metrics.ivr != null ? String(metrics.ivr) : '—'} sub={metrics.iv_mode ?? '—'} />
            <MetricCard label="QQQ" value={metrics.qqq_price != null ? `$${metrics.qqq_price}` : '—'} sub={`RSI ${metrics.qqq_rsi ?? '—'}`} />
            <MetricCard label="信号评级" value={metrics.signal_grade ?? '—'} sub={metrics.qqq_bullish ? '看涨' : '看跌'} />
            <MetricCard label="状态" value={optionsData?.signal ? '有信号' : '无信号'} sub={optionsData?.reason?.slice(0, 20) ?? ''} />
          </MetricGrid>
          {optionsData?.signal && (
            <div style={{ marginTop: 12, padding: 14, background: 'var(--color-bg)', borderRadius: 8, fontSize: 13 }}>
              <div style={{ fontWeight: 600, marginBottom: 8 }}>Bull Call Spread 信号</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 16px', color: 'var(--color-text-secondary)' }}>
                <span>结构: {optionsData.signal.structure}</span>
                <span>合约: {optionsData.signal.contracts} 张</span>
                <span>买腿: {optionsData.signal.buy_leg}</span>
                <span>卖腿: {optionsData.signal.sell_leg}</span>
                <span>最大盈利: {optionsData.signal.max_profit}</span>
                <span>最大亏损: {optionsData.signal.max_loss}</span>
              </div>
            </div>
          )}
          {/* PR3: BCS 持仓表（spreads 字段从 daily_options.py IBKR fill 来；空时显「无 BCS 持仓」）*/}
          {optionsData?.spreads !== undefined && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: 'var(--color-text)' }}>
                当前 BCS 持仓
              </div>
              <OptionsPositionTable spreads={optionsData.spreads ?? []} />
            </div>
          )}
        </>
      )}

      {/* CB 双低 advisory (PR7 2026-06-16): 不出买入信号, 只列今日双低 top + 强赎警告 */}
      {isActive && strategy_kind === 'cb_double_low' && (
        <>
          <div style={{
            marginBottom: 12, padding: '8px 12px', borderRadius: 6,
            background: '#fff8e1', border: '1px solid #ffd54f',
            fontSize: 12, color: '#7c5b00', lineHeight: 1.5,
          }}>
            <strong>advisory only</strong> — 不接 journal / portfolio_history.
            PM 月初人工 rebalance 参考. v7 配比 CB sleeve {((cbData?.config?.target_pct ?? 0) * 100).toFixed(0)}% (从 {cbData?.config?.source || '?'} 抽).
          </div>
          <MetricGrid>
            <MetricCard label="今日候选" value={cbData?.entries_top?.length ?? 0} sub={`top ${cbData?.config?.n_entry ?? '—'}`} colorClass={(cbData?.entries_top?.length ?? 0) > 0 ? 'text-[#0071e3]' : ''} />
            <MetricCard label="可投 universe" value={cbData?.universe?.active ?? '—'} sub={`${cbData?.universe?.total ?? '—'} 全集`} />
            <MetricCard label="强赎预警" value={cbData?.warn_redeem_near?.length ?? 0} sub="近期触发强赎" colorClass={(cbData?.warn_redeem_near?.length ?? 0) > 0 ? 'text-[#ff9f0a]' : ''} />
            <MetricCard label="数据日期" value={cbData?.date || '—'} sub={`panel: ${cbData?.asof_panel || '—'}`} />
          </MetricGrid>
          {cbData?.entries_top && cbData.entries_top.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: 'var(--color-text)' }}>
                今日双低 TOP {cbData.entries_top.length}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-[#e5e5ea] text-[#86868b]">
                      <th className="text-left py-2 px-2 font-medium">#</th>
                      <th className="text-left py-2 px-2 font-medium">代码</th>
                      <th className="text-left py-2 px-2 font-medium">名称</th>
                      <th className="text-right py-2 px-2 font-medium">现价</th>
                      <th className="text-right py-2 px-2 font-medium">转股溢价率</th>
                      <th className="text-right py-2 px-2 font-medium">双低分</th>
                      <th className="text-center py-2 px-2 font-medium">强赎</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cbData.entries_top.slice(0, 20).map((e) => (
                      <tr key={e.bond_code} className="border-b border-[#f0f0f2]">
                        <td className="py-1.5 px-2 text-[#86868b]">{e.rank}</td>
                        <td className="py-1.5 px-2 font-mono font-semibold">{e.bond_code}</td>
                        <td className="py-1.5 px-2">{e.bond_name}</td>
                        <td className="py-1.5 px-2 text-right font-mono">{e.close.toFixed(2)}</td>
                        <td className="py-1.5 px-2 text-right">{e.conversion_premium_rate.toFixed(2)}%</td>
                        <td className="py-1.5 px-2 text-right font-semibold">{e.dual_low_score.toFixed(2)}</td>
                        <td className="py-1.5 px-2 text-center">
                          {e.warn_redeem_near ? <span className="text-[#ff9f0a]">⚠</span> : ''}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {/* ── blocked / unsupported / deprecated: reason ── */}
      {!isActive && blocker_reason && (
        <div style={{ padding: '10px 14px', borderRadius: 8, background: 'var(--color-bg)', fontSize: 13, color: 'var(--color-text-secondary)', lineHeight: 1.6 }}>
          {blocker_reason}
        </div>
      )}
      {!isActive && !blocker_reason && (
        <div style={{ padding: '10px 14px', borderRadius: 8, background: 'var(--color-bg)', fontSize: 13, color: 'var(--color-text-secondary)' }}>
          架构就绪，可通过 CLI 运行。不在每日定时任务中。
        </div>
      )}
    </GlassCard>
  );
}
