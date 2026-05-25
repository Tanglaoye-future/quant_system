import type { CellStatus } from '../types';

const statusConfig: Record<CellStatus, { label: string; bg: string; text: string }> = {
  active:    { label: '运行中', bg: 'rgba(48,209,88,0.12)', text: '#30d158' },
  available: { label: '可用',   bg: 'rgba(0,113,227,0.10)', text: '#0071e3' },
  blocked:   { label: '阻断',   bg: 'rgba(255,159,10,0.12)', text: '#ff9f0a' },
  deprecated:{ label: '退役',   bg: 'rgba(134,134,139,0.10)', text: '#86868b' },
  unsupported:{label: '不支持', bg: 'rgba(255,69,58,0.08)', text: '#ff453a' },
};

export default function CellStatusBadge({ status }: { status: CellStatus }) {
  const cfg = statusConfig[status] ?? statusConfig.unsupported;
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 10,
      fontSize: 11, fontWeight: 600, background: cfg.bg, color: cfg.text,
    }}>
      {cfg.label}
    </span>
  );
}
