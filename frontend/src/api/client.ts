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

export function getPanic() {
  return fetchJSON<import('../types').PanicData>('/report/panic');
}

export function getMatrix() {
  return fetchJSON<import('../types').MatrixResponse>('/matrix');
}

export function getTSignals() {
  return fetchJSON<import('../types').TSignalsPayload>('/report/t_signals');
}

// Daily 运行控制 ─────────────────────────────────────────────────────────
export interface DailyStatus {
  status: 'idle' | 'running' | 'success' | 'failed';
  job_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
  log_path: string | null;
  log_tail: string[];
}

export async function runDaily(skipOptions = true): Promise<{ job_id: string; started_at: string; log_path: string }> {
  const res = await fetch(`${BASE}/daily/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ skip_options: skipOptions }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`run daily failed: ${res.status} ${detail}`);
  }
  return res.json();
}

export function getDailyStatus() {
  return fetchJSON<DailyStatus>('/daily/status');
}
