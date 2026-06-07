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
  current_price?: number | null;
  stop_loss?: number | null;
  ma_long?: number | null;
  dist_to_stop_pct?: number | null;
  dist_to_ma_long_pct?: number | null;
  take_profit?: number | null;
  dist_to_target_pct?: number | null;
}

export interface PortfolioSummary {
  n_positions: number;
  cost_basis: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  max_single_weight: number;
  n_at_risk: number;
  worst_drawdown_pct: number;
  peak_market_value?: number | null;
  drawdown_from_peak_pct?: number | null;
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
  portfolio_alerts?: string[];
  portfolio_summary?: PortfolioSummary | null;
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
  name?: string;
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
  entry_price?: number | null;
  current_price?: number | null;
  stop_loss?: number | null;
  take_profit?: number | null;
  dist_to_stop_pct?: number | null;
  dist_to_target_pct?: number | null;
}

export interface ZhuangData {
  date: string;
  market?: string;
  universe_size: number;
  candidates_count: number;
  market_trend: boolean | null;
  top_candidates: ZhuangCandidate[];
  positions?: ZhuangPosition[];
  portfolio_alerts?: string[];
  portfolio_summary?: PortfolioSummary | null;
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

// ── Panic / capitulation dashboard types ──

export interface PanicCandidate {
  code: string;
  universe: string;
  drop_pct: number;
  vol_ratio: number;
  close: number;
  dd_from_20d_high: number;
}

export interface ReboundCandidate {
  code: string;
  universe: string;
  prior_drop_pct: number;
  prior_vol_ratio: number;
  today_open_vs_prior_close: number;
}

export interface LHBRow {
  code: string;
  name: string;
  date: string;
  jg_net_buy_yuan: number;
  reason: string;
  pct_change?: number;
}

export interface LHBFrequencyRow {
  code: string;
  name: string;
  appearances: number;
  total_jg_net_buy_yuan: number;
  last_date: string;
}

export interface SectorRow {
  sector_type: string;
  name: string;
  pct_change: number;
  representative_stock: string;
  representative_pct?: number;
}

export interface SentimentScore {
  source: string;
  n_items: number;
  n_bull: number;
  n_bear: number;
  score: number;
  samples_bull: string[];
  samples_bear: string[];
}

export interface SleeveOverlap {
  sleeve: string;
  candidates: string[];
  overlap_with_panic: string[];
  overlap_with_rebound: string[];
}

export interface HistoryEntry {
  date: string;
  panic_count: number;
  rebound_count: number;
  lhb_top_jg_buy_yuan: number;
}

export interface PanicData {
  generated_at: string;
  panic: PanicCandidate[];
  rebound: ReboundCandidate[];
  lhb: LHBRow[];
  sentiment: SentimentScore[];
  sleeve_overlap: SleeveOverlap[];
  sectors: {
    industry_top: SectorRow[];
    industry_bot: SectorRow[];
    concept_top: SectorRow[];
    concept_bot: SectorRow[];
  };
  lhb_frequency: LHBFrequencyRow[];
  history: HistoryEntry[];
}

export interface HealthResponse {
  status: string;
  data_available: {
    quant: boolean;
    options: boolean;
    zhuang: boolean;
  };
}
