import { useEffect, useState, useRef } from 'react';
import { runDaily, getDailyStatus, type DailyStatus } from '../api/client';

interface Props {
  onComplete?: () => void;   // 跑完后回调，由 App 触发 refresh dashboard data
}

export default function DailyRunButton({ onComplete }: Props) {
  const [status, setStatus] = useState<DailyStatus | null>(null);
  const [showLog, setShowLog] = useState(false);
  const [busy, setBusy] = useState(false);   // 防止 POST 重复点击
  const lastStatusRef = useRef<string>('idle');

  // 初始化拉一次状态 + 跑步时每 3s 轮询
  useEffect(() => {
    let cancelled = false;

    const fetchStatus = async () => {
      try {
        const s = await getDailyStatus();
        if (cancelled) return;
        // running → success/failed 转换时触发 dashboard refresh
        if (lastStatusRef.current === 'running' && (s.status === 'success' || s.status === 'failed')) {
          onComplete?.();
        }
        lastStatusRef.current = s.status;
        setStatus(s);
      } catch (e) {
        // API 暂时不可达；不弹错保持安静
      }
    };

    fetchStatus();
    const id = setInterval(() => {
      if (lastStatusRef.current === 'running') fetchStatus();
    }, 3000);
    return () => { cancelled = true; clearInterval(id); };
  }, [onComplete]);

  const onClick = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await runDaily(true);
      const s = await getDailyStatus();
      setStatus(s);
      lastStatusRef.current = s.status;
      setShowLog(true);   // 启动后展开日志
    } catch (e: any) {
      alert(`无法启动 daily：${e?.message ?? e}`);
    } finally {
      setBusy(false);
    }
  };

  const running = status?.status === 'running';
  const label = running ? `运行中… ${elapsed(status?.started_at)}`
    : status?.status === 'success' ? '运行 Daily ✓'
    : status?.status === 'failed' ? '运行 Daily ✗'
    : '运行 Daily';

  const baseCls = 'px-3 py-1.5 text-xs font-medium rounded-lg transition-colors disabled:opacity-50';
  const stateCls = running
    ? 'bg-[#fff4d6] text-[#9a6b00] border border-[#f0c000]/40'
    : status?.status === 'failed'
    ? 'bg-[#ffe8e6] text-[#c0392b] border border-[#ff453a]/40'
    : status?.status === 'success'
    ? 'bg-[#e5f9e8] text-[#1a7f37] border border-[#30d158]/40'
    : 'bg-[#0071e3] text-white hover:bg-[#0066cc]';

  return (
    <>
      <button
        onClick={onClick}
        disabled={running || busy}
        title={status?.log_path ? `日志: ${status.log_path}` : ''}
        className={`${baseCls} ${stateCls}`}
      >
        {label}
      </button>
      {status?.job_id && (
        <button
          onClick={() => setShowLog(v => !v)}
          className="px-2 py-1 text-[11px] text-[#0071e3] hover:underline"
        >
          {showLog ? '隐藏日志' : '查看日志'}
        </button>
      )}
      {showLog && status?.log_tail && status.log_tail.length > 0 && (
        <div
          className="fixed right-4 bottom-4 w-[640px] max-h-[60vh] overflow-auto rounded-xl shadow-2xl bg-[#1d1d1f] text-[#f5f5f7] text-[11px] font-mono z-50"
          style={{ padding: 14 }}
        >
          <div className="flex items-center justify-between mb-2 sticky top-0 bg-[#1d1d1f] py-1">
            <div className="text-[#86868b]">
              {status.job_id} · {status.status}
              {status.exit_code !== null && status.exit_code !== undefined && ` · exit ${status.exit_code}`}
            </div>
            <button onClick={() => setShowLog(false)} className="text-[#86868b] hover:text-white">×</button>
          </div>
          <pre className="whitespace-pre-wrap break-words">{status.log_tail.join('\n')}</pre>
        </div>
      )}
    </>
  );
}

function elapsed(startedAt?: string | null): string {
  if (!startedAt) return '';
  try {
    const ms = Date.now() - new Date(startedAt).getTime();
    const s = Math.floor(ms / 1000);
    const m = Math.floor(s / 60);
    const r = s % 60;
    return m > 0 ? `${m}m${r}s` : `${s}s`;
  } catch {
    return '';
  }
}
