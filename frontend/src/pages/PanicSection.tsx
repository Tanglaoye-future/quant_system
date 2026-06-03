import GlassCard from '../components/GlassCard';
import MetricGrid from '../components/MetricGrid';
import MetricCard from '../components/MetricCard';
import DataTable from '../components/DataTable';
import StatusBadge from '../components/StatusBadge';
import type {
  ColumnDef,
  PanicData,
  PanicCandidate,
  ReboundCandidate,
  LHBRow,
  LHBFrequencyRow,
  SectorRow,
  SleeveOverlap,
  HistoryEntry,
} from '../types';

type Column<T> = ColumnDef<T>;

// ── helpers ──────────────────────────────────────────────────────────────

function fmtPct(v: number): string {
  const sign = v >= 0 ? '+' : '';
  return `${sign}${(v * 100).toFixed(2)}%`;
}

function fmtYuan(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1e8) return `${(v / 1e8).toFixed(2)} 亿`;
  if (abs >= 1e4) return `${(v / 1e4).toFixed(0)} 万`;
  return v.toFixed(0);
}

function colorPct(v: number): string {
  if (v > 0) return 'text-[#30d158]';
  if (v < 0) return 'text-[#ff453a]';
  return '';
}

function negColorPct(v: number): string {
  if (v < 0) return 'text-[#ff453a]'; // negative = red (drop)
  if (v > 0) return 'text-[#30d158]';
  return '';
}

// ── column defs ──────────────────────────────────────────────────────────

const panicColumns: Column<PanicCandidate>[] = [
  { key: 'code', header: '代码', render: (r) => <span className="font-semibold">{r.code}</span> },
  { key: 'universe', header: 'universe', render: (r) => r.universe },
  {
    key: 'drop_pct',
    header: '跌幅',
    render: (r) => <span className={`font-semibold ${negColorPct(r.drop_pct)}`}>{fmtPct(r.drop_pct)}</span>,
  },
  { key: 'vol_ratio', header: '量比', render: (r) => r.vol_ratio.toFixed(1) },
  { key: 'close', header: '收盘', render: (r) => r.close.toFixed(2) },
  {
    key: 'dd',
    header: '距20日高',
    render: (r) => <span className={negColorPct(r.dd_from_20d_high)}>{fmtPct(r.dd_from_20d_high)}</span>,
  },
];

const reboundColumns: Column<ReboundCandidate>[] = [
  { key: 'code', header: '代码', render: (r) => <span className="font-semibold">{r.code}</span> },
  {
    key: 'prior_drop',
    header: '前日跌幅',
    render: (r) => <span className="text-[#ff453a] font-semibold">{fmtPct(r.prior_drop_pct)}</span>,
  },
  { key: 'prior_vol', header: '前日量比', render: (r) => r.prior_vol_ratio.toFixed(1) },
  {
    key: 'gap',
    header: '今日开盘跳空',
    render: (r) => <span className={`font-semibold ${colorPct(r.today_open_vs_prior_close)}`}>{fmtPct(r.today_open_vs_prior_close)}</span>,
  },
];

const lhbColumns: Column<LHBRow>[] = [
  { key: 'code', header: '代码', render: (r) => <span className="font-semibold">{r.code}</span> },
  { key: 'name', header: '名称', render: (r) => r.name || '—' },
  { key: 'date', header: '日期', render: (r) => r.date },
  {
    key: 'jg_buy',
    header: '机构净买',
    render: (r) => <span className={r.jg_net_buy_yuan > 0 ? 'text-[#30d158] font-semibold' : 'text-[#ff453a] font-semibold'}>{fmtYuan(r.jg_net_buy_yuan)}</span>,
  },
  {
    key: 'pct',
    header: '涨跌幅',
    render: (r) => <span className={`font-semibold ${colorPct(r.pct_change ?? 0)}`}>{r.pct_change != null ? fmtPct(r.pct_change / 100) : '—'}</span>,
  },
  { key: 'reason', header: '上榜原因', render: (r) => <span className="text-xs text-[#86868b]">{r.reason}</span> },
];

const lhbFreqColumns: Column<LHBFrequencyRow>[] = [
  { key: 'code', header: '代码', render: (r) => <span className="font-semibold">{r.code}</span> },
  { key: 'name', header: '名称', render: (r) => r.name },
  { key: 'appearances', header: '上榜次数', render: (r) => <span className="font-bold text-[#ff9f0a]">{r.appearances}</span> },
  {
    key: 'total',
    header: '累计机构净买',
    render: (r) => <span className={r.total_jg_net_buy_yuan > 0 ? 'text-[#30d158]' : 'text-[#ff453a]'}>{fmtYuan(r.total_jg_net_buy_yuan)}</span>,
  },
  { key: 'last_date', header: '最后上榜', render: (r) => r.last_date },
];

const sectorColumns: Column<SectorRow>[] = [
  { key: 'name', header: '板块', render: (r) => <span className="font-semibold">{r.name}</span> },
  {
    key: 'pct',
    header: '涨跌幅',
    render: (r) => <span className={`font-semibold ${colorPct(r.pct_change)}`}>{fmtPct(r.pct_change)}</span>,
  },
  { key: 'stock', header: '代表股', render: (r) => r.representative_stock },
  {
    key: 'stock_pct',
    header: '涨幅',
    render: (r) => <span className={colorPct(r.representative_pct ?? 0)}>{r.representative_pct != null ? fmtPct(r.representative_pct) : '—'}</span>,
  },
];

// ── sub-components ───────────────────────────────────────────────────────

function SectionTitle({ num, title }: { num: string; title: string }) {
  return (
    <div className="text-sm font-semibold text-[#1d1d1f] mb-2 flex items-center gap-1.5">
      <span className="text-[#86868b] text-xs">{num}</span> {title}
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return <div className="text-center py-6 text-[#aeaeb2] text-sm">{text}</div>;
}

function OverlapBadge({ codes }: { codes: string[] }) {
  if (codes.length === 0) return <span className="text-[#aeaeb2] text-xs">无重叠</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {codes.map((c) => (
        <span key={c} className="inline-flex px-1.5 py-0.5 bg-[#ffe8e6] text-[#c0392b] text-[11px] font-semibold rounded">
          {c}
        </span>
      ))}
    </div>
  );
}

function MiniBar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  const color = value >= 3 ? 'bg-[#ff453a]' : value >= 1 ? 'bg-[#ff9f0a]' : 'bg-[#30d158]';
  return (
    <div className="w-full bg-[#e5e5ea] rounded-full h-1.5">
      <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export default function PanicSection({ data }: { data: PanicData }) {
  const panic = data.panic || [];
  const rebound = data.rebound || [];
  const lhb = data.lhb || [];
  const sentiment = data.sentiment || [];
  const overlaps = data.sleeve_overlap || [];
  const sectors = data.sectors || { industry_top: [], industry_bot: [], concept_top: [], concept_bot: [] };
  const lhbFreq = data.lhb_frequency || [];
  const history = data.history || [];

  const hasAnyData = panic.length > 0 || rebound.length > 0 || lhb.length > 0
    || sentiment.length > 0 || overlaps.length > 0 || lhbFreq.length > 0
    || sectors.industry_top.length > 0 || sectors.concept_top.length > 0
    || history.length > 0;

  if (!hasAnyData) {
    return (
      <section className="mb-12 animate-fadeIn">
        <GlassCard>
          <div className="text-center py-12 text-[#aeaeb2]">
            暂无恐慌/情绪数据，请运行 <code className="bg-[#f0f0f2] px-1.5 py-0.5 rounded text-sm">python scripts/reporting/daily_panic_dashboard.py</code>
          </div>
        </GlassCard>
      </section>
    );
  }

  const maxPanicInHistory = Math.max(...history.map((h) => h.panic_count), 1);

  return (
    <section className="mb-12 animate-fadeIn space-y-3">
      {/* ① Panic candidates */}
      <GlassCard>
        <SectionTitle num="①" title="Panic 候选 · 急跌放量" />
        {panic.length > 0 ? (
          <>
            <MetricGrid>
              <MetricCard label="Panic 候选" value={panic.length} sub="HS300 急跌+放量" colorClass={panic.length > 0 ? 'text-[#ff453a]' : ''} />
              <MetricCard label="最大跌幅" value={fmtPct(Math.min(...panic.map((p) => p.drop_pct)))} sub="" colorClass="text-[#ff453a]" />
              <MetricCard label="最高量比" value={Math.max(...panic.map((p) => p.vol_ratio)).toFixed(1)} sub="vs 20日均量" />
              <MetricCard label="生成时间" value={data.generated_at?.split(' ')[1] || '—'} sub={data.generated_at?.split(' ')[0] || ''} />
            </MetricGrid>
            <DataTable columns={panicColumns} data={panic} emptyText="" />
          </>
        ) : (
          <EmptyState text="今日无 panic 候选" />
        )}
      </GlassCard>

      {/* ② Rebound candidates */}
      <GlassCard>
        <SectionTitle num="②" title="反包候选 · 前日 panic + 今日高开" />
        {rebound.length > 0 ? (
          <DataTable columns={reboundColumns} data={rebound} emptyText="" />
        ) : (
          <EmptyState text="今日无反包候选" />
        )}
      </GlassCard>

      {/* ③ LHB 机构净买 TOP 20 */}
      <GlassCard>
        <SectionTitle num="③" title="LHB 机构净买 TOP 20" />
        {lhb.length > 0 ? (
          <>
            <MetricGrid>
              <MetricCard label="上榜数" value={lhb.length} sub="近 5 个交易日" />
              <MetricCard label="最大净买" value={fmtYuan(Math.max(...lhb.map((r) => r.jg_net_buy_yuan)))} sub="" colorClass="text-[#30d158]" />
            </MetricGrid>
            <DataTable columns={lhbColumns} data={lhb} emptyText="" />
          </>
        ) : (
          <EmptyState text="今日无 LHB 数据" />
        )}
      </GlassCard>

      {/* ④ Market sentiment */}
      <GlassCard>
        <SectionTitle num="④" title="大盘情绪 · 关键词扫描" />
        {sentiment.length > 0 ? (
          <div className="space-y-3">
            {sentiment.map((s) => (
              <div key={s.source} className="bg-[#f5f5f7] rounded-xl p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-[#1d1d1f]">{s.source}</span>
                  <span className={`text-xs font-bold ${s.score < -0.2 ? 'text-[#ff453a]' : s.score > 0.2 ? 'text-[#30d158]' : 'text-[#86868b]'}`}>
                    净情绪 {(s.score * 100).toFixed(0)}%
                  </span>
                </div>
                <MetricGrid>
                  <MetricCard label="扫描条数" value={s.n_items} sub="" />
                  <MetricCard label="看多" value={s.n_bull} sub="" colorClass="text-[#30d158]" />
                  <MetricCard label="看空" value={s.n_bear} sub="" colorClass="text-[#ff453a]" />
                  <MetricCard label="情绪分" value={(s.score).toFixed(3)} sub="(bull-bear)/total" colorClass={s.score < 0 ? 'text-[#ff453a]' : 'text-[#30d158]'} />
                </MetricGrid>
                {s.samples_bull.length > 0 && (
                  <div className="mt-1 text-[11px] text-[#30d158]">多: {s.samples_bull.slice(0, 5).join(', ')}</div>
                )}
                {s.samples_bear.length > 0 && (
                  <div className="mt-0.5 text-[11px] text-[#ff453a]">空: {s.samples_bear.slice(0, 5).join(', ')}</div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <EmptyState text="无情绪数据（--quick 模式跳过 news fetch）" />
        )}
      </GlassCard>

      {/* ⑤ Sleeve overlap */}
      <GlassCard>
        <SectionTitle num="⑤" title="Sleeve 重叠 · panic/rebound vs 活跃策略" />
        {overlaps.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#e5e5ea]">
                  <th className="text-left py-2 px-2 text-[#86868b] font-medium">Sleeve</th>
                  <th className="text-left py-2 px-2 text-[#86868b] font-medium">候选数</th>
                  <th className="text-left py-2 px-2 text-[#86868b] font-medium">重叠 Panic</th>
                  <th className="text-left py-2 px-2 text-[#86868b] font-medium">重叠 Rebound</th>
                </tr>
              </thead>
              <tbody>
                {overlaps.map((o) => (
                  <tr key={o.sleeve} className="border-b border-[#f0f0f2]">
                    <td className="py-2 px-2 font-semibold">{o.sleeve}</td>
                    <td className="py-2 px-2">{o.candidates.length}</td>
                    <td className="py-2 px-2"><OverlapBadge codes={o.overlap_with_panic} /></td>
                    <td className="py-2 px-2"><OverlapBadge codes={o.overlap_with_rebound} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState text="无 sleeve 数据" />
        )}
      </GlassCard>

      {/* ⑥ Sector rankings */}
      <GlassCard>
        <SectionTitle num="⑥" title="板块涨跌 · 行业/概念 TOP & BOTTOM 5" />
        {(sectors.industry_top.length > 0 || sectors.concept_top.length > 0) ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* 行业 */}
            <div>
              <div className="text-xs font-medium text-[#86868b] mb-2">行业板块</div>
              {sectors.industry_top.length > 0 && (
                <div className="mb-2">
                  <div className="text-[11px] text-[#30d158] mb-1">TOP 5</div>
                  <DataTable columns={sectorColumns} data={sectors.industry_top} emptyText="" />
                </div>
              )}
              {sectors.industry_bot.length > 0 && (
                <div>
                  <div className="text-[11px] text-[#ff453a] mb-1">BOTTOM 5</div>
                  <DataTable columns={sectorColumns} data={sectors.industry_bot} emptyText="" />
                </div>
              )}
              {sectors.industry_top.length === 0 && sectors.industry_bot.length === 0 && (
                <EmptyState text="无行业数据" />
              )}
            </div>
            {/* 概念 */}
            <div>
              <div className="text-xs font-medium text-[#86868b] mb-2">概念板块</div>
              {sectors.concept_top.length > 0 && (
                <div className="mb-2">
                  <div className="text-[11px] text-[#30d158] mb-1">TOP 5</div>
                  <DataTable columns={sectorColumns} data={sectors.concept_top} emptyText="" />
                </div>
              )}
              {sectors.concept_bot.length > 0 && (
                <div>
                  <div className="text-[11px] text-[#ff453a] mb-1">BOTTOM 5</div>
                  <DataTable columns={sectorColumns} data={sectors.concept_bot} emptyText="" />
                </div>
              )}
              {sectors.concept_top.length === 0 && sectors.concept_bot.length === 0 && (
                <EmptyState text="无概念数据" />
              )}
            </div>
          </div>
        ) : (
          <EmptyState text="无板块数据" />
        )}
      </GlassCard>

      {/* ⑦ LHB frequency */}
      <GlassCard>
        <SectionTitle num="⑦" title="LHB 高频上榜 · 近 30 天 ≥2 次" />
        {lhbFreq.length > 0 ? (
          <>
            <MetricGrid>
              <MetricCard label="高频股数" value={lhbFreq.length} sub="上榜 ≥2 次" />
              <MetricCard label="最高频次" value={Math.max(...lhbFreq.map((r) => r.appearances))} sub="" colorClass={Math.max(...lhbFreq.map((r) => r.appearances)) >= 5 ? 'text-[#ff453a]' : 'text-[#ff9f0a]'} />
            </MetricGrid>
            <DataTable columns={lhbFreqColumns} data={lhbFreq} emptyText="" />
          </>
        ) : (
          <EmptyState text="无高频上榜股（近 30 天无 ≥2 次上榜）" />
        )}
      </GlassCard>

      {/* ⑧ History trend */}
      <GlassCard>
        <SectionTitle num="⑧" title="Panic 历史趋势 · 近 60 天" />
        {history.length > 0 ? (
          <div className="space-y-1.5">
            <div className="grid grid-cols-[auto_1fr_auto] gap-2 items-center text-xs">
              {history.slice(-30).map((h: HistoryEntry) => (
                <div key={h.date} className="contents">
                  <span className="text-[#86868b] w-20 text-right">{h.date.slice(5)}</span>
                  <MiniBar value={h.panic_count} max={maxPanicInHistory} />
                  <span className={`w-16 text-right font-semibold ${h.panic_count >= 5 ? 'text-[#ff453a]' : h.panic_count >= 2 ? 'text-[#ff9f0a]' : 'text-[#30d158]'}`}>
                    {h.panic_count} panic
                    {h.rebound_count > 0 && <span className="ml-1 text-[#30d158]">{h.rebound_count}↑</span>}
                  </span>
                </div>
              ))}
            </div>
            <div className="text-[11px] text-[#86868b] mt-2 flex justify-between">
              <span>最早: {history[0]?.date || '—'}</span>
              <span>今日: {history[history.length - 1]?.panic_count || 0} panic · {history[history.length - 1]?.rebound_count || 0} rebound</span>
            </div>
          </div>
        ) : (
          <EmptyState text="首次采集，历史数据将在下次运行时积累" />
        )}
      </GlassCard>
    </section>
  );
}
