import type { TSignalEvent, TSignalsPayload } from '../types';
import GlassCard from './GlassCard';

// 持仓中日内做 T 信号 dashboard 卡片 (spec docs/specs/intraday_t_execution_a_share.md PR5)
// 默认 yaml disabled → API 返 today=[], history=[] → 卡片显示 "未启用 / 0 信号" 不影响布局
//
// 6 条不变量在视觉上反映:
//   - SELL/BUY 严格区分颜色
//   - qty_ratio % 显示 (永远 20-70% 之间)
//   - confidence 三档 high/medium/low
//   - advisory only 提示 banner

function pct(v: number | null | undefined, digits = 2): string {
  if (v == null || isNaN(v)) return '—';
  return `${(v * 100).toFixed(digits)}%`;
}

function fmtPrice(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return '—';
  return v.toFixed(2);
}

function fmtTime(iso: string | null): string {
  if (!iso) return '—';
  // "2026-06-15T10:23:45+08:00" → "10:23"
  const m = iso.match(/T(\d{2}):(\d{2})/);
  return m ? `${m[1]}:${m[2]}` : iso;
}

function sideColor(side: string | null): string {
  if (side === 'SELL') return 'text-rose-600 dark:text-rose-400';
  if (side === 'BUY') return 'text-emerald-600 dark:text-emerald-400';
  return 'text-zinc-500';
}

function sideBg(side: string | null): string {
  if (side === 'SELL') return 'bg-rose-50 dark:bg-rose-950/40 border-rose-200 dark:border-rose-800';
  if (side === 'BUY') return 'bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-800';
  return 'bg-zinc-50 dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800';
}

function confidenceBadge(c: string | null): { label: string; cls: string } {
  if (c === 'high') return { label: 'high', cls: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200' };
  if (c === 'medium') return { label: 'medium', cls: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200' };
  if (c === 'low') return { label: 'low', cls: 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300' };
  return { label: '—', cls: 'bg-zinc-100 text-zinc-700' };
}

function SignalRow({ ev }: { ev: TSignalEvent }) {
  const cb = confidenceBadge(ev.confidence);
  return (
    <div className={`border rounded-lg p-3 ${sideBg(ev.side)}`}>
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span className={`font-bold ${sideColor(ev.side)}`}>{ev.side ?? '—'}</span>
          <span className="font-mono text-sm">{ev.symbol ?? '—'}</span>
          <span className="text-xs text-zinc-500">({ev.strategy_name})</span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className={`px-2 py-0.5 rounded ${cb.cls}`}>{cb.label}</span>
          <span className="text-zinc-500">{fmtTime(ev.asof_ts)}</span>
        </div>
      </div>
      <div className="flex items-center gap-4 text-sm">
        <span>价 <span className="font-mono">{fmtPrice(ev.suggested_price)}</span></span>
        <span>qty <span className="font-mono font-medium">{pct(ev.qty_ratio, 0)}</span></span>
        {!ev.delivered && (
          <span className="text-xs text-amber-600 dark:text-amber-400">⚠ 未送达</span>
        )}
      </div>
      {ev.reason && (
        <div className="text-xs text-zinc-600 dark:text-zinc-400 mt-1 font-mono">
          {ev.reason}
        </div>
      )}
    </div>
  );
}

export default function TSignalCard({ data }: { data: TSignalsPayload | null }) {
  const today = data?.today ?? [];
  const history = data?.history ?? [];
  const sells = today.filter(e => e.side === 'SELL').length;
  const buys = today.filter(e => e.side === 'BUY').length;

  return (
    <GlassCard>
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-lg font-semibold">日内做 T 信号</h3>
          <p className="text-xs text-zinc-500">
            advisory only — A 股持仓内高抛低吸 (Backstop #4 人工下单)
          </p>
        </div>
        <div className="text-right text-xs text-zinc-500">
          今日 SELL <span className="font-mono text-rose-600 dark:text-rose-400">{sells}</span>
          {' / '}
          BUY <span className="font-mono text-emerald-600 dark:text-emerald-400">{buys}</span>
        </div>
      </div>

      {today.length === 0 && history.length === 0 && (
        <div className="text-sm text-zinc-500 py-4 text-center">
          0 T 信号 — 检查 config/intraday.yaml::t_signals.enabled 是否开启
        </div>
      )}

      {today.length > 0 && (
        <div className="space-y-2 mb-3">
          <h4 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
            今日 ({data?.asof_today})
          </h4>
          {today.map((ev, i) => <SignalRow key={i} ev={ev} />)}
        </div>
      )}

      {history.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
            最近 5 天
          </h4>
          <div className="max-h-64 overflow-y-auto space-y-1">
            {history.slice(0, 10).map((ev, i) => (
              <div key={i} className="text-xs flex items-center justify-between border-b border-zinc-200 dark:border-zinc-800 py-1">
                <div className="flex items-center gap-2">
                  <span className={`font-bold ${sideColor(ev.side)}`}>{ev.side}</span>
                  <span className="font-mono">{ev.symbol}</span>
                </div>
                <div className="flex items-center gap-3 text-zinc-500">
                  <span>{ev.asof_date}</span>
                  <span>qty {pct(ev.qty_ratio, 0)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </GlassCard>
  );
}
