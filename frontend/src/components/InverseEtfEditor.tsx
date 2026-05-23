import { useQuery } from "@tanstack/react-query";
import { fetchInverseEtfs } from "../lib/api";
import { LoadingState } from "./LoadingState";
import { ErrorState } from "./ErrorState";

export function InverseEtfEditor() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["inverseEtfs"],
    queryFn: fetchInverseEtfs,
  });

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-700 p-5 space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-slate-200">Inverse-ETF Map</h2>
        <p className="text-xs text-slate-500 mt-1">
          Short-signal rows use this map to look up the inverse ETF to buy. To add or
          edit rows, update{" "}
          <code className="text-cyan-400 font-mono text-[11px]">data/inverse_etfs.csv</code>{" "}
          and restart the backend. (A write endpoint has been requested — see
          SHARED_CHANGES.md.)
        </p>
      </div>

      {isLoading ? (
        <LoadingState label="Loading map…" />
      ) : error ? (
        <ErrorState
          message={`Failed to load: ${(error as Error).message}`}
          onRetry={() => refetch()}
        />
      ) : !data || data.count === 0 ? (
        <p className="text-xs text-slate-500 italic">
          No mappings found. Add rows to data/inverse_etfs.csv.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-700 text-slate-500 uppercase">
                <th className="pb-2 pr-4">Underlying</th>
                <th className="pb-2 pr-4">Inverse ETF</th>
                <th className="pb-2 pr-4">Leverage</th>
                <th className="pb-2">Note</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {Object.entries(data.map).map(([underlying, entry]) => (
                <tr key={underlying}>
                  <td className="py-1.5 pr-4 font-mono font-semibold text-slate-200">
                    {underlying}
                  </td>
                  <td className="py-1.5 pr-4 font-mono text-cyan-400">
                    {entry.inverse_etf_symbol}
                  </td>
                  <td className="py-1.5 pr-4 text-slate-400">{entry.leverage}×</td>
                  <td className="py-1.5 text-slate-500">{entry.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
