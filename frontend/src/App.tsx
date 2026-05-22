import { useEffect, useState } from "react";
import { fetchHealth, HealthResponse } from "./lib/api";
import logo from "./assets/logo.svg";

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchHealth()
      .then(setHealth)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col items-center justify-center gap-8 p-8">
      <img src={logo} alt="AlphaSignal" className="h-12" />

      <div className="w-full max-w-sm bg-slate-900 rounded-xl p-6 shadow-lg border border-slate-800">
        <h2 className="text-lg font-semibold mb-4 text-cyan-400">Backend Health</h2>

        {loading && (
          <p className="text-slate-400 animate-pulse">Checking backend…</p>
        )}

        {error && (
          <div className="rounded-lg bg-red-900/40 border border-red-700 p-4 text-red-300 text-sm">
            <p className="font-semibold">Connection error</p>
            <p className="mt-1">{error}</p>
            <p className="mt-2 text-slate-400 text-xs">
              Make sure the backend is running: <code className="text-slate-300">scripts/dev.sh</code>
            </p>
          </div>
        )}

        {health && (
          <dl className="space-y-2 text-sm">
            {(
              [
                ["Status", health.status],
                ["App", health.app],
                ["Version", health.version],
                ["Weights valid", String(health.weights_valid)],
              ] as [string, string][]
            ).map(([label, value]) => (
              <div key={label} className="flex justify-between">
                <dt className="text-slate-400">{label}</dt>
                <dd className={
                  value === "true" ? "text-green-400 font-medium" :
                  value === "false" ? "text-red-400 font-medium" :
                  "text-slate-100"
                }>{value}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </div>
  );
}
