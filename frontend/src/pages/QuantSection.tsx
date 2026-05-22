import GlassCard from '../components/GlassCard';
import MetricGrid from '../components/MetricGrid';
import MetricCard from '../components/MetricCard';
import DataTable from '../components/DataTable';
import type { ColumnDef } from '../types';
import type { QuantData, QuantSignal, QuantPosition } from '../types';

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
  {
    key: 'source',
    header: '策略',
    render: (r) => (
      <span className="inline-flex px-2 py-0.5 text-[11px] font-medium rounded-md bg-[#f0f0f2] text-[#86868b]">
        {r._source}
      </span>
    ),
  },
  {
    key: 'score',
    header: '评分',
    render: (r) => <span className={r.score > 0 ? 'text-[#0071e3]' : ''}>{r.score.toFixed(3)}</span>,
  },
  { key: 'entry_price', header: '入场价', render: (r) => r.entry_price.toFixed(2) },
  { key: 'stop_loss', header: '止损', render: (r) => r.stop_loss.toFixed(2) },
  { key: 'take_profit', header: '止盈', render: (r) => r.take_profit.toFixed(2) },
  { key: 'reason', header: '入场理由', render: (r) => <span className="text-xs text-[#86868b]">{r.reason}</span> },
  {
    key: 'action',
    header: '建议',
    render: () => (
      <span className="inline-flex px-2 py-0.5 text-[11px] font-semibold rounded-md bg-[#e5f9e8] text-[#1a7f37]">
        买入
      </span>
    ),
  },
];

const positionColumns: Column<QuantPosition>[] = [
  { key: 'code', header: '代码', render: (r) => <span className="font-semibold">{r.code}</span> },
  { key: 'name', header: '名称', render: (r) => r.name || '—' },
  {
    key: 'source',
    header: '策略',
    render: (r) => (
      <span className="inline-flex px-2 py-0.5 text-[11px] font-medium rounded-md bg-[#f0f0f2] text-[#86868b]">
        {r._source}
      </span>
    ),
  },
  { key: 'entry_date', header: '入场日', render: (r) => r.entry_date },
  { key: 'hold_days', header: '持有天', render: (r) => `${r.hold_days} 天` },
  {
    key: 'pnl_pct',
    header: '浮盈',
    render: (r) => <span className={`font-semibold ${colorPnl(r.pnl_pct)}`}>{fmtPct(r.pnl_pct)}</span>,
  },
  {
    key: 'action',
    header: '操作',
    render: (r) => {
      const variant = r.action === 'EXIT' ? 'bg-[#ffe8e6] text-[#c0392b]' : 'bg-[#e5f9e8] text-[#1a7f37]';
      return (
        <span className={`inline-flex px-2 py-0.5 text-[11px] font-semibold rounded-md ${variant}`}>
          {r.action === 'EXIT' ? '卖出' : '持有'}
        </span>
      );
    },
  },
];

export default function QuantSection({ data }: { data: QuantData }) {
  if (data._missing) {
    return (
      <section className="mb-12 animate-fadeIn">
        <h2 className="text-xl font-semibold tracking-tight mb-4">A 股中线量化</h2>
        <GlassCard>
          <div className="text-center py-12 text-[#aeaeb2]">
            暂无数据，请运行 <code className="bg-[#f0f0f2] px-1.5 py-0.5 rounded text-sm">python scripts/daily/daily_equity.py</code>
          </div>
        </GlassCard>
      </section>
    );
  }

  const nPositions = data.positions?.length ?? 0;
  const nSignals = data.signals?.length ?? 0;
  const gateLabel = data.market_gate === true ? '通过' : data.market_gate === false ? '关闭' : '—';
  const gateColor = data.market_gate ? 'text-[#30d158]' : 'text-[#ff453a]';

  return (
    <section className="mb-12 animate-fadeIn">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold tracking-tight">A 股中线量化</h2>
        <span className="text-xs text-[#aeaeb2]">{data.date}</span>
      </div>

      <GlassCard className="mb-4">
        <MetricGrid>
          <MetricCard label="持仓数" value={nPositions} sub="最大 6 仓" />
          <MetricCard label="买入候选" value={nSignals} sub="今日信号" colorClass={nSignals > 0 ? 'text-[#0071e3]' : ''} />
          <MetricCard label="M2 市况门" value={gateLabel} sub={data.market_gate_msg} colorClass={gateColor} />
          <MetricCard label="HS300" value={data.benchmark_close} sub={`MA60: ${data.benchmark_ma60}`} />
        </MetricGrid>
      </GlassCard>

      <GlassCard className="mb-4">
        <div className="text-sm font-semibold text-[#1d1d1f] mb-3">买入候选</div>
        <DataTable columns={signalColumns} data={data.signals || []} emptyText="今日无买入信号" />
      </GlassCard>

      <GlassCard>
        <div className="text-sm font-semibold text-[#1d1d1f] mb-3">当前持仓</div>
        <DataTable columns={positionColumns} data={data.positions || []} emptyText="当前空仓" />
      </GlassCard>
    </section>
  );
}
