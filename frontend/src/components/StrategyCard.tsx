import type { CellResponse } from '../types';
import CellStatusBadge from './CellStatusBadge';
import GlassCard from './GlassCard';
import MetricCard from './MetricCard';
import MetricGrid from './MetricGrid';

interface Props {
  cell: CellResponse;
  /** 当 status != active 时, 是否仍显示卡片 (默认 true — 显示占位) */
  showPlaceholder?: boolean;
}

export default function StrategyCard({ cell, showPlaceholder = true }: Props) {
  const { strategy_label, strategy_kind, status, has_data, blocker_reason, metrics } = cell;
  const isActive = status === 'active' && has_data;

  if (!isActive && !showPlaceholder) return null;

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

      {/* active: show metrics */}
      {isActive && strategy_kind === 'zhuang' && (
        <MetricGrid>
          <MetricCard label="候选数" value={metrics.candidates_count ?? 0} sub="score≥45" />
          <MetricCard label="Universe" value="—" sub="50–2000亿" />
          <MetricCard label="最高分" value={metrics.candidates_count ? '—' : '—'} sub="入场门槛65" />
          <MetricCard label="市场趋势" value="—" sub="CSI500 MA60" />
        </MetricGrid>
      )}
      {isActive && (strategy_kind === 'bottomup_timing' || strategy_kind === 'mean_reversion') && (
        <MetricGrid>
          <MetricCard label="信号数" value={metrics.signals_count ?? 0} sub="今日买入候选" />
          <MetricCard label="持仓数" value={metrics.positions_count ?? 0} sub="最大10仓" />
          <MetricCard label="市况门" value={metrics.market_gate ? 'OK' : (metrics.market_gate === false ? 'CLOSE' : '—')} sub={metrics.market_gate ? '允许开仓' : '禁止开仓'} />
          <MetricCard label="基准" value="—" sub="HS300 / HSCHK100" />
        </MetricGrid>
      )}
      {isActive && strategy_kind === 'bull_call_spread' && (
        <MetricGrid>
          <MetricCard label="IVR" value={metrics.ivr != null ? String(metrics.ivr) : '—'} sub={metrics.iv_mode ?? '—'} />
          <MetricCard label="QQQ" value={metrics.qqq_price != null ? `$${metrics.qqq_price}` : '—'} sub="MA200 跟踪中" />
          <MetricCard label="RSI(14)" value={metrics.qqq_rsi != null ? String(metrics.qqq_rsi) : '—'} sub={metrics.qqq_rsi && metrics.qqq_rsi > 75 ? '超买' : '正常'} />
          <MetricCard label="信号评级" value={metrics.signal_grade ?? '—'} sub={metrics.reason?.slice(0, 20) ?? ''} />
        </MetricGrid>
      )}

      {/* blocked / unsupported / deprecated: show reason */}
      {!isActive && blocker_reason && (
        <div style={{
          padding: '10px 14px', borderRadius: 8,
          background: 'var(--color-bg)', fontSize: 13,
          color: 'var(--color-text-secondary)', lineHeight: 1.6,
        }}>
          {blocker_reason}
        </div>
      )}

      {/* available but no data */}
      {!isActive && !blocker_reason && (
        <div style={{
          padding: '10px 14px', borderRadius: 8,
          background: 'var(--color-bg)', fontSize: 13,
          color: 'var(--color-text-secondary)',
        }}>
          架构就绪，可通过 CLI 运行。不在每日定时任务中。
        </div>
      )}
    </GlassCard>
  );
}
