export interface HealthResponse {
  status: string;
  app: string;
  version: string;
  weights_valid: boolean;
}

export type SignalLabel = "Strong Buy" | "Buy" | "Hold" | "Sell" | "Strong Sell";

export interface SubScores {
  candlestick: number;
  p3: number;
  p5: number;
  volume: number;
  ema: number;
  sr: number;
  macd: number;
  rsi: number;
}

export interface SignalEntry {
  rank: number;
  symbol: string;
  composite: number;
  signal: SignalLabel;
  long_allowed: boolean;
  short_allowed: boolean;
  sub_scores: SubScores;
  /** Populated on short-strategy runs; null when no inverse ETF is mapped */
  inverse_etf?: string | null;
  /** True when signal was emitted but no inverse ETF mapping exists */
  no_inverse_etf?: boolean;
}

export interface SignalsResponse {
  run_id: number;
  run_timestamp: string;
  date: string;
  universe: string;
  config_hash: string;
  n_signals: number;
  signals: SignalEntry[];
}

export interface Bar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface BarsResponse {
  symbol: string;
  range: string;
  start: string;
  end: string;
  n_bars: number;
  bars: Bar[];
}

export interface ComponentDetail {
  sub: number;
  weight: number;
  weighted: number;
}

export interface SignalAudit {
  symbol: string;
  date: string;
  composite: number;
  signal: SignalLabel;
  source: "db" | "computed";
  regime: {
    long_allowed: boolean;
    short_allowed: boolean;
  };
  components: {
    candlestick: ComponentDetail;
    p3: ComponentDetail;
    p5: ComponentDetail;
    volume: ComponentDetail;
    ema: ComponentDetail;
    sr: ComponentDetail;
    macd: ComponentDetail;
    rsi: ComponentDetail;
  };
}

export type ComponentKey = keyof SignalAudit["components"];

export interface ConfigWeights {
  candlestick: number;
  p3: number;
  p5: number;
  volume: number;
  ema: number;
  sr: number;
  macd: number;
  rsi: number;
}

export interface ConfigThresholds {
  strong_buy: number;
  buy: number;
  sell: number;
  strong_sell: number;
}

export interface ConfigResponse {
  thresholds: ConfigThresholds;
  weights: ConfigWeights;
  regime: { ema_period: number; slope_lookback: number };
  candlestick: {
    long_candle_body_pct: number;
    hammer_wick_mult: number;
    doji_body_pct: number;
    sr_context_multiplier: number;
    scores: Record<string, number>;
  };
  p3: { window: number; scores: Record<string, number> };
  p5: { window: number; scores: Record<string, number> };
  volume: {
    avg_period: number;
    bullish_buckets: Array<{ rv_min: number | null; rv_max: number | null; score: number }>;
  };
  ema: {
    periods: number[];
    stacking_scores: Record<string, number>;
    cross_scores: Record<string, number>;
  };
  sr: { cluster_pct: number; breakout_volume_mult: number; scores: Record<string, number> };
  macd: { fast: number; slow: number; signal: number; micro_signals: Record<string, number> };
  rsi: { period: number; scores: Record<string, number> };
  [key: string]: unknown;
}

export interface ScoringTablesUpdate {
  candlestick?: Record<string, number>;
  p3?: Record<string, number>;
  p5?: Record<string, number>;
  ema_stacking?: Record<string, number>;
  ema_cross?: Record<string, number>;
  sr?: Record<string, number>;
  macd?: Record<string, number>;
  rsi?: Record<string, number>;
}

export interface ProfileUpdate {
  weights: ConfigWeights;
  thresholds?: ConfigThresholds;
  scoring_tables?: ScoringTablesUpdate;
}

export interface PutConfigResponse {
  ok: boolean;
  strategy: string;
  weights: ConfigWeights;
  thresholds_updated: boolean;
  scoring_tables_updated: boolean;
  config_hash: string;
  version_saved_at: string;
}

export interface DailyRunResponse {
  job_id: string;
  status: "running" | "done" | "error";
  message?: string;
  started_at?: string;
  finished_at?: string;
  run_id?: number;
  n_success?: number;
  n_errors?: number;
  universe?: string;
  strategy?: string;
  date?: string;
  error?: string;
  // Progress fields (present while status === "running")
  n_done?: number;
  n_total?: number;
  phase?: string;
}

export interface BacktestJobResponse {
  job_id: string;
  status: "running" | "done" | "error";
  message?: string;
}

export interface TradeEntry {
  symbol: string;
  side: string;
  entry_date: string;
  entry_price: number;
  exit_date: string;
  exit_price: number;
  shares: number;
  initial_stop: number;
  pnl: number;
  pnl_pct: number;
  exit_reason: string;
  // Short-strategy fields (null for long trades)
  underlying_symbol?: string | null;
  trade_instrument?: string | null;
}

export interface BacktestMetrics {
  n_trades: number;
  hit_rate: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
  max_drawdown_pct: number;
  sharpe: number;
  cagr: number;
  total_return_pct: number;
  final_equity: number;
  exposure_pct: number;
}

export interface BacktestResult {
  job_id: string;
  status: "running" | "done" | "error";
  db_run_id?: number;
  started_at?: string;
  finished_at?: string;
  duration_seconds?: number;
  error?: string;
  // Progress fields (present while status === "running")
  n_done?: number;
  n_total?: number;
  phase?: string;
  params?: {
    start: string;
    end: string;
    symbols: string[];
    n_symbols_loaded: number;
    initial_account: number;
  };
  metrics?: BacktestMetrics;
  equity_curve?: Array<{ date: string; equity: number; n_open: number }>;
  trades?: TradeEntry[];
  survivorship_note?: string;
}

// ── Market Overview ──────────────────────────────────────────────────────────

export interface IndexTile {
  label: string;
  symbol: string;
  status: "ok" | "unavailable";
  last?: number;
  prev_close?: number;
  change_pct?: number;
}

export interface FearAndGreed {
  label: string;
  source: string;
  status: "ok" | "unavailable";
  score?: number;
  rating?: string;
}

export interface MarketOverviewResponse {
  indices: Record<string, IndexTile>;
  fear_and_greed: FearAndGreed;
  cache_ttl_seconds: number;
  note: string;
}

// ── Watchlist ────────────────────────────────────────────────────────────────

export interface WatchlistEntry {
  symbol: string;
  added_at: string;
  note: string | null;
}

export interface WatchlistResponse {
  count: number;
  symbols: WatchlistEntry[];
}

// ── Inverse ETFs ─────────────────────────────────────────────────────────────

export interface InverseEtfEntry {
  inverse_etf_symbol: string;
  leverage: number;
  note: string;
}

export interface InverseEtfMapResponse {
  count: number;
  map: Record<string, InverseEtfEntry>;
}

// ── Schedule ─────────────────────────────────────────────────────────────────

export interface ScheduleStatus {
  enabled: boolean;
  time: string;
  tz: string;
  catchup_enabled: boolean;
  last_run_date: string | null;
  next_run: string | null;
  note: string;
}
