import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchBars, fetchSignalAudit } from "../lib/api";
import { ChartPanel } from "../components/ChartPanel";
import { AuditPanel } from "../components/AuditPanel";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";

const RANGES = ["1m", "3m", "6m", "1y", "2y", "5y"] as const;
type Range = (typeof RANGES)[number];

import { useState } from "react";

export function SymbolView() {
  const { symbol } = useParams<{ symbol: string }>();
  const navigate = useNavigate();
  const [range, setRange] = useState<Range>("1y");

  const barsQuery = useQuery({
    queryKey: ["bars", symbol, range],
    queryFn: () => fetchBars(symbol!, range),
    enabled: !!symbol,
    retry: false,
  });

  const auditQuery = useQuery({
    queryKey: ["audit", symbol],
    queryFn: () => fetchSignalAudit(symbol!),
    enabled: !!symbol,
    retry: false,
  });

  if (!symbol) return null;

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => navigate(-1)}
          className="text-slate-400 hover:text-slate-200 transition-colors"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <div>
          <h1 className="text-xl font-bold text-slate-100">{symbol}</h1>
          {barsQuery.data && (
            <p className="text-sm text-slate-500 mt-0.5">
              {barsQuery.data.start} → {barsQuery.data.end} · {barsQuery.data.n_bars} bars
            </p>
          )}
        </div>

        {/* Range selector */}
        <div className="ml-auto flex gap-1 bg-slate-800 rounded-lg p-1">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`px-3 py-1 rounded text-xs font-semibold transition-colors ${
                range === r
                  ? "bg-cyan-500/20 text-cyan-300"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {r.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Charts */}
      {barsQuery.isLoading && <LoadingState label="Loading chart data…" />}
      {barsQuery.error && (
        <ErrorState
          message={`Failed to load bars: ${(barsQuery.error as Error).message}`}
          onRetry={() => barsQuery.refetch()}
        />
      )}
      {barsQuery.data && <ChartPanel bars={barsQuery.data.bars} />}

      {/* Audit panel */}
      <div>
        <h2 className="text-sm font-semibold text-slate-400 uppercase mb-3">
          Score Breakdown — Latest Signal
        </h2>
        {auditQuery.isLoading && <LoadingState label="Loading score breakdown…" />}
        {auditQuery.error && (
          <ErrorState
            message={`No signal data: ${(auditQuery.error as Error).message}`}
            onRetry={() => auditQuery.refetch()}
          />
        )}
        {auditQuery.data && <AuditPanel audit={auditQuery.data} />}
      </div>
    </div>
  );
}
