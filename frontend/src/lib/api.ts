import type {
  HealthResponse,
  SignalsResponse,
  BarsResponse,
  SignalAudit,
  ConfigResponse,
  PutConfigResponse,
  ConfigWeights,
  ProfileUpdate,
  DailyRunResponse,
  BacktestJobResponse,
  BacktestResult,
  MarketOverviewResponse,
  WatchlistResponse,
  WatchlistEntry,
  InverseEtfMapResponse,
  ScheduleStatus,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

async function get<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(BASE + path);
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  }
  const res = await fetch(url.toString());
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

async function del<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path, { method: "DELETE" });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

// ── Health ───────────────────────────────────────────────────────────────────

export function fetchHealth() {
  return get<HealthResponse>("/health");
}

// ── Signals ──────────────────────────────────────────────────────────────────

export function fetchSignals(params?: { date?: string; universe?: string }) {
  const p: Record<string, string> = {};
  if (params?.date) p.date = params.date;
  if (params?.universe) p.universe = params.universe;
  return get<SignalsResponse>("/api/signals", p);
}

// ── Symbol detail ────────────────────────────────────────────────────────────

export function fetchBars(symbol: string, range = "1y") {
  return get<BarsResponse>(`/api/symbols/${symbol}/bars`, { range });
}

/** Fetch 30-day bars for a sparkline (encodes symbol for index tickers like ^GSPC). */
export function fetchSparkline(symbol: string) {
  return get<BarsResponse>(`/api/symbols/${encodeURIComponent(symbol)}/bars`, { range: "1m" });
}

export function fetchSignalAudit(symbol: string, date?: string) {
  const p: Record<string, string> = {};
  if (date) p.date = date;
  return get<SignalAudit>(`/api/symbols/${symbol}/signal`, p);
}

// ── Config (per-strategy) ────────────────────────────────────────────────────

export function fetchConfigStrategy(strategy: "long" | "short") {
  return get<ConfigResponse>(`/api/config/${strategy}`);
}

export function putConfigStrategy(strategy: "long" | "short", payload: ProfileUpdate) {
  return put<PutConfigResponse>(`/api/config/${strategy}`, payload);
}

/** @deprecated Use fetchConfigStrategy("long") */
export function fetchConfig() {
  return fetchConfigStrategy("long");
}

/** @deprecated Use putConfigStrategy */
export function putWeights(weights: ConfigWeights) {
  return putConfigStrategy("long", { weights });
}

// ── Daily runs ───────────────────────────────────────────────────────────────

export function postDailyRun(params?: {
  universe?: string;
  strategy?: "long" | "short";
  date?: string;
}) {
  return post<DailyRunResponse>("/api/runs/daily", {
    universe: params?.universe ?? "combined",
    strategy: params?.strategy ?? "long",
    ...(params?.date ? { date: params.date } : {}),
  });
}

export function fetchDailyRun(jobId: string) {
  return get<DailyRunResponse>(`/api/runs/daily/${jobId}`);
}

// ── Backtest ─────────────────────────────────────────────────────────────────

export function postBacktest(params: {
  universe?: string;
  symbols?: string[];
  start?: string;
  end?: string;
  strategy?: string;
  initial_fund?: number;
  initial_account?: number;
  slippage_pct?: number;
  commission?: number;
  fee_per_share?: number;
  fee_min?: number;
  fee_max_pct_of_trade?: number;
  position_size_pct?: number;
  position_size_min?: number;
  atr_stop_multiple?: number;
  atr_period?: number;
  max_concurrent_positions?: number;
  per_name_cap_pct?: number;
  top_n?: number;
  benchmark_symbol?: string;
  risk_free_rate?: number;
}) {
  return post<BacktestJobResponse>("/api/backtest", params);
}

export function fetchBacktest(jobId: string) {
  return get<BacktestResult>(`/api/backtest/${jobId}`);
}

// ── Market overview ──────────────────────────────────────────────────────────

export function fetchMarketOverview(refresh = false) {
  const p: Record<string, string> = {};
  if (refresh) p.refresh = "true";
  return get<MarketOverviewResponse>("/api/market/overview", p);
}

// ── Watchlist ────────────────────────────────────────────────────────────────

export function fetchWatchlist() {
  return get<WatchlistResponse>("/api/watchlist");
}

export function addToWatchlist(symbol: string, note?: string) {
  return post<WatchlistEntry>("/api/watchlist", { symbol, note: note ?? null });
}

export function removeFromWatchlist(symbol: string) {
  return del<{ ok: boolean; symbol: string }>(`/api/watchlist/${symbol}`);
}

// ── Inverse ETFs ─────────────────────────────────────────────────────────────

export function fetchInverseEtfs() {
  return get<InverseEtfMapResponse>("/api/inverse-etfs");
}

// ── Schedule ─────────────────────────────────────────────────────────────────

export function fetchSchedule() {
  return get<ScheduleStatus>("/api/schedule");
}

export function putSchedule(enabled: boolean) {
  return put<ScheduleStatus>("/api/schedule", { enabled });
}
