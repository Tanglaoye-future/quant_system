type BadgeVariant = 'pass' | 'fail' | 'idle' | 'warn' | 'info';

const variantStyles: Record<BadgeVariant, string> = {
  pass: 'bg-[#e5f9e8] text-[#1a7f37]',
  fail: 'bg-[#ffe8e6] text-[#c0392b]',
  idle: 'bg-[#f0f0f2] text-[#86868b]',
  warn: 'bg-[#fff3e0] text-[#cc7a00]',
  info: 'bg-[#e3f0ff] text-[#0066cc]',
};

export default function StatusBadge({
  label,
  variant = 'idle',
}: {
  label: string;
  variant?: BadgeVariant;
}) {
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold tracking-wide ${variantStyles[variant]}`}
    >
      {label}
    </span>
  );
}
