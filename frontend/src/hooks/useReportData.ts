import { useState, useEffect, useCallback } from 'react';
import type { ReportSummary, MarketsResponse } from '../types';
import { getSummary, getMarkets } from '../api/client';

export default function useReportData() {
  const [data, setData] = useState<ReportSummary | null>(null);
  const [markets, setMarkets] = useState<MarketsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<string>('');

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [result, mkts] = await Promise.all([getSummary(), getMarkets()]);
      setData(result);
      setMarkets(mkts);
      setUpdatedAt(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { data, markets, loading, error, updatedAt, refresh: fetchData };
}
