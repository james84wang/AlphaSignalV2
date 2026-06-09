export interface HealthResponse {
  status: string;
  app: string;
  version: string;
  weights_valid: boolean;
}

export type SignalLabel = "Strong Buy" | "Buy" | "Hold" | "Sell" | "Strong Sell";

// Names of the eight confluence components (4 entry + 4 exit).
export const ENTRY_COMPONENTS = [
  "macd_hidden_bull",
  "rsi_hidden_bull",
  "rsi_zone",
  "demark_td9_buy",
] as const;
export const EXIT_COMPONENTS = [
  "demark_td13_sell",
  "macd_regular_bear",
  "rsi_regular_bear",
  "demark_td9_sell",
] as const;
export type EntryComponent = (typeof ENTRY_COMPONENTS)[number];
export type ExitComponent = (typeof EXIT_COMPONENTS)[number];

export interface SignalEntry {
  rank: number;
  symbol: string;
  composite: number;
  signal: SignalLabel;
  long_allowed: boolean;
  short_allowed: boolean;
  /** component name → contribution points (entry + exit components) */
  sub_scores: Record<string, number>;
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

export interface ConfluenceComponent {
  side: "entry" | "exit";
  weight: number;
  fired: boolean;
  contribution: number;
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
  entry_score: number;
  exit_score: number;
  components: Record<string, ConfluenceComponent>;
}

// ── Strategy config (Hidden-Divergence Confluence, long-only) ──────────────────

export interface EntryWeights {
  macd_hidden_bull: number;
  rsi_hidden_bull: number;
  rsi_zone: number;
  demark_td9_buy: number;
}

export interface ExitWeights {
  demark_td13_sell: number;
  macd_regular_bear: number;
  rsi_regular_bear: number;
  demark_td9_sell: number;
}

export interface EntrySide {
  threshold: number;
  conf_window: number;
  weights: EntryWeights;
}

export interface ExitSide {
  threshold: number;
  conf_window: number;
  weights: ExitWeights;
}

export interface RegimeParams {
  ema_fast: number;
  ema_slow: number;
  slope_lookback: number;
}
export interface PivotsParams {
  left: number;
  right: number;
  min_bars: number;
  max_bars: number;
}
export interface MacdParams {
  fast: number;
  slow: number;
  signal: number;
}
export interface RsiParams {
  period: number;
  zone_low: number;
  zone_high: number;
}
export interface DemarkParams {
  setup: number;
  countdown: number;
  setup_lookback: number;
  countdown_lookback: number;
}

export interface StrategyParams {
  regime: RegimeParams;
  pivots: PivotsParams;
  macd: MacdParams;
  rsi: RsiParams;
  demark: DemarkParams;
}

export interface ConfigResponse extends StrategyParams {
  entry: EntrySide;
  exit: ExitSide;
}

export interface ProfileUpdate {
  entry: EntrySide;
  exit: ExitSide;
  params?: Partial<StrategyParams>;
}

export interface PutConfigResponse {
  ok: boolean;
  strategy: string;
  entry: EntrySide;
  exit: ExitSide;
  params_updated: boolean;
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
  entry_fee?: number;
  exit_fee?: number;
  // Optional grouping key retained for backward-compat; undefined for long trades.
  underlying_symbol?: string | null;
  trade_instrument?: string | null;
}

export interface BacktestMetrics {
  n_trades: number;
  hit_rate: number;
  win_rate?: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
  win_loss_ratio?: number;
  max_drawdown_pct: number;
  max_drawdown?: number;
  sharpe: number;
  sharpe_ratio?: number;
  cagr: number;
  total_return_pct: number;
  total_return?: number;
  final_equity: number;
  exposure_pct: number;
  total_fees?: number;
  turnover?: number;
  avg_holding_days?: number;
}

export interface BenchmarkMetrics {
  total_return: number;
  cagr: number;
  sharpe_ratio: number;
  max_drawdown: number;
  final_equity: number;
}

export interface ComparisonMetricRow {
  strategy: number;
  benchmark: number;
}

export interface Comparison {
  metrics: Record<string, ComparisonMetricRow>;
  fairness_caveat: string;
  sharpe_convention: string;
  price_basis: string;
}

export interface ConstraintCounts {
  skipped_no_slot: number;
  skipped_no_capital: number;
  skipped_top_n: number;
}

export interface BacktestResult {
  job_id: string;
  status: "running" | "done" | "error";
  db_run_id?: number;
  started_at?: string;
  finished_at?: string;
  duration_seconds?: number;
  error?: string;
  strategy?: string;
  n_done?: number;
  n_total?: number;
  phase?: string;
  params?: {
    start: string;
    end: string;
    symbols: string[];
    n_symbols_loaded: number;
    initial_fund?: number;
    initial_account?: number;
    position_size_pct?: number;
    position_size_min?: number;
    fee_per_share?: number;
    fee_min?: number;
    fee_max_pct_of_trade?: number;
    atr_stop_multiple?: number;
    atr_period?: number;
    max_concurrent_positions?: number;
    per_name_cap_pct?: number;
    top_n?: number;
    benchmark_symbol?: string;
    risk_free_rate?: number;
    price_basis?: string;
  };
  metrics?: BacktestMetrics;
  strategy_metrics?: BacktestMetrics;
  benchmark_metrics?: BenchmarkMetrics;
  comparison?: Comparison;
  equity_curve?: Array<{ date: string; equity: number; n_open: number }>;
  benchmark_equity_curve?: Array<{ date: string; equity: number; n_open: number }>;
  constraint_counts?: ConstraintCounts;
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

// ── Watchlists (multiple named lists) ──────────────────────────────────────────

export interface WatchlistSymbol {
  symbol: string;
  added_at: string;
  note: string | null;
}

export interface WatchlistList {
  name: string;
  count: number;
  symbols: WatchlistSymbol[];
}

export interface WatchlistsResponse {
  lists: WatchlistList[];
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

// ── Optimiser ────────────────────────────────────────────────────────────────

export interface OptimizeRequest {
  universe: string;
  start?: string;
  end?: string;
  trials?: number;
  folds?: number;
  seed?: number;
  insample_ratio?: number;
  max_drawdown_limit?: number;
  include_scoring_tables?: boolean;
  include_sizing?: boolean;
}

export interface OptimizeStartResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface OptimizeWeights {
  entry: { threshold: number; conf_window: number; weights: Record<string, number> };
  exit: { threshold: number; conf_window: number; weights: Record<string, number> };
}

export interface OptimizeStatus {
  job_id: string;
  status: "running" | "done" | "error";
  started_at?: string;
  finished_at?: string;
  error?: string;
  // progress (while running)
  n_done?: number;
  n_total?: number;
  phase?: string;
  // result (when done)
  universe_size?: number;
  n_trials?: number;
  wall_clock_seconds?: number;
  insample_start?: string;
  insample_end?: string;
  holdout_start?: string;
  holdout_end?: string;
  pass_verdict?: boolean;
  verdict_tier?: "ROBUST" | "SUSPECT" | "OVERFIT";
  verdict_notes?: string[];
  insample_metrics?: Record<string, number>;
  holdout_metrics?: Record<string, number>;
  wf_metrics?: Record<string, number>;
  holdout_benchmark_metrics?: Record<string, number>;
  benchmark_vs_spy_metrics?: Record<string, number>;
  luck_audit?: Record<string, unknown>;
  cluster_analysis?: Record<string, unknown>;
  perturbation_results?: Array<Record<string, unknown>>;
  best_strat?: OptimizeWeights;
  best_composite_score?: number;
  candidate_path?: string;
  report_path?: string;
  csv_path?: string;
}

export interface PromoteResponse {
  ok: boolean;
  promoted_from: string;
  config_hash: string;
}
