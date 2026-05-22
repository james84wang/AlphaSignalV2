import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchConfig, putWeights } from "../lib/api";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import type { ConfigWeights } from "../lib/types";

const WEIGHT_KEYS: (keyof ConfigWeights)[] = [
  "candlestick",
  "p3",
  "p5",
  "volume",
  "ema",
  "sr",
  "macd",
  "rsi",
];
const WEIGHT_LABELS: Record<keyof ConfigWeights, string> = {
  candlestick: "Candlestick Pattern",
  p3: "3-Bar Pattern",
  p5: "5-Bar Pattern",
  volume: "Volume",
  ema: "EMA System",
  sr: "Support / Resistance",
  macd: "MACD",
  rsi: "RSI",
};

function ScoreTable({ label, scores }: { label: string; scores: Record<string, number> }) {
  return (
    <div className="bg-slate-800/60 rounded-xl border border-slate-700 overflow-hidden">
      <div className="px-4 py-2 border-b border-slate-700">
        <h3 className="text-sm font-semibold text-slate-200">{label}</h3>
      </div>
      <div className="divide-y divide-slate-700/50">
        {Object.entries(scores).map(([k, v]) => (
          <div key={k} className="flex items-center justify-between px-4 py-2">
            <span className="text-xs text-slate-400 font-mono">
              {k.replace(/_/g, " ")}
            </span>
            <span
              className={`text-xs font-semibold font-mono ${
                v >= 0 ? "text-green-400" : "text-red-400"
              }`}
            >
              {v >= 0 ? "+" : ""}
              {v}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function Settings() {
  const qc = useQueryClient();
  const { data: config, isLoading, error, refetch } = useQuery({
    queryKey: ["config"],
    queryFn: fetchConfig,
  });

  const [weights, setWeights] = useState<ConfigWeights | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  useEffect(() => {
    if (config && !dirty) setWeights({ ...config.weights });
  }, [config, dirty]);

  const total = weights
    ? Object.values(weights).reduce((s, v) => s + v, 0)
    : 0;
  const sumOk = Math.abs(total - 100) < 0.01;

  const saveMutation = useMutation({
    mutationFn: () => putWeights(weights!),
    onSuccess: () => {
      setSaveSuccess(true);
      setDirty(false);
      qc.invalidateQueries({ queryKey: ["config"] });
      qc.invalidateQueries({ queryKey: ["signals"] });
      setTimeout(() => setSaveSuccess(false), 3000);
    },
  });

  function handleChange(key: keyof ConfigWeights, raw: string) {
    const val = parseFloat(raw);
    if (isNaN(val)) return;
    setWeights((prev) => ({ ...prev!, [key]: val }));
    setDirty(true);
    setSaveSuccess(false);
  }

  if (isLoading) return <LoadingState label="Loading config…" />;
  if (error)
    return (
      <ErrorState
        message={`Failed to load config: ${(error as Error).message}`}
        onRetry={() => refetch()}
      />
    );
  if (!config || !weights) return null;

  return (
    <div className="p-6 max-w-3xl space-y-8">
      <div>
        <h1 className="text-xl font-bold text-slate-100">Strategy Settings</h1>
        <p className="text-sm text-slate-500 mt-1">
          Adjust component weights. All weights must sum to exactly 100.
        </p>
      </div>

      {/* Weight-change warning */}
      {dirty && (
        <div className="rounded-xl border border-amber-600/50 bg-amber-950/40 px-4 py-3 text-sm text-amber-300">
          <strong>Warning:</strong> Changing weights invalidates all prior signals. After saving,
          re-run the daily signal scan to regenerate scores with the new weights.
        </div>
      )}

      {/* Weights editor */}
      <div className="bg-slate-900 rounded-xl border border-slate-700 p-5 space-y-4">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-slate-200">Component Weights</h2>
          <span
            className={`text-sm font-mono font-bold ${
              sumOk ? "text-emerald-400" : "text-red-400"
            }`}
          >
            {total.toFixed(1)} / 100
          </span>
        </div>

        {WEIGHT_KEYS.map((key) => (
          <div key={key} className="flex items-center gap-4">
            <label className="w-44 text-sm text-slate-300 flex-shrink-0">
              {WEIGHT_LABELS[key]}
            </label>
            <input
              type="range"
              min={0}
              max={60}
              step={0.5}
              value={weights[key]}
              onChange={(e) => handleChange(key, e.target.value)}
              className="flex-1 accent-cyan-400"
            />
            <input
              type="number"
              min={0}
              max={100}
              step={0.1}
              value={weights[key]}
              onChange={(e) => handleChange(key, e.target.value)}
              className="w-16 bg-slate-800 border border-slate-600 rounded px-2 py-1 text-sm text-right font-mono text-slate-100 focus:outline-none focus:border-cyan-500"
            />
            <span className="text-slate-500 text-sm w-2">%</span>
          </div>
        ))}

        {/* Save button */}
        <div className="pt-2 flex items-center gap-4">
          <button
            onClick={() => saveMutation.mutate()}
            disabled={!sumOk || !dirty || saveMutation.isPending}
            className={`px-5 py-2 rounded-lg text-sm font-semibold transition-all ${
              !sumOk || !dirty
                ? "bg-slate-700 text-slate-500 cursor-not-allowed"
                : saveMutation.isPending
                ? "bg-cyan-600/50 text-cyan-300 cursor-wait"
                : "bg-cyan-600 text-white hover:bg-cyan-500"
            }`}
          >
            {saveMutation.isPending ? "Saving…" : "Save Weights"}
          </button>

          {saveSuccess && (
            <span className="text-sm text-emerald-400 font-medium">
              Saved! Re-run signals to apply.
            </span>
          )}
          {saveMutation.error && (
            <span className="text-sm text-red-400">
              {(saveMutation.error as Error).message}
            </span>
          )}
        </div>
      </div>

      {/* Signal thresholds (read-only display) */}
      <div className="bg-slate-900 rounded-xl border border-slate-700 p-5">
        <h2 className="text-sm font-semibold text-slate-200 mb-4">Signal Thresholds</h2>
        <div className="grid grid-cols-2 gap-3">
          {(
            [
              ["Strong Buy", config.thresholds.strong_buy, "text-emerald-400"],
              ["Buy", config.thresholds.buy, "text-green-400"],
              ["Sell", config.thresholds.sell, "text-orange-400"],
              ["Strong Sell", config.thresholds.strong_sell, "text-red-400"],
            ] as [string, number, string][]
          ).map(([label, val, cls]) => (
            <div
              key={label}
              className="flex items-center justify-between bg-slate-800 rounded-lg px-4 py-2.5"
            >
              <span className={`text-sm font-semibold ${cls}`}>{label}</span>
              <span className="text-sm font-mono text-slate-300">{val}</span>
            </div>
          ))}
        </div>
        <p className="text-xs text-slate-600 mt-3">
          Edit thresholds directly in config.yaml (restart backend to apply).
        </p>
      </div>

      {/* Per-pattern scoring tables */}
      <div>
        <h2 className="text-sm font-semibold text-slate-200 mb-4">Scoring Tables</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ScoreTable label="Candlestick Patterns" scores={config.candlestick.scores} />
          <ScoreTable label="3-Bar Patterns (P3)" scores={config.p3.scores} />
          <ScoreTable label="5-Bar Patterns (P5)" scores={config.p5.scores} />
          <ScoreTable label="EMA Stacking" scores={config.ema.stacking_scores} />
          <ScoreTable label="EMA Crossovers" scores={config.ema.cross_scores} />
          <ScoreTable label="Support / Resistance" scores={config.sr.scores} />
          <ScoreTable label="MACD Micro-signals" scores={config.macd.micro_signals} />
          <ScoreTable label="RSI Zones" scores={config.rsi.scores} />
        </div>
      </div>
    </div>
  );
}
