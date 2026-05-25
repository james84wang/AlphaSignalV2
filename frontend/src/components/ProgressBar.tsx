/**
 * Animated progress bar with elapsed-time ETA.
 * Shows a cyan fill bar while loading symbols, switches to an amber
 * pulsing "Simulating" state when phase === "Simulating".
 */

export interface ProgressInfo {
  nDone: number;
  nTotal: number;
  phase: string;
  startedAt: string;
}

function formatEta(startedAt: string, nDone: number, nTotal: number): string {
  if (nDone <= 0) return "estimating…";
  const elapsedMs = Date.now() - new Date(startedAt).getTime();
  const elapsedSec = elapsedMs / 1000;
  const rate = nDone / elapsedSec; // symbols per second
  const remaining = (nTotal - nDone) / rate;
  if (remaining < 5) return "almost done";
  if (remaining < 60) return `~${Math.round(remaining)}s`;
  const mins = Math.floor(remaining / 60);
  const secs = Math.round(remaining % 60);
  return `~${mins}m ${secs > 0 ? ` ${secs}s` : ""}`;
}

export function ProgressBar({ nDone, nTotal, phase, startedAt }: ProgressInfo) {
  const isSimulating = phase === "Simulating";
  const pct = nTotal > 0 ? Math.min(100, Math.round((nDone / nTotal) * 100)) : 0;
  const eta = nTotal > 0 && nDone < nTotal ? formatEta(startedAt, nDone, nTotal) : "";

  return (
    <div className="space-y-1.5 w-full">
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-300 font-medium truncate max-w-[55%]">
          {isSimulating
            ? "Simulating…"
            : phase
            ? phase
            : "Working…"}
        </span>
        <span className="text-slate-500 font-mono tabular-nums shrink-0 ml-2">
          {isSimulating ? (
            <span className="text-amber-400">running simulation</span>
          ) : nTotal > 0 ? (
            <>
              <span className="text-slate-400">{nDone}</span>
              <span className="text-slate-600"> / {nTotal}</span>
              {eta && <span className="text-slate-500"> · ETA {eta}</span>}
            </>
          ) : null}
        </span>
      </div>

      <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
        {isSimulating ? (
          /* Indeterminate amber pulse while simulation runs */
          <div className="h-full w-full bg-amber-500/60 animate-pulse rounded-full" />
        ) : (
          <div
            className="h-full bg-cyan-500 rounded-full transition-all duration-700 ease-out"
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
    </div>
  );
}
