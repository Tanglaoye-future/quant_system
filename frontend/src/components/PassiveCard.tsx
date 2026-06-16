import GlassCard from './GlassCard';
import type { PassiveData } from '../types';

/** v7 配比里的被动持仓 (QQQ / GLD / BTC) 三行 spot snapshot.
 *  不出信号 — PM 只需复核 "今天还应该按 10/10/10 持有, 现价是 X, 涨跌 Y".
 *  美股 tab 唯一 card (QQQ 已不跑 BCS 期权).
 */
export default function PassiveCard({ data }: { data: PassiveData }) {
  const holdings = data?.holdings || [];
  if (data?._missing || holdings.length === 0) {
    return (
      <GlassCard>
        <div className="text-center py-8 text-[#aeaeb2] text-sm">
          暂无被动持仓数据，请运行 <code className="bg-[#f0f0f2] px-1.5 py-0.5 rounded text-xs">python scripts/reporting/daily_passive_holdings.py</code>
        </div>
      </GlassCard>
    );
  }

  function fmtSpot(sym: string, v: number | null): string {
    if (v === null || v === undefined) return '—';
    if (sym === 'BTC-USD') return `$${v.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
    return `$${v.toFixed(2)}`;
  }
  function fmtChg(v: number | null): string {
    if (v === null || v === undefined) return '—';
    const sign = v >= 0 ? '+' : '';
    return `${sign}${(v * 100).toFixed(2)}%`;
  }
  function chgColor(v: number | null): string {
    if (v === null || v === undefined) return 'text-[#86868b]';
    return v >= 0 ? 'text-[#30d158]' : 'text-[#ff453a]';
  }

  return (
    <GlassCard>
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm font-semibold text-[#1d1d1f]">被动持仓 · v7 配比</div>
        <span className="text-[11px] text-[#86868b]">
          {data.asof || '—'} · 不出信号
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#e5e5ea] text-xs text-[#86868b]">
              <th className="text-left py-2 px-2 font-medium">标的</th>
              <th className="text-left py-2 px-2 font-medium">目标配比</th>
              <th className="text-right py-2 px-2 font-medium">现价</th>
              <th className="text-right py-2 px-2 font-medium">1d 变动</th>
              <th className="text-right py-2 px-2 font-medium">数据日期</th>
            </tr>
          </thead>
          <tbody>
            {holdings.map((h) => (
              <tr key={h.symbol} className="border-b border-[#f0f0f2]">
                <td className="py-2 px-2">
                  <span className="font-semibold">{h.symbol}</span>
                  <span className="ml-2 text-xs text-[#86868b]">{h.label}</span>
                </td>
                <td className="py-2 px-2">
                  <span className="inline-flex px-2 py-0.5 text-[11px] font-semibold rounded-md bg-[#e6f0ff] text-[#0050b3]">
                    {(h.target_pct * 100).toFixed(0)}%
                  </span>
                </td>
                <td className="py-2 px-2 text-right font-mono">{fmtSpot(h.symbol, h.spot)}</td>
                <td className={`py-2 px-2 text-right font-semibold ${chgColor(h.change_pct)}`}>
                  {fmtChg(h.change_pct)}
                </td>
                <td className="py-2 px-2 text-right text-xs text-[#86868b]">
                  {h.as_of_date || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-3 text-[11px] text-[#86868b] leading-relaxed">
        v7 配比 (memory/cb_double_low_pr7_yaml_daily_2026-06): HK 50% · A_mom 15% · QQQ 10% · GLD 10% · BTC 10% · CB 5%
      </div>
    </GlassCard>
  );
}
