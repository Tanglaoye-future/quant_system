import type { ReportSummary } from '../types';

/** 今日交易动作汇总 —— 跨 equity + zhuang 聚合，让自动交易行为一眼可见。
 *  避免「无信号日」看着像系统没交易功能。 */
export default function TradeActionsBar({ data }: { data: ReportSummary }) {
  const buySignals = (data.quant?.signals || []).length;

  const eqPos = data.quant?.positions || [];
  const zhPos = data.zhuang?.positions || [];
  const all = [
    ...eqPos.map((p) => ({ code: p.code, action: p.action })),
    ...zhPos.map((p) => ({ code: p.code, action: p.action })),
  ];
  const isSell = (a: string) => a === 'EXIT' || a === '卖出';
  const isNew = (a: string) => a === '建仓';

  const newOpens = all.filter((p) => isNew(p.action)).length;
  const sells = all.filter((p) => isSell(p.action)).length;
  const holds = new Set(all.filter((p) => !isSell(p.action)).map((p) => p.code)).size;
  const quiet = buySignals === 0 && newOpens === 0 && sells === 0;

  const chip = (label: string, value: number, tone: string) => (
    <div className="flex items-center gap-1.5">
      <span className={`inline-flex items-center justify-center min-w-[22px] h-[22px] px-1.5 rounded-md text-[12px] font-bold ${tone}`}>
        {value}
      </span>
      <span className="text-[13px] text-[#6e6e73]">{label}</span>
    </div>
  );

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 mb-4 rounded-xl bg-white/70 border border-[#e5e5ea]">
      <span className="text-[13px] font-semibold text-[#1d1d1f]">今日交易动作</span>
      {chip('买入信号', buySignals, buySignals > 0 ? 'bg-[#e6f0ff] text-[#0050b3]' : 'bg-[#f0f0f2] text-[#aeaeb2]')}
      {chip('今日建仓', newOpens, newOpens > 0 ? 'bg-[#e5f9e8] text-[#1a7f37]' : 'bg-[#f0f0f2] text-[#aeaeb2]')}
      {chip('卖出建议', sells, sells > 0 ? 'bg-[#ffe8e6] text-[#c0392b]' : 'bg-[#f0f0f2] text-[#aeaeb2]')}
      {chip('持有', holds, 'bg-[#f0f0f2] text-[#48484a]')}
      {quiet && (
        <span className="text-[12px] text-[#aeaeb2]">今日无新交易动作（市况门/无信号），仅维持持仓</span>
      )}
    </div>
  );
}
