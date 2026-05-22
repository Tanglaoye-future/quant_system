import GlassCard from './GlassCard';
import MetricGrid from './MetricGrid';
import MetricCard from './MetricCard';
import StatusBadge from './StatusBadge';
import type { QuantData, OptionsData, ZhuangData } from '../types';

function fmtPct(v: number | null): string {
  if (v === null || v === undefined) return '—';
  const sign = v >= 0 ? '+' : '';
  return `${sign}${(v * 100).toFixed(2)}%`;
}

function colorPnl(v: number | null): string {
  if (v === null || v === undefined) return '';
  if (v > 0) return 'text-[#30d158]';
  if (v < 0) return 'text-[#ff453a]';
  return 'text-[#1d1d1f]';
}

export default function SystemStatusBar({
  quant,
  options,
  zhuang,
}: {
  quant: QuantData;
  options: OptionsData;
  zhuang: ZhuangData;
}) {
  const quantMissing = quant._missing;
  const optMissing = options._missing;
  const zhuangMissing = zhuang._missing;

  const qSignals = quant.signals?.length ?? 0;
  const qPositions = quant.positions?.length ?? 0;
  const qGate = quant.market_gate;
  const qBadge = qSignals > 0 ? 'pass' : 'idle';

  const oSignal = options.signal;
  const oBadge = oSignal ? 'pass' : 'idle';

  const zCount = zhuang.candidates_count ?? 0;
  const zMax = zhuang.top_candidates?.[0]?.total ?? 0;
  const zBadge = zCount > 0 ? 'info' : 'idle';

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-10 animate-fadeIn">
      <GlassCard>
        <div className="flex items-center justify-between mb-3">
          <div className="text-xs font-semibold text-[#86868b] uppercase tracking-wider">
            quant · A 股中线
          </div>
          <StatusBadge
            label={quantMissing ? '无数据' : qSignals > 0 ? `${qSignals} 信号` : '待机'}
            variant={quantMissing ? 'idle' : qBadge}
          />
        </div>
        <div className="text-sm text-[#1d1d1f] leading-relaxed">
          {quantMissing ? (
            '暂无数据，请运行 daily 脚本'
          ) : (
            <>
              市况门{qGate ? '通过' : '关闭'} · {qSignals} 只买入信号
              <br />
              持仓 {qPositions} 只 · HS300
            </>
          )}
        </div>
      </GlassCard>

      <GlassCard>
        <div className="flex items-center justify-between mb-3">
          <div className="text-xs font-semibold text-[#86868b] uppercase tracking-wider">
            options · QQQ 期权
          </div>
          <StatusBadge
            label={optMissing ? '无数据' : oSignal ? '有信号' : '待机'}
            variant={optMissing ? 'idle' : oBadge}
          />
        </div>
        <div className="text-sm text-[#1d1d1f] leading-relaxed">
          {optMissing ? (
            '暂无数据，请运行 daily 脚本'
          ) : (
            <>
              IVR {options.ivr?.toFixed(1) ?? '—'} · {options.iv_mode ?? '—'} · QQQ $
              {options.qqq_price?.toFixed(2) ?? '—'}
              <br />
              RSI {options.qqq_rsi?.toFixed(1) ?? '—'} · {options.reason?.slice(0, 30) ?? '—'}
            </>
          )}
        </div>
      </GlassCard>

      <GlassCard>
        <div className="flex items-center justify-between mb-3">
          <div className="text-xs font-semibold text-[#86868b] uppercase tracking-wider">
            zhuang · 庄股小盘
          </div>
          <StatusBadge
            label={zhuangMissing ? '无数据' : `${zCount} 候选`}
            variant={zhuangMissing ? 'idle' : zBadge}
          />
        </div>
        <div className="text-sm text-[#1d1d1f] leading-relaxed">
          {zhuangMissing ? (
            '暂无数据，请运行 daily 脚本'
          ) : (
            <>
              Universe {zhuang.universe_size ?? '—'} 只 · 候选 {zCount} 只
              <br />
              最高分 {zMax.toFixed(1)} · 门槛 65
            </>
          )}
        </div>
      </GlassCard>
    </div>
  );
}
