import { useState, useEffect, useCallback } from 'react';
import type { ReportSummary, MarketsResponse, MatrixResponse } from '../types';
import { getSummary, getMarkets, getMatrix } from '../api/client';

export default function useReportData() {
  const [data, setData] = useState<ReportSummary | null>(null);
  const [markets, setMarkets] = useState<MarketsResponse | null>(null);
  const [matrix, setMatrix] = useState<MatrixResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<string>('');

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [result, mkts, mtx] = await Promise.all([
        getSummary(), getMarkets(), getMatrix(),
      ]);
      setData(result);
      setMarkets(mkts);
      setMatrix(mtx);
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

  return { data, markets, matrix, loading, error, updatedAt, refresh: fetchData };
}
