const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export interface HealthResponse {
  status: string;
  app: string;
  version: string;
  weights_valid: boolean;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${BASE}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}
