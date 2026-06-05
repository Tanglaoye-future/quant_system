import { ReactNode } from 'react';
import DailyRunButton from './DailyRunButton';

export default function Layout({
  date,
  updatedAt,
  onRefresh,
  loading,
  children,
}: {
  date: string;
  updatedAt: string;
  onRefresh: () => void;
  loading: boolean;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-[#f5f5f7]">
      {/* Sticky header */}
      <header className="header-gradient sticky top-0 z-50 border-b border-[#e5e5ea]/60">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold tracking-tight text-[#1d1d1f]">
              量化策略日报
            </h1>
            <p className="text-xs text-[#86868b] mt-0.5">
              {date || '—'} · A 股 · 美股 · 港股
            </p>
          </div>
          <div className="flex items-center gap-3">
            {updatedAt && (
              <span className="text-xs text-[#aeaeb2]">更新 {updatedAt}</span>
            )}
            <DailyRunButton onComplete={onRefresh} />
            <button
              onClick={onRefresh}
              disabled={loading}
              className="px-3 py-1.5 text-xs font-medium rounded-lg bg-[#e5e5ea] text-[#1d1d1f] hover:bg-[#d1d1d6] transition-colors disabled:opacity-50"
            >
              {loading ? '刷新中…' : '刷新'}
            </button>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-5xl mx-auto px-6 py-10">{children}</main>

      {/* Footer */}
      <footer className="max-w-5xl mx-auto px-6 pb-10 text-xs text-[#aeaeb2] flex justify-between">
        <span>Quant System v0.2.0</span>
        <span>本报告仅供研究参考，不构成投资建议</span>
      </footer>
    </div>
  );
}
