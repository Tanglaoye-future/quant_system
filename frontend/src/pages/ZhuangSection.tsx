import GlassCard from '../components/GlassCard';
import MetricGrid from '../components/MetricGrid';
import MetricCard from '../components/MetricCard';
import DataTable from '../components/DataTable';
import type { ColumnDef, ZhuangData, ZhuangCandidate } from '../types';

type Column<T> = ColumnDef<T>;

const columns: Column<ZhuangCandidate>[] = [
  {
    key: 'rank',
    header: '#',
    render: (_, i) => <span className="text-[#86868b]">{i + 1}</span>,
    className: 'w-8',
  },
  {
    key: 'code',
    header: '代码',
    render: (r) => <span className="font-semibold">{r.code}</span>,
  },
  { key: 'ma_convergence', header: 'MA 收敛', render: (r) => r.ma_convergence.toFixed(1) },
  { key: 'volume_asymmetry', header: '量价不对称', render: (r) => r.volume_asymmetry.toFixed(1) },
  { key: 'price_consolidation', header: '价格横盘', render: (r) => r.price_consolidation.toFixed(1) },
  { key: 'turnover_decline', header: '换手下降', render: (r) => r.turnover_decline.toFixed(1) },
  { key: 'vp_divergence', header: '量价背离', render: (r) => r.vp_divergence.toFixed(1) },
  {
    key: 'total',
    header: '综合评分',
    render: (r) => {
      const cls = r.total >= 65 ? 'text-[#30d158]' : r.total >= 55 ? 'text-[#ff9f0a]' : '';
      return <span className={`font-bold ${cls}`}>{r.total.toFixed(1)}</span>;
    },
  },
];

export default function ZhuangSection({ data }: { data: ZhuangData }) {
  if (data._missing) {
    return (
      <section className="mb-12 animate-fadeIn">
        <h2 className="text-xl font-semibold tracking-tight mb-4">庄股小盘跟庄</h2>
        <GlassCard>
          <div className="text-center py-12 text-[#aeaeb2]">
            暂无数据，请运行 <code className="bg-[#f0f0f2] px-1.5 py-0.5 rounded text-sm">python scripts/daily/daily_zhuang.py</code>
          </div>
        </GlassCard>
      </section>
    );
  }

  const zCount = data.candidates_count ?? 0;
  const zMax = data.top_candidates?.[0]?.total ?? 0;
  const overThreshold = zMax >= 65;

  return (
    <section className="mb-12 animate-fadeIn">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold tracking-tight">庄股小盘跟庄</h2>
        <span className="text-xs text-[#aeaeb2]">{data.date}</span>
      </div>

      <GlassCard className="mb-4">
        <MetricGrid>
          <MetricCard label="Universe" value={data.universe_size ?? '—'} sub="50-2000 亿" />
          <MetricCard label="候选数" value={zCount} sub="≥45 分" colorClass={zCount > 0 ? 'text-[#0071e3]' : ''} />
          <MetricCard
            label="最高评分"
            value={zMax.toFixed(1)}
            sub={overThreshold ? '✅ 达标' : '门槛 65'}
            colorClass={overThreshold ? 'text-[#30d158]' : 'text-[#ff9f0a]'}
          />
          <MetricCard
            label="市场趋势"
            value={data.market_trend ? '金叉 OK' : '未达'}
            sub="CSI500 MA60"
            colorClass={data.market_trend ? 'text-[#30d158]' : 'text-[#ff453a]'}
          />
        </MetricGrid>
      </GlassCard>

      <GlassCard>
        <div className="text-sm font-semibold text-[#1d1d1f] mb-3">
          吃货期候选 · TOP 15
        </div>
        <DataTable columns={columns} data={data.top_candidates || []} emptyText="无候选" />
        <div className="mt-3 text-xs text-[#86868b] leading-relaxed">
          {overThreshold
            ? '✅ 存在达到实盘门槛的候选，请进一步人工确认。'
            : '⚠ 最高分未达实盘门槛 (65)，今日仅监控，不建议入场。'}
          <br />
          权重：MA 收敛 ×0.20 · 量价不对称 ×0.30 · 价格横盘 ×0.20 · 换手下降 ×0.15 · 量价背离 ×0.15
        </div>
      </GlassCard>
    </section>
  );
}
