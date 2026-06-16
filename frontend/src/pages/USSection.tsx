import GlassCard from '../components/GlassCard';
import MetricGrid from '../components/MetricGrid';
import MetricCard from '../components/MetricCard';
import StatusBadge from '../components/StatusBadge';
import type { OptionsData } from '../types';

function rsiColor(rsi: number): string {
  if (rsi > 75) return 'text-[#ff453a]';
  if (rsi > 65) return 'text-[#ff9f0a]';
  return 'text-[#30d158]';
}

function StrategySection({ name, status, children }: { name: string; status: 'active' | 'idle' | 'signal'; children: React.ReactNode }) {
  const variant = status === 'signal' ? 'pass' : status === 'active' ? 'pass' : 'idle';
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

export default function USSection({ data }: { data: OptionsData }) {
  if (data._missing) {
    return (
      <section className="mb-12 animate-fadeIn">
        <GlassCard>
          <div className="text-center py-12 text-[#aeaeb2]">
            暂无数据，请运行 <code className="bg-[#f0f0f2] px-1.5 py-0.5 rounded text-sm">python scripts/daily/daily_options.py</code>
          </div>
        </GlassCard>
      </section>
    );
  }

  const { signal } = data;
  const status = signal ? ('signal' as const) : (data.qqq_bullish ? ('active' as const) : ('idle' as const));
  const gradeColor = data.signal_grade === 'D' ? 'text-[#ff453a]' : data.signal_grade === 'A' ? 'text-[#30d158]' : 'text-[#ff9f0a]';
  const modeColor = data.iv_mode?.startsWith('HIGH') ? 'text-[#ff453a]' : 'text-[#30d158]';

  return (
    <section className="mb-12 animate-fadeIn">
      <StrategySection name="期权 Bull Call Spread" status={status}>
        <MetricGrid>
          <MetricCard label="VXN / IVR" value={data.ivr?.toFixed(1) ?? '—'} sub={data.iv_mode ?? '—'} colorClass={modeColor} />
          <MetricCard label="QQQ 价格" value={`$${data.qqq_price?.toFixed(2) ?? '—'}`} sub={`MA200: $${data.qqq_ma200?.toFixed(0) ?? '—'}`} colorClass="text-[#0071e3]" />
          <MetricCard label="RSI (14)" value={data.qqq_rsi?.toFixed(1) ?? '—'} sub={data.qqq_rsi > 75 ? '⚠ 超买' : '正常'} colorClass={rsiColor(data.qqq_rsi)} />
          <MetricCard label="信号评级" value={data.signal_grade ?? '—'} sub={data.qqq_bullish ? '看涨' : '趋势不足'} colorClass={gradeColor} />
        </MetricGrid>

        <div className="bg-[#f5f5f7] rounded-xl p-4 space-y-2 text-sm">
          <div className="flex justify-between py-1.5 border-b border-[#e5e5ea]">
            <span className="text-[#86868b]">IV 状态</span>
            <span className={modeColor}>{data.iv_mode} · IVR {data.ivr?.toFixed(1)}</span>
          </div>
          <div className="flex justify-between py-1.5 border-b border-[#e5e5ea]">
            <span className="text-[#86868b]">QQQ 趋势</span>
            <span className="text-[#30d158]">{data.qqq_bullish ? '上升趋势中' : '趋势未确认'}</span>
          </div>
          <div className="flex justify-between py-1.5 border-b border-[#e5e5ea]">
            <span className="text-[#86868b]">不操作原因</span>
            <span className="text-[#ff453a]">{data.reason || '—'}</span>
          </div>
          <div className="flex justify-between py-1.5">
            <span className="text-[#86868b]">今日结论</span>
            <span className={signal ? 'text-[#30d158] font-semibold' : 'text-[#ff9f0a]'}>
              {signal ? '有信号' : '无信号 · 继续观察'}
            </span>
          </div>
        </div>

        {signal && (
          <div className="mt-4 bg-[#f5f5f7] rounded-xl p-4 border border-[#e5e5ea]">
            <div className="text-sm font-semibold text-[#30d158] mb-2">今日信号：{signal.type}</div>
            <div className="space-y-1.5 text-xs">
              <div className="flex justify-between"><span className="text-[#86868b]">结构</span><span>{signal.structure}</span></div>
              <div className="flex justify-between"><span className="text-[#86868b]">买腿</span><span>{signal.buy_leg}</span></div>
              <div className="flex justify-between"><span className="text-[#86868b]">卖腿</span><span>{signal.sell_leg}</span></div>
              <div className="flex justify-between"><span className="text-[#86868b]">最大盈利</span><span className="text-[#30d158] font-semibold">{signal.max_profit}</span></div>
              <div className="flex justify-between"><span className="text-[#86868b]">最大亏损</span><span className="text-[#ff453a] font-semibold">{signal.max_loss}</span></div>
            </div>
          </div>
        )}
      </StrategySection>

      {/* INACTIVE_STRATEGIES_HIDE 2026-06-16: 美股中线 momentum 已归档 (Sharpe 0.2), 不再展示. */}
      {/*
      <GlassCard className="mb-4 opacity-60">
        <div className="flex items-center justify-between mb-3">
          <div className="text-sm font-semibold text-[#aeaeb2]">中线 momentum</div>
          <StatusBadge label="已归档" variant="idle" />
        </div>
        <div className="text-xs text-[#aeaeb2]">美股主动策略已关闭（Sharpe 仅 0.2），由被动 QQQ 替代。</div>
      </GlassCard>
      */}
    </section>
  );
}
