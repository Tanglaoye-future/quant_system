export default function MetricCard({
  label,
  value,
  sub,
  colorClass = '',
}: {
  label: string;
  value: string | number;
  sub?: string;
  colorClass?: string;
}) {
  return (
    <div className="bg-[#f5f5f7] rounded-xl px-4 py-3.5">
      <div className="text-[11px] font-medium text-[#86868b] uppercase tracking-widest mb-1.5">
        {label}
      </div>
      <div className={`text-2xl font-bold tabular-nums ${colorClass}`}>{value}</div>
      {sub && <div className="text-xs text-[#aeaeb2] mt-1">{sub}</div>}
    </div>
  );
}
