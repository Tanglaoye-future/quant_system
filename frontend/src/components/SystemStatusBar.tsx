import GlassCard from './GlassCard';
import StatusBadge from './StatusBadge';
import type { MarketsResponse, MarketData } from '../types';

function regimeVariant(r: string): 'pass' | 'fail' | 'idle' {
  if (r === 'ok' || r === 'bullish') return 'pass';
  if (r === 'closed' || r === 'bearish') return 'fail';
  return 'idle';
}

function regimeLabel(r: string): string {
  if (r === 'ok') return '市况通过';
  if (r === 'closed') return '市况关闭';
  if (r === 'bullish') return '看涨';
  if (r === 'bearish') return '看跌';
  return '未知';
}

function activeSummary(strategies: MarketData['strategies']): string {
  const active = strategies.filter((s) => s.status === 'active' || s.status === 'signal');
  if (active.length === 0) return '待机';
  return active.map((s) => s.name).join(' · ');
}

export default function SystemStatusBar({ markets }: { markets: MarketsResponse }) {
  const entries = [
    { key: 'a_share', label: 'A 股', data: markets.a_share },
    { key: 'us', label: '美股', data: markets.us },
    { key: 'hk', label: '港股', data: markets.hk },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-10 animate-fadeIn">
      {entries.map(({ key, label, data }) => {
        const idx = data.index;
        return (
          <GlassCard key={key}>
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="text-xs font-semibold text-[#86868b] uppercase tracking-wider">
                  {label}
                </div>
                <div className="text-sm font-medium text-[#1d1d1f] mt-0.5">
                  {idx.name} <span className="text-[#aeaeb2] font-normal">{idx.symbol}</span>
                </div>
              </div>
              <StatusBadge
                label={regimeLabel(idx.regime)}
                variant={regimeVariant(idx.regime)}
              />
            </div>
            <div className="text-sm text-[#1d1d1f] leading-relaxed">
              {idx.close != null && idx.close !== '—' && (
                <span className="font-semibold tabular-nums">
                  {typeof idx.close === 'number' ? idx.close.toFixed(2) : idx.close}
                </span>
              )}
              {(idx.ma60 != null || idx.ma200 != null || idx.ma != null) && (
                <span className="text-[#86868b] ml-2">
                  {idx.ma60 != null ? `MA60 ${idx.ma60}` : ''}
                  {idx.ma200 != null ? `MA200 ${idx.ma200}` : ''}
                  {idx.ma != null && !idx.ma60 && !idx.ma200 ? `MA ${idx.ma}` : ''}
                </span>
              )}
              <br />
              <span className="text-xs text-[#86868b]">{activeSummary(data.strategies)}</span>
            </div>
          </GlassCard>
        );
      })}
    </div>
  );
}
