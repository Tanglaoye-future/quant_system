const BASE = '/api';

async function fetchJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
  return res.json();
}

export function getHealth() {
  return fetchJSON<{ status: string; data_available: Record<string, boolean> }>('/health');
}

export function getSummary() {
  return fetchJSON<import('../types').ReportSummary>('/report/summary');
}

export function getQuant() {
  return fetchJSON<import('../types').QuantData>('/report/quant');
}

export function getOptions() {
  return fetchJSON<import('../types').OptionsData>('/report/options');
}

export function getZhuang() {
  return fetchJSON<import('../types').ZhuangData>('/report/zhuang');
}

export function getMarkets() {
  return fetchJSON<import('../types').MarketsResponse>('/markets');
}
