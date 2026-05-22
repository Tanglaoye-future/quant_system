import GlassCard from '../components/GlassCard';
import MetricGrid from '../components/MetricGrid';
import MetricCard from '../components/MetricCard';
import DataTable from '../components/DataTable';
import StatusBadge from '../components/StatusBadge';
import type { ColumnDef, QuantData, QuantSignal, QuantPosition } from '../types';

type Column<T> = ColumnDef<T>;

function fmtPct(v: number | null): string {
  if (v === null || v === undefined) return '—';
  const sign = v >= 0 ? '+' : '';
  return `${sign}${(v * 100).toFixed(2)}%`;
}

function colorPnl(v: number | null): string {
  if (v === null || v === undefined) return '';
  if (v > 0) return 'text-[#30d158]';
  if (v < 0) return 'text-[#ff453a]';
  return '';
}

const signalColumns: Column<QuantSignal>[] = [
  { key: 'code', header: '代码', render: (r) => <span className="font-semibold">{r.code}</span> },
  { key: 'name', header: '名称', render: (r) => r.name || '—' },
  { key: 'score', header: '评分', render: (r) => <span className={r.score > 0 ? 'text-[#0071e3]' : ''}>{r.score.toFixed(3)}</span> },
  { key: 'entry_price', header: '入场价', render: (r) => r.entry_price.toFixed(2) },
  { key: 'stop_loss', header: '止损', render: (r) => r.stop_loss.toFixed(2) },
  { key: 'take_profit', header: '止盈', render: (r) => r.take_profit.toFixed(2) },
  { key: 'reason', header: '入场理由', render: (r) => <span className="text-xs text-[#86868b]">{r.reason}</span> },
];

const positionColumns: Column<QuantPosition>[] = [
  { key: 'code', header: '代码', render: (r) => <span className="font-semibold">{r.code}</span> },
  { key: 'name', header: '名称', render: (r) => r.name || '—' },
  { key: 'entry_date', header: '入场日', render: (r) => r.entry_date },
  { key: 'hold_days', header: '持有天', render: (r) => `${r.hold_days} 天` },
  { key: 'pnl_pct', header: '浮盈', render: (r) => <span className={`font-semibold ${colorPnl(r.pnl_pct)}`}>{fmtPct(r.pnl_pct)}</span> },
  {
    key: 'action',
    header: '操作',
    render: (r) => {
      const v = r.action === 'EXIT' ? 'bg-[#ffe8e6] text-[#c0392b]' : 'bg-[#e5f9e8] text-[#1a7f37]';
      return <span className={`inline-flex px-2 py-0.5 text-[11px] font-semibold rounded-md ${v}`}>{r.action === 'EXIT' ? '卖出' : '持有'}</span>;
    },
  },
];

export default function HKSection({ data }: { data: QuantData }) {
  const hkSignals = (data.signals || []).filter((s) => s._source?.startsWith('HK'));
  const hkPositions = (data.positions || []).filter((p) => p._source?.startsWith('HK'));

  const gateOk = data.market_gate;
  const gateLabel = gateOk === true ? '通过' : gateOk === false ? '关闭' : '—';
  const gateColor = gateOk ? 'text-[#30d158]' : 'text-[#ff453a]';
  const status = hkSignals.length > 0 ? ('active' as const) : ('idle' as const);

  if (data._missing) {
    return (
      <section className="mb-12 animate-fadeIn">
        <GlassCard>
          <div className="text-center py-12 text-[#aeaeb2]">
            暂无数据，请运行 <code className="bg-[#f0f0f2] px-1.5 py-0.5 rounded text-sm">python scripts/daily/daily_equity.py --market hk_share</code>
          </div>
        </GlassCard>
      </section>
    );
  }

  return (
    <section className="mb-12 animate-fadeIn">
      <GlassCard className="mb-4">
        <div className="flex items-center justify-between mb-3">
          <div className="text-sm font-semibold text-[#1d1d1f]">中线 momentum</div>
          <StatusBadge label={status === 'active' ? '活跃' : '待机'} variant={status === 'active' ? 'pass' : 'idle'} />
        </div>

        <MetricGrid>
          <MetricCard label="M2 市况门" value={gateLabel} sub={data.market_gate_msg || 'HSCHK100 MA60'} colorClass={gateColor} />
          <MetricCard label="买入信号" value={hkSignals.length} sub="今日候选" colorClass={hkSignals.length > 0 ? 'text-[#0071e3]' : ''} />
          <MetricCard label="当前持仓" value={hkPositions.length} sub="最大 6 仓" />
          <MetricCard label="HSCHK100" value={data.benchmark_close} sub={`MA60: ${data.benchmark_ma60}`} />
        </MetricGrid>

        {hkSignals.length > 0 && (
          <div className="mb-3">
            <div className="text-xs font-medium text-[#86868b] mb-2">买入候选</div>
            <DataTable columns={signalColumns} data={hkSignals} emptyText="今日无买入信号" />
          </div>
        )}
        {hkPositions.length > 0 && (
          <div>
            <div className="text-xs font-medium text-[#86868b] mb-2">当前持仓</div>
            <DataTable columns={positionColumns} data={hkPositions} emptyText="当前空仓" />
          </div>
        )}
        {hkSignals.length === 0 && hkPositions.length === 0 && (
          <div className="text-center py-6 text-[#aeaeb2] text-sm">今日无信号，无持仓</div>
        )}
      </GlassCard>
    </section>
  );
}
