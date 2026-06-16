import GlassCard from '../components/GlassCard';
import MetricGrid from '../components/MetricGrid';
import MetricCard from '../components/MetricCard';
import DataTable from '../components/DataTable';
import StatusBadge from '../components/StatusBadge';
// ZHUANG_DEPRECATED 2026-06-14: ZhuangCandidate/ZhuangPosition 仅 zhuang section 内部用, 已注释.
import type { ColumnDef, QuantData, QuantSignal, QuantPosition, ZhuangData /*, ZhuangCandidate, ZhuangPosition */ } from '../types';

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

// ZHUANG_DEPRECATED 2026-06-14: 整段 zhuang 列定义注释, 仅 zhuang section JSX 内部使用.
/*
function zhuangActionStyle(action: string): string {
  if (action === '卖出') return 'bg-[#ffe8e6] text-[#c0392b]';
  if (action === '建仓') return 'bg-[#e6f0ff] text-[#0050b3]';
  return 'bg-[#e5f9e8] text-[#1a7f37]';
}

const zhuangPositionColumns: Column<ZhuangPosition>[] = [
  { key: 'code', header: '代码', render: (r) => <span className="font-semibold">{r.code}</span> },
  { key: 'entry_date', header: '入场日', render: (r) => r.entry_date || '—' },
  { key: 'hold_days', header: '持有天', render: (r) => (r.hold_days != null ? `${r.hold_days} 天` : '—') },
  { key: 'pnl_pct', header: '浮盈', render: (r) => <span className={`font-semibold ${colorPnl(r.pnl_pct)}`}>{fmtPct(r.pnl_pct)}</span> },
  {
    key: 'action',
    header: '操作',
    render: (r) => <span className={`inline-flex px-2 py-0.5 text-[11px] font-semibold rounded-md ${zhuangActionStyle(r.action)}`}>{r.action || '持有'}</span>,
  },
];

const zhuangColumns: Column<ZhuangCandidate>[] = [
  { key: 'rank', header: '#', render: (_, i) => <span className="text-[#86868b]">{i + 1}</span>, className: 'w-8' },
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
*/

interface StrategySectionProps {
  name: string;
  status: 'active' | 'idle' | 'signal';
  children: React.ReactNode;
}

function StrategySection({ name, status, children }: StrategySectionProps) {
  const variant = status === 'active' || status === 'signal' ? 'pass' : 'idle';
  const label = status === 'signal' ? '有信号' : status === 'active' ? '活跃' : '待机';
  return (
    <GlassCard className="mb-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm font-semibold text-[#1d1d1f]">{name}</div>
        <StatusBadge label={label} variant={variant} />
      </div>
      {children}
    </GlassCard>
  );
}

// ZHUANG_DEPRECATED 2026-06-14: zhuang prop 仍接收以兼容调用方 type, 但内部不消费.
export default function AShareSection({ quant, zhuang: _zhuang }: { quant: QuantData; zhuang: ZhuangData }) {
  const aSignals = (quant.signals || []).filter((s) => s._source?.startsWith('A 股'));
  const aPositions = (quant.positions || []).filter((p) => p._source?.startsWith('A 股'));

  const momSignals = aSignals.filter((s) => s._source === 'A 股 · momentum');
  const momPositions = aPositions.filter((p) => p._source === 'A 股 · momentum');
  const mrSignals = aSignals.filter((s) => s._source === 'A 股 · mean-reversion');
  const mrPositions = aPositions.filter((p) => p._source === 'A 股 · mean-reversion');

  const gateOk = quant.market_gate;
  const gateLabel = gateOk === true ? '通过' : gateOk === false ? '关闭' : '—';
  const gateColor = gateOk ? 'text-[#30d158]' : 'text-[#ff453a]';

  const momStatus = momSignals.length > 0 ? 'active' as const : 'idle' as const;
  const mrStatus = mrSignals.length > 0 ? 'active' as const : 'idle' as const;
  // ZHUANG_DEPRECATED 2026-06-14:
  // const zhuangPositions = _zhuang.positions || [];
  // const zhuangStatus = ((_zhuang.candidates_count ?? 0) > 0 || zhuangPositions.length > 0) ? 'active' as const : 'idle' as const;

  if (quant._missing) {
    return (
      <section className="mb-12 animate-fadeIn">
        <GlassCard>
          <div className="text-center py-12 text-[#aeaeb2]">
            暂无数据，请运行 <code className="bg-[#f0f0f2] px-1.5 py-0.5 rounded text-sm">python scripts/daily/daily_equity.py</code>
          </div>
        </GlassCard>
      </section>
    );
  }

  return (
    <section className="mb-12 animate-fadeIn">
      {/* 中线 momentum */}
      {!quant._missing && (
        <StrategySection name="中线 momentum" status={momStatus}>
          <MetricGrid>
            <MetricCard label="M2 市况门" value={gateLabel} sub={quant.market_gate_msg || 'HS300 MA60'} colorClass={gateColor} />
            <MetricCard label="买入信号" value={momSignals.length} sub="今日候选" colorClass={momSignals.length > 0 ? 'text-[#0071e3]' : ''} />
            <MetricCard label="当前持仓" value={momPositions.length} sub="最大 6 仓" />
            <MetricCard label="HS300" value={quant.benchmark_close} sub={`MA60: ${quant.benchmark_ma60}`} />
          </MetricGrid>
          {momSignals.length > 0 && (
            <div className="mb-3">
              <div className="text-xs font-medium text-[#86868b] mb-2">买入候选</div>
              <DataTable columns={signalColumns} data={momSignals} emptyText="今日无买入信号" />
            </div>
          )}
          {momPositions.length > 0 && (
            <div>
              <div className="text-xs font-medium text-[#86868b] mb-2">当前持仓</div>
              <DataTable columns={positionColumns} data={momPositions} emptyText="当前空仓" />
            </div>
          )}
          {momSignals.length === 0 && momPositions.length === 0 && (
            <div className="text-center py-6 text-[#aeaeb2] text-sm">今日无信号，无持仓</div>
          )}
        </StrategySection>
      )}

      {/* 中线 mean-reversion */}
      {!quant._missing && (
        <StrategySection name="中线 mean-reversion" status={mrStatus}>
          <MetricGrid>
            <MetricCard label="买入信号" value={mrSignals.length} sub="今日候选" colorClass={mrSignals.length > 0 ? 'text-[#0071e3]' : ''} />
            <MetricCard label="当前持仓" value={mrPositions.length} sub="无仓位上限" />
            <MetricCard label="HS300" value={quant.benchmark_close} sub={`MA60: ${quant.benchmark_ma60}`} />
            <MetricCard label="数据日期" value={quant.date || '—'} sub="" />
          </MetricGrid>
          {mrSignals.length > 0 && (
            <div className="mb-3">
              <div className="text-xs font-medium text-[#86868b] mb-2">买入候选</div>
              <DataTable columns={signalColumns} data={mrSignals} emptyText="今日无买入信号" />
            </div>
          )}
          {mrPositions.length > 0 && (
            <div>
              <div className="text-xs font-medium text-[#86868b] mb-2">当前持仓</div>
              <DataTable columns={positionColumns} data={mrPositions} emptyText="当前空仓" />
            </div>
          )}
          {mrSignals.length === 0 && mrPositions.length === 0 && (
            <div className="text-center py-6 text-[#aeaeb2] text-sm">今日无信号，无持仓</div>
          )}
        </StrategySection>
      )}

      {/* ZHUANG_DEPRECATED 2026-06-14: 庄股跟庄已弃用 (违反北极星支柱 1+2)，详见 memory/zhuang_deprecated_2026-06.md */}
      {/*
      {!_zhuang._missing && (
        <StrategySection name="庄股跟庄" status={zhuangStatus}>
          <MetricGrid>
            <MetricCard label="当前持仓" value={zhuangPositions.length} sub="最大 6 仓" colorClass={zhuangPositions.length > 0 ? 'text-[#0071e3]' : ''} />
            <MetricCard label="候选数" value={_zhuang.candidates_count ?? 0} sub="≥45 分" colorClass={(_zhuang.candidates_count ?? 0) > 0 ? 'text-[#0071e3]' : ''} />
            <MetricCard label="最高评分" value={(_zhuang.top_candidates?.[0]?.total ?? 0).toFixed(1)} sub={(_zhuang.top_candidates?.[0]?.total ?? 0) >= 65 ? '达标' : '门槛 65'} colorClass={(_zhuang.top_candidates?.[0]?.total ?? 0) >= 65 ? 'text-[#30d158]' : 'text-[#ff9f0a]'} />
            <MetricCard label="市场趋势" value={_zhuang.market_trend === null || _zhuang.market_trend === undefined ? '—' : _zhuang.market_trend ? '金叉 OK' : '未达'} sub="CSI500 MA60" colorClass={_zhuang.market_trend ? 'text-[#30d158]' : 'text-[#ff453a]'} />
          </MetricGrid>
          {zhuangPositions.length > 0 && (
            <div className="mb-3">
              <div className="text-xs font-medium text-[#86868b] mb-2">当前持仓（出场为 advisory 建议）</div>
              <DataTable columns={zhuangPositionColumns} data={zhuangPositions} emptyText="当前空仓" />
            </div>
          )}
          {(_zhuang.top_candidates || []).length > 0 && (
            <>
              <div className="text-xs font-medium text-[#86868b] mb-2">吃货期候选 · TOP 15</div>
              <DataTable columns={zhuangColumns} data={_zhuang.top_candidates || []} emptyText="无候选" />
              <div className="mt-3 text-xs text-[#86868b] leading-relaxed">
                权重：MA 收敛 ×0.20 · 量价不对称 ×0.30 · 价格横盘 ×0.20 · 换手下降 ×0.15 · 量价背离 ×0.15
              </div>
            </>
          )}
          {zhuangPositions.length === 0 && (_zhuang.top_candidates || []).length === 0 && (
            <div className="text-center py-6 text-[#aeaeb2] text-sm">今日无候选，无持仓</div>
          )}
        </StrategySection>
      )}
      */}
    </section>
  );
}
