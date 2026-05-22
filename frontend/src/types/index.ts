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

export interface ZhuangData {
  date: string;
  universe_size: number;
  candidates_count: number;
  market_trend: boolean | null;
  top_candidates: ZhuangCandidate[];
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

export interface HealthResponse {
  status: string;
  data_available: {
    quant: boolean;
    options: boolean;
    zhuang: boolean;
  };
}
