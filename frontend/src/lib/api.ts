import type {
  HealthResponse,
  SignalsResponse,
  BarsResponse,
  SignalAudit,
  ConfigResponse,
  PutConfigResponse,
  ConfigWeights,
  DailyRunResponse,
  BacktestJobResponse,
  BacktestResult,
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

export function fetchHealth() {
  return get<HealthResponse>("/health");
}

export function fetchSignals(params?: { date?: string; universe?: string }) {
  const p: Record<string, string> = {};
  if (params?.date) p.date = params.date;
  if (params?.universe) p.universe = params.universe;
  return get<SignalsResponse>("/api/signals", p);
}

export function fetchBars(symbol: string, range = "1y") {
  return get<BarsResponse>(`/api/symbols/${symbol}/bars`, { range });
}

export function fetchSignalAudit(symbol: string, date?: string) {
  const p: Record<string, string> = {};
  if (date) p.date = date;
  return get<SignalAudit>(`/api/symbols/${symbol}/signal`, p);
}

export function fetchConfig() {
  return get<ConfigResponse>("/api/config");
}

export function putWeights(weights: ConfigWeights) {
  return put<PutConfigResponse>("/api/config", weights);
}

export function postDailyRun(params?: { universe?: string; date?: string }) {
  return post<DailyRunResponse>("/api/runs/daily", {
    universe: params?.universe ?? "watchlist",
    ...(params?.date ? { date: params.date } : {}),
  });
}

export function fetchDailyRun(jobId: string) {
  return get<DailyRunResponse>(`/api/runs/daily/${jobId}`);
}

export function postBacktest(params: {
  universe?: string;
  symbols?: string[];
  start?: string;
  end?: string;
  initial_account?: number;
  slippage_pct?: number;
  commission?: number;
}) {
  return post<BacktestJobResponse>("/api/backtest", params);
}

export function fetchBacktest(jobId: string) {
  return get<BacktestResult>(`/api/backtest/${jobId}`);
}
