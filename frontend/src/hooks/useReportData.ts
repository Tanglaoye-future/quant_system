import { useState, useEffect, useCallback, useRef } from 'react';
import type { ReportSummary, MarketsResponse, MatrixResponse, PanicData } from '../types';
import { getSummary, getMarkets, getMatrix, getPanic } from '../api/client';

interface UseReportDataOptions {
  /** 自动 poll 频率 (ms). 默认 60_000 (60s). 传 0 或负数 → 不 poll. */
  pollIntervalMs?: number;
}

export default function useReportData({ pollIntervalMs = 60_000 }: UseReportDataOptions = {}) {
  const [data, setData] = useState<ReportSummary | null>(null);
  const [markets, setMarkets] = useState<MarketsResponse | null>(null);
  const [matrix, setMatrix] = useState<MatrixResponse | null>(null);
  const [panicData, setPanicData] = useState<PanicData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<string>('');

  // PR3: in-flight 标志, 避免 polling 期间 race condition 叠加 fetch.
  const inFlightRef = useRef(false);

  const fetchData = useCallback(async () => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      setLoading(true);
      setError(null);
      const [result, mkts, mtx, panic] = await Promise.all([
        getSummary(), getMarkets(), getMatrix(), getPanic(),
      ]);
      setData(result);
      setMarkets(mkts);
      setMatrix(mtx);
      setPanicData(panic);
      setUpdatedAt(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
      inFlightRef.current = false;
    }
  }, []);

  // 首次 mount fetch.
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // PR3: 自动 polling — 仅 document.visibilityState === 'visible' 时;
  // tab 隐藏 → clearInterval; 重显时立即 fetch + 恢复 interval.
  useEffect(() => {
    if (pollIntervalMs <= 0) return;

    let intervalId: number | null = null;

    const startInterval = () => {
      if (intervalId !== null) return;
      intervalId = window.setInterval(() => {
        if (document.visibilityState === 'visible') {
          fetchData();
        }
      }, pollIntervalMs);
    };

    const stopInterval = () => {
      if (intervalId !== null) {
        window.clearInterval(intervalId);
        intervalId = null;
      }
    };

    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        fetchData();      // 重显时立即刷新
        startInterval();
      } else {
        stopInterval();
      }
    };

    if (document.visibilityState === 'visible') {
      startInterval();
    }
    document.addEventListener('visibilitychange', handleVisibility);

    return () => {
      stopInterval();
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, [fetchData, pollIntervalMs]);

  return { data, markets, matrix, panicData, loading, error, updatedAt, refresh: fetchData };
}
