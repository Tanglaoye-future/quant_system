import type { ColumnDef, QuantSignal, QuantPosition, ZhuangCandidate } from '../types';

function fmtPct(v: number | null): string {
  if (v === null || v === undefined) return '—';
  const sign = v >= 0 ? '+' : '';
  return `${sign}${(v * 100).toFixed(2)}%`;
}

function colorPnl(v: number | null): string {
  if (v === null || v === undefined) return '';
  return v > 0 ? 'text-[#30d158]' : v < 0 ? 'text-[#ff453a]' : '';
}

export const signalColumns: ColumnDef<QuantSignal>[] = [
  { key: 'code', header: '代码', render: (r) => <span className="font-semibold">{r.code}</span> },
  { key: 'name', header: '名称', render: (r) => r.name || '—' },
  { key: 'score', header: '评分', render: (r) => <span className={r.score > 0 ? 'text-[#0071e3]' : ''}>{r.score.toFixed(3)}</span> },
  { key: 'entry_price', header: '入场价', render: (r) => r.entry_price.toFixed(2) },
  { key: 'stop_loss', header: '止损', render: (r) => r.stop_loss.toFixed(2) },
  { key: 'take_profit', header: '止盈', render: (r) => r.take_profit.toFixed(2) },
  { key: 'reason', header: '入场理由', render: (r) => <span className="text-xs text-[#86868b]">{r.reason}</span> },
];

export const positionColumns: ColumnDef<QuantPosition>[] = [
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

export const zhuangColumns: ColumnDef<ZhuangCandidate>[] = [
  { key: 'rank', header: '#', render: (_, i) => <span className="text-[#86868b]">{i + 1}</span> },
  { key: 'code', header: '代码', render: (r) => <span className="font-semibold">{r.code}</span> },
  { key: 'ma_convergence', header: 'MA 收敛', render: (r) => r.ma_convergence.toFixed(1) },
  { key: 'volume_asymmetry', header: '量价不对称', render: (r) => r.volume_asymmetry.toFixed(1) },
  { key: 'price_consolidation', header: '价格横盘', render: (r) => r.price_consolidation.toFixed(1) },
  { key: 'turnover_decline', header: '换手下降', render: (r) => r.turnover_decline.toFixed(1) },
  { key: 'vp_divergence', header: '量价背离', render: (r) => r.vp_divergence.toFixed(1) },
  {
    key: 'total', header: '综合评分', render: (r) => {
      const c = r.total >= 65 ? 'text-[#30d158]' : r.total >= 55 ? 'text-[#ff9f0a]' : '';
      return <span className={`font-bold ${c}`}>{r.total.toFixed(1)}</span>;
    },
  },
];
