import type { ColumnDef, OptionsSpread } from '../types';
import DataTable from './DataTable';

function fmtPct(v: number | null): string {
  if (v === null || v === undefined) return '—';
  const sign = v >= 0 ? '+' : '';
  return `${sign}${(v * 100).toFixed(2)}%`;
}

function colorPnl(v: number | null): string {
  if (v === null || v === undefined) return '';
  return v > 0 ? 'text-[#30d158]' : v < 0 ? 'text-[#ff453a]' : '';
}

const spreadColumns: ColumnDef<OptionsSpread>[] = [
  {
    key: 'strikes',
    header: '价差',
    render: (r) => (
      <span className="font-semibold">
        {r.long_strike.toFixed(0)}/{r.short_strike.toFixed(0)}
      </span>
    ),
  },
  {
    key: 'expiry',
    header: '到期 / DTE',
    render: (r) => (
      <span>
        {r.expiry}{' '}
        <span className={r.days_to_exp < 7 ? 'text-[#ff453a] font-semibold' : 'text-[#86868b]'}>
          ({r.days_to_exp}D)
        </span>
      </span>
    ),
  },
  { key: 'contracts', header: '合约', render: (r) => `${r.contracts}` },
  { key: 'debit_paid', header: '净付出', render: (r) => `$${r.debit_paid.toFixed(2)}` },
  {
    key: 'current_value',
    header: '当前价',
    render: (r) => (r.current_value === null || r.current_value === undefined ? '—' : `$${r.current_value.toFixed(2)}`),
  },
  {
    key: 'pnl_pct',
    header: '盈亏',
    render: (r) => <span className={`font-semibold ${colorPnl(r.pnl_pct)}`}>{fmtPct(r.pnl_pct)}</span>,
  },
  {
    key: 'breach_alerts',
    header: '告警',
    render: (r) => {
      if (!r.breach_alerts || r.breach_alerts.length === 0) {
        return <span className="text-[#86868b]">—</span>;
      }
      return (
        <span className="text-[#ff453a] font-semibold">
          {r.breach_alerts.join(' / ')}
        </span>
      );
    },
  },
];

interface Props {
  spreads: OptionsSpread[];
}

export default function OptionsPositionTable({ spreads }: Props) {
  if (!spreads || spreads.length === 0) {
    return (
      <div style={{ padding: '12px 14px', textAlign: 'center', color: 'var(--color-text-secondary)', fontSize: 13 }}>
        无 BCS 持仓
      </div>
    );
  }
  return <DataTable columns={spreadColumns} data={spreads} />;
}
