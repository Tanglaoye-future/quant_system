import type { ReactNode } from 'react';

export interface QuantSignal {
  code: string;
  name: string;
  score: number;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  reason: string;
  suggested_action: string;
  _source: string;
}

export interface QuantPosition {
  code: string;
  name: string;
  entry_date: string;
  hold_days: number;
  pnl_pct: number | null;
  action: string;
  _source: string;
}

export interface QuantData {
  date: string;
  market: string;
  market_gate: boolean | null;
  market_gate_msg: string;
  benchmark_close: string;
  benchmark_ma60: string;
  signals: QuantSignal[];
  positions: QuantPosition[];
  _missing?: boolean;
}

export interface OptionsSignal {
  type: string;
  structure: string;
  buy_leg: string;
  sell_leg: string;
  max_profit: string;
  max_loss: string;
  contracts: number;
  net_debit: number;
}

export interface OptionsData {
  date: string;
  ivr: number;
  iv_mode: string;
  signal_grade: string;
  qqq_price: number;
  qqq_ma200: number;
  qqq_rsi: number;
  qqq_bullish: boolean;
  signal: OptionsSignal | null;
  reason: string;
  _missing?: boolean;
}

export interface ZhuangCandidate {
  code: string;
  ma_convergence: number;
  volume_asymmetry: number;
  price_consolidation: number;
  turnover_decline: number;
  vp_divergence: number;
  total: number;
}

export interface ZhuangPosition {
  code: string;
  name: string;
  entry_date: string;
  hold_days: number | null;
  pnl_pct: number | null;
  action: string;
}

export interface ZhuangData {
  date: string;
  market?: string;
  universe_size: number;
  candidates_count: number;
  market_trend: boolean | null;
  top_candidates: ZhuangCandidate[];
  positions?: ZhuangPosition[];
  _missing?: boolean;
}

export interface ReportSummary {
  quant: QuantData;
  options: OptionsData;
  zhuang: ZhuangData;
}

export interface ColumnDef<T> {
  key: string;
  header: string;
  render: (row: T, index: number) => ReactNode;
  className?: string;
}

// ── Market-centric types ──

export interface MarketIndex {
  name: string;
  symbol: string;
  close?: number | string;
  ma?: number | string;
  ma60?: number | string;
  ma200?: number | string;
  regime: string;
  regime_msg?: string;
}

export interface StrategySummary {
  key: string;
  name: string;
  status: string;
  signals?: number;
  positions?: number;
  candidates?: number;
  max_score?: number;
  gate_ok?: boolean | null;
  ivr?: number;
  iv_mode?: string;
  grade?: string;
  qqq_price?: number;
  qqq_rsi?: number;
  reason?: string;
  missing?: boolean;
}

export interface MarketData {
  index: MarketIndex;
  strategies: StrategySummary[];
}

export interface MarketsResponse {
  a_share: MarketData;
  us: MarketData;
  hk: MarketData;
}

// ── Dynamic strategy-market matrix (Phase 2: registry-backed) ──

export type CellStatus = 'active' | 'available' | 'blocked' | 'deprecated' | 'unsupported';

export interface CellMetrics {
  signals_count?: number;
  positions_count?: number;
  candidates_count?: number;
  market_gate?: boolean | null;
  ivr?: number;
  iv_mode?: string;
  signal_grade?: string;
  qqq_price?: number;
  qqq_rsi?: number;
  qqq_bullish?: boolean;
  reason?: string;
}

export interface CellResponse {
  strategy_name: string;
  strategy_label: string;
  strategy_kind: string;
  status: CellStatus;
  has_data: boolean;
  data_date?: string;
  config_enabled: boolean;
  blocker_reason?: string;
  metrics: CellMetrics;
}

export interface MarketGroup {
  market_name: string;
  market_label: string;
  display_order: number;
  index: MarketIndex;
  cells: CellResponse[];
}

export interface MatrixResponse {
  markets: MarketGroup[];
  strategies: string[];
}

/** @deprecated Use MatrixResponse / GET /api/matrix instead. Kept for backward compat. */
export interface MarketsResponse {
  a_share: MarketData;
  us: MarketData;
  hk: MarketData;
}

export interface HealthResponse {
  status: string;
  data_available: {
    quant: boolean;
    options: boolean;
    zhuang: boolean;
  };
}
