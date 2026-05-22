import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchSignals } from "../lib/api";
import { SignalBadge, compositeColor } from "../components/SignalBadge";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import type { SignalEntry } from "../lib/types";

const COMPONENT_KEYS = ["candlestick", "p3", "p5", "volume", "ema", "sr", "macd", "rsi"] as const;
const COMPONENT_SHORT: Record<string, string> = {
  candlestick: "Candle",
  p3: "P3",
  p5: "P5",
  volume: "Vol",
  ema: "EMA",
  sr: "S/R",
  macd: "MACD",
  rsi: "RSI",
};

function SubScoreCell({ value }: { value: number }) {
  const color =
    value >= 50 ? "text-emerald-400" : value >= 0 ? "text-green-400" : value >= -50 ? "text-orange-400" : "text-red-400";
  return <td className={`px-2 py-3 text-right text-xs font-mono ${color}`}>{value.toFixed(0)}</td>;
}

function SignalRow({ entry, onClick }: { entry: SignalEntry; onClick: () => void }) {
  return (
    <tr
      className="border-b border-slate-800 hover:bg-slate-800/60 cursor-pointer transition-colors group"
      onClick={onClick}
    >
      <td className="px-4 py-3 text-sm text-slate-500 w-10">{entry.rank}</td>
      <td className="px-4 py-3">
        <span className="text-sm font-semibold text-slate-100 group-hover:text-cyan-300 transition-colors">
          {entry.symbol}
        </span>
      </td>
      <td className="px-4 py-3 text-right">
        <span className={`text-sm font-bold font-mono ${compositeColor(entry.composite)}`}>
          {entry.composite >= 0 ? "+" : ""}
          {entry.composite.toFixed(1)}
        </span>
      </td>
      <td className="px-4 py-3 text-right">
        <SignalBadge signal={entry.signal} />
      </td>
      {COMPONENT_KEYS.map((k) => (
        <SubScoreCell key={k} value={entry.sub_scores[k]} />
      ))}
      <td className="px-3 py-3 text-xs text-center">
        {entry.long_allowed ? (
          <span className="text-green-400">L</span>
        ) : (
          <span className="text-slate-600">—</span>
        )}
        {" / "}
        {entry.short_allowed ? (
          <span className="text-red-400">S</span>
        ) : (
          <span className="text-slate-600">—</span>
        )}
      </td>
    </tr>
  );
}

interface Props {
  universe: string;
}

export function Dashboard({ universe }: Props) {
  const navigate = useNavigate();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["signals", universe],
    queryFn: () => fetchSignals({ universe }),
    retry: false,
  });

  if (isLoading) return <LoadingState label="Loading signals…" />;
  if (error) {
    const msg = (error as Error).message;
    const is404 = msg.startsWith("404");
    return (
      <ErrorState
        message={
          is404
            ? "No signals found. Run a daily signal scan first."
            : `Failed to load signals: ${msg}`
        }
        onRetry={is404 ? undefined : () => refetch()}
      />
    );
  }
  if (!data) return null;

  return (
    <div className="p-6">
      {/* Header */}
      <div className="mb-5 flex items-baseline justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-100">Dashboard</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            {data.date} · {data.n_signals} signals · {data.universe}
          </p>
        </div>
        <p className="text-xs text-slate-600">Run #{data.run_id}</p>
      </div>

      {/* Table */}
      <div className="bg-slate-900 rounded-xl border border-slate-700 overflow-x-auto">
        <table className="w-full text-left min-w-[900px]">
          <thead>
            <tr className="border-b border-slate-700 text-xs text-slate-500 uppercase font-medium">
              <th className="px-4 py-3">#</th>
              <th className="px-4 py-3">Symbol</th>
              <th className="px-4 py-3 text-right">Score</th>
              <th className="px-4 py-3 text-right">Signal</th>
              {COMPONENT_KEYS.map((k) => (
                <th key={k} className="px-2 py-3 text-right">
                  {COMPONENT_SHORT[k]}
                </th>
              ))}
              <th className="px-3 py-3 text-center">Regime</th>
            </tr>
          </thead>
          <tbody>
            {data.signals.map((entry) => (
              <SignalRow
                key={entry.symbol}
                entry={entry}
                onClick={() => navigate(`/symbol/${entry.symbol}`)}
              />
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-xs text-slate-600">
        Click any row to open the symbol view with chart and score breakdown.
      </p>
    </div>
  );
}
