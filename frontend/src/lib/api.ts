import type {
  HealthResponse,
  SignalsResponse,
  BarsResponse,
  SignalAudit,
  ConfigResponse,
  PutConfigResponse,
  ProfileUpdate,
  DailyRunResponse,
  BacktestJobResponse,
  BacktestResult,
  MarketOverviewResponse,
  WatchlistsResponse,
  ScheduleStatus,
  OptimizeRequest,
  OptimizeStartResponse,
  OptimizeStatus,
  PromoteResponse,
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

// ── Config (single long-only strategy) ───────────────────────────────────────

export function fetchConfig() {
  return get<ConfigResponse>("/api/config/hidden_div");
}

export function putConfig(payload: ProfileUpdate) {
  return put<PutConfigResponse>("/api/config/hidden_div", payload);
}

/**
 * Download the saved strategy as a TradingView Pine Script (v6). Fetches the
 * generated text from the backend and triggers a browser file download.
 */
export async function downloadPineScript(): Promise<void> {
  const res = await fetch(`${BASE}/api/config/hidden_div/pine`);
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "hidden_div_confluence_uptrend.pine";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ── Daily runs ───────────────────────────────────────────────────────────────

export function postDailyRun(params?: { universe?: string; date?: string }) {
  return post<DailyRunResponse>("/api/runs/daily", {
    universe: params?.universe ?? "combined",
    strategy: "hidden_div",
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
  initial_fund?: number;
  slippage_pct?: number;
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
  return post<BacktestJobResponse>("/api/backtest", { strategy: "hidden_div", ...params });
}

export function fetchBacktest(jobId: string) {
  return get<BacktestResult>(`/api/backtest/${jobId}`);
}

// ── Optimiser ────────────────────────────────────────────────────────────────

export function postOptimize(body: OptimizeRequest) {
  return post<OptimizeStartResponse>("/api/optimize", body);
}

export function fetchOptimize(jobId: string) {
  return get<OptimizeStatus>(`/api/optimize/${jobId}`);
}

export function promoteCandidate(jobId: string) {
  return post<PromoteResponse>(`/api/optimize/${jobId}/promote`, {});
}

/** URL of the markdown optimisation report (opened in a new tab / downloaded). */
export function optimizeReportUrl(jobId: string): string {
  return `${BASE}/api/optimize/${jobId}/report`;
}

// ── Market overview ──────────────────────────────────────────────────────────

export function fetchMarketOverview(refresh = false) {
  const p: Record<string, string> = {};
  if (refresh) p.refresh = "true";
  return get<MarketOverviewResponse>("/api/market/overview", p);
}

// ── Watchlists (multiple named lists) ─────────────────────────────────────────

export function fetchWatchlists() {
  return get<WatchlistsResponse>("/api/watchlists");
}

export function addToWatchlist(listName: string, symbol: string, note?: string) {
  return post<{ list_name: string; symbol: string; added_at: string; note: string | null }>(
    `/api/watchlists/${encodeURIComponent(listName)}/symbols`,
    { symbol, note: note ?? null },
  );
}

export function removeFromWatchlist(listName: string, symbol: string) {
  return del<{ ok: boolean; list_name: string; symbol: string }>(
    `/api/watchlists/${encodeURIComponent(listName)}/symbols/${encodeURIComponent(symbol)}`,
  );
}

// ── Schedule ─────────────────────────────────────────────────────────────────

export function fetchSchedule() {
  return get<ScheduleStatus>("/api/schedule");
}

export function putSchedule(enabled: boolean) {
  return put<ScheduleStatus>("/api/schedule", { enabled });
}

// ── About ─────────────────────────────────────────────────────────────────────

export function fetchAbout(lang: "en" | "zh" = "en") {
  return get<{ content: string; last_updated: string }>("/api/about", { lang });
}
