import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchConfigStrategy, putConfigStrategy } from "../lib/api";
import { WatchlistEditor } from "../components/WatchlistEditor";
import { InverseEtfEditor } from "../components/InverseEtfEditor";
import { ScheduleToggle } from "../components/ScheduleToggle";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { exportSettingsToExcel } from "../lib/exportSettings";
import type { ConfigWeights, ConfigThresholds, ConfigResponse, ScoringTablesUpdate } from "../lib/types";

type Strategy = "long" | "short";

// ── helpers ──────────────────────────────────────────────────────────────────

const WEIGHT_KEYS: (keyof ConfigWeights)[] = [
  "candlestick", "p3", "p5", "volume", "ema", "sr", "macd", "rsi",
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

function scoreColor(v: number) {
  return v > 0 ? "text-emerald-400" : v < 0 ? "text-red-400" : "text-slate-400";
}

// ── Editable score table ──────────────────────────────────────────────────────

function ScoreTableEditor({
  label,
  scores,
  onChange,
}: {
  label: string;
  scores: Record<string, number>;
  onChange: (updated: Record<string, number>) => void;
}) {
  function handleChange(key: string, raw: string) {
    const val = parseFloat(raw);
    if (isNaN(val)) return;
    const clamped = Math.max(-100, Math.min(100, val));
    onChange({ ...scores, [key]: clamped });
  }

  return (
    <div className="bg-slate-800/60 rounded-xl border border-slate-700 overflow-hidden">
      <div className="px-4 py-2.5 border-b border-slate-700">
        <h3 className="text-sm font-semibold text-slate-200">{label}</h3>
      </div>
      <div className="divide-y divide-slate-700/40">
        {Object.entries(scores).map(([k, v]) => (
          <div key={k} className="flex items-center justify-between px-4 py-1.5 gap-3">
            <span className="text-xs text-slate-400 font-mono flex-1 truncate">
              {k.replace(/_/g, " ")}
            </span>
            <input
              type="number"
              min={-100}
              max={100}
              step={1}
              value={v}
              onChange={(e) => handleChange(k, e.target.value)}
              className={`w-20 text-right text-xs font-mono font-semibold bg-slate-900 border border-slate-700
                rounded px-2 py-0.5 focus:outline-none focus:border-cyan-500 ${scoreColor(v)}`}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Threshold editor ──────────────────────────────────────────────────────────

const THRESHOLD_META: Array<[keyof ConfigThresholds, string, string]> = [
  ["strong_buy",  "Strong Buy",  "text-emerald-400"],
  ["buy",         "Buy",         "text-green-400"],
  ["sell",        "Sell",        "text-orange-400"],
  ["strong_sell", "Strong Sell", "text-red-400"],
];

function ThresholdEditor({
  thresholds,
  onChange,
}: {
  thresholds: ConfigThresholds;
  onChange: (t: ConfigThresholds) => void;
}) {
  const ordered =
    thresholds.strong_sell < thresholds.sell &&
    thresholds.sell < 0 &&
    0 < thresholds.buy &&
    thresholds.buy < thresholds.strong_buy;

  function handleChange(key: keyof ConfigThresholds, raw: string) {
    const val = parseFloat(raw);
    if (isNaN(val)) return;
    onChange({ ...thresholds, [key]: val });
  }

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-3">
        {THRESHOLD_META.map(([key, label, cls]) => (
          <div key={key} className="flex items-center justify-between bg-slate-800 rounded-lg px-4 py-2">
            <span className={`text-sm font-semibold ${cls}`}>{label}</span>
            <input
              type="number"
              step={1}
              value={thresholds[key]}
              onChange={(e) => handleChange(key, e.target.value)}
              className="w-20 text-right text-sm font-mono text-slate-100 bg-slate-900 border border-slate-700
                rounded px-2 py-1 focus:outline-none focus:border-cyan-500"
            />
          </div>
        ))}
      </div>
      {!ordered && (
        <p className="text-xs text-red-400 mt-1">
          Must satisfy: Strong Sell &lt; Sell &lt; 0 &lt; Buy &lt; Strong Buy
        </p>
      )}
      <p className="text-xs text-slate-600">
        A composite score above "Buy" generates a Buy signal; below "Sell" generates a Sell signal.
      </p>
    </div>
  );
}

// ── Scoring tables derived from config ───────────────────────────────────────

function scoringTablesFromConfig(config: ConfigResponse): ScoringTablesUpdate {
  return {
    candlestick: { ...config.candlestick.scores },
    p3: { ...config.p3.scores },
    p5: { ...config.p5.scores },
    ema_stacking: { ...config.ema.stacking_scores },
    ema_cross: { ...config.ema.cross_scores },
    sr: { ...config.sr.scores },
    macd: { ...config.macd.micro_signals },
    rsi: { ...config.rsi.scores },
  };
}

// ── Main profile editor ───────────────────────────────────────────────────────

function ProfileEditor({ strategy }: { strategy: Strategy }) {
  const qc = useQueryClient();
  const isLong = strategy === "long";

  const { data: config, isLoading, error, refetch } = useQuery({
    queryKey: ["config", strategy],
    queryFn: () => fetchConfigStrategy(strategy),
  });

  const [weights, setWeights] = useState<ConfigWeights | null>(null);
  const [thresholds, setThresholds] = useState<ConfigThresholds | null>(null);
  const [scoringTables, setScoringTables] = useState<ScoringTablesUpdate | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  useEffect(() => {
    if (config && !dirty) {
      setWeights({ ...config.weights });
      setThresholds({ ...config.thresholds });
      setScoringTables(scoringTablesFromConfig(config));
    }
  }, [config, dirty]);

  const weightTotal = weights ? Object.values(weights).reduce((s, v) => s + v, 0) : 0;
  const weightsOk = Math.abs(weightTotal - 100) < 0.01;

  const thresholdsOk = thresholds
    ? thresholds.strong_sell < thresholds.sell &&
      thresholds.sell < 0 &&
      0 < thresholds.buy &&
      thresholds.buy < thresholds.strong_buy
    : false;

  const canSave = dirty && weightsOk && thresholdsOk;

  const saveMutation = useMutation({
    mutationFn: () =>
      putConfigStrategy(strategy, {
        weights: weights!,
        thresholds: thresholds!,
        scoring_tables: scoringTables!,
      }),
    onSuccess: () => {
      setSaveSuccess(true);
      setDirty(false);
      qc.invalidateQueries({ queryKey: ["config", strategy] });
      qc.invalidateQueries({ queryKey: ["signals"] });
      setTimeout(() => setSaveSuccess(false), 4000);
    },
  });

  function handleWeightChange(key: keyof ConfigWeights, raw: string) {
    const val = parseFloat(raw);
    if (isNaN(val)) return;
    setWeights((prev) => ({ ...prev!, [key]: val }));
    setDirty(true);
    setSaveSuccess(false);
  }

  function handleThresholdsChange(t: ConfigThresholds) {
    setThresholds(t);
    setDirty(true);
    setSaveSuccess(false);
  }

  function handleTableChange(tableKey: keyof ScoringTablesUpdate, updated: Record<string, number>) {
    setScoringTables((prev) => ({ ...prev!, [tableKey]: updated }));
    setDirty(true);
    setSaveSuccess(false);
  }

  if (isLoading) return <LoadingState label={`Loading ${strategy} config…`} />;
  if (error)
    return (
      <ErrorState
        message={`Failed to load ${strategy} config: ${(error as Error).message}`}
        onRetry={() => refetch()}
      />
    );
  if (!config || !weights || !thresholds || !scoringTables) return null;

  return (
    <div className="space-y-8">
      {/* Dirty / save bar */}
      {dirty && (
        <div className={`flex items-center justify-between gap-4 rounded-xl border px-4 py-3 ${
          isLong
            ? "border-emerald-600/50 bg-emerald-950/40"
            : "border-red-600/50 bg-red-950/40"
        }`}>
          <p className={`text-sm ${isLong ? "text-emerald-300" : "text-red-300"}`}>
            <strong>Unsaved changes</strong> to the{" "}
            <strong className="uppercase">{strategy}</strong> profile. Saving will
            invalidate prior {strategy} signals — re-run after saving.
          </p>
          <div className="flex items-center gap-3 flex-shrink-0">
            {saveSuccess && (
              <span className="text-sm text-emerald-400 font-medium">Saved!</span>
            )}
            {saveMutation.error && (
              <span className="text-xs text-red-400 max-w-xs">
                {(saveMutation.error as Error).message}
              </span>
            )}
            <button
              onClick={() => {
                setWeights({ ...config.weights });
                setThresholds({ ...config.thresholds });
                setScoringTables(scoringTablesFromConfig(config));
                setDirty(false);
              }}
              className="px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-slate-200 border border-slate-600 hover:border-slate-400 transition-colors"
            >
              Reset
            </button>
            <button
              onClick={() => saveMutation.mutate()}
              disabled={!canSave || saveMutation.isPending}
              className={`px-5 py-1.5 rounded-lg text-sm font-semibold transition-all ${
                !canSave
                  ? "bg-slate-700 text-slate-500 cursor-not-allowed"
                  : saveMutation.isPending
                  ? "bg-cyan-600/50 text-cyan-300 cursor-wait"
                  : "bg-cyan-600 text-white hover:bg-cyan-500"
              }`}
            >
              {saveMutation.isPending ? "Saving…" : `Save ${isLong ? "Long" : "Short"} Profile`}
            </button>
          </div>
        </div>
      )}

      {/* ── Component Weights ── */}
      <div className="bg-slate-900 rounded-xl border border-slate-700 p-5 space-y-4">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-slate-200">Component Weights</h2>
          <span className={`text-sm font-mono font-bold ${weightsOk ? "text-emerald-400" : "text-red-400"}`}>
            {weightTotal.toFixed(1)} / 100
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
              onChange={(e) => handleWeightChange(key, e.target.value)}
              className={`flex-1 ${isLong ? "accent-emerald-400" : "accent-red-400"}`}
            />
            <input
              type="number"
              min={0}
              max={100}
              step={0.1}
              value={weights[key]}
              onChange={(e) => handleWeightChange(key, e.target.value)}
              className="w-16 bg-slate-800 border border-slate-600 rounded px-2 py-1 text-sm
                text-right font-mono text-slate-100 focus:outline-none focus:border-cyan-500"
            />
            <span className="text-slate-500 text-sm w-2">%</span>
          </div>
        ))}
      </div>

      {/* ── Signal Thresholds ── */}
      <div className="bg-slate-900 rounded-xl border border-slate-700 p-5 space-y-3">
        <h2 className="text-sm font-semibold text-slate-200">Signal Thresholds</h2>
        <ThresholdEditor thresholds={thresholds} onChange={handleThresholdsChange} />
      </div>

      {/* ── Scoring Tables ── */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-200">Scoring Tables</h2>
          <p className="text-xs text-slate-500">Values must be between −100 and +100</p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ScoreTableEditor
            label="Candlestick Patterns"
            scores={scoringTables.candlestick!}
            onChange={(u) => handleTableChange("candlestick", u)}
          />
          <ScoreTableEditor
            label="3-Bar Patterns (P3)"
            scores={scoringTables.p3!}
            onChange={(u) => handleTableChange("p3", u)}
          />
          <ScoreTableEditor
            label="5-Bar Patterns (P5)"
            scores={scoringTables.p5!}
            onChange={(u) => handleTableChange("p5", u)}
          />
          <ScoreTableEditor
            label="EMA Stacking"
            scores={scoringTables.ema_stacking!}
            onChange={(u) => handleTableChange("ema_stacking", u)}
          />
          <ScoreTableEditor
            label="EMA Crossovers"
            scores={scoringTables.ema_cross!}
            onChange={(u) => handleTableChange("ema_cross", u)}
          />
          <ScoreTableEditor
            label="Support / Resistance"
            scores={scoringTables.sr!}
            onChange={(u) => handleTableChange("sr", u)}
          />
          <ScoreTableEditor
            label="MACD Micro-signals"
            scores={scoringTables.macd!}
            onChange={(u) => handleTableChange("macd", u)}
          />
          <ScoreTableEditor
            label="RSI Zones"
            scores={scoringTables.rsi!}
            onChange={(u) => handleTableChange("rsi", u)}
          />
        </div>
      </div>
    </div>
  );
}

// ── Export button ─────────────────────────────────────────────────────────────

function ExportButton() {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const { data: longCfg } = useQuery({
    queryKey: ["config", "long"],
    queryFn: () => fetchConfigStrategy("long"),
  });
  const { data: shortCfg } = useQuery({
    queryKey: ["config", "short"],
    queryFn: () => fetchConfigStrategy("short"),
  });

  async function handleExport() {
    if (!longCfg || !shortCfg) return;
    setBusy(true);
    setErr(null);
    try {
      exportSettingsToExcel(longCfg, shortCfg);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const ready = !!longCfg && !!shortCfg;

  return (
    <div className="flex items-center gap-3">
      <button
        onClick={handleExport}
        disabled={!ready || busy}
        className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold border transition-all ${
          !ready
            ? "border-slate-700 bg-slate-800/40 text-slate-500 cursor-not-allowed"
            : busy
            ? "border-amber-500/40 bg-amber-500/10 text-amber-300 cursor-wait"
            : "border-slate-600 bg-slate-800 text-slate-200 hover:border-cyan-500 hover:text-cyan-300 hover:bg-slate-800/80"
        }`}
      >
        {/* Download icon */}
        <svg className="w-4 h-4 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
          <path
            fillRule="evenodd"
            d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z"
            clipRule="evenodd"
          />
        </svg>
        {busy ? "Exporting…" : "Export Settings (.xlsx)"}
      </button>
      <span className="text-xs text-slate-500">
        Downloads both Long &amp; Short profiles in one Excel workbook
      </span>
      {err && <span className="text-xs text-red-400">{err}</span>}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function Settings() {
  const [activeStrategy, setActiveStrategy] = useState<Strategy>("long");

  return (
    <div className="p-6 max-w-3xl space-y-10">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-slate-100">Strategy Settings</h1>
          <p className="text-sm text-slate-500 mt-1">
            Two independent profiles — Long and Short. Edit weights, thresholds, and
            scoring tables for each. Changes take effect on the next signal run.
          </p>
        </div>
        <ExportButton />
      </div>

      {/* Profile tabs */}
      <div className="space-y-4">
        <div className="flex gap-1 bg-slate-800 rounded-lg p-1 w-fit">
          {(["long", "short"] as Strategy[]).map((s) => (
            <button
              key={s}
              onClick={() => setActiveStrategy(s)}
              className={`px-6 py-1.5 rounded text-sm font-semibold transition-all ${
                activeStrategy === s
                  ? s === "long"
                    ? "bg-emerald-600/30 text-emerald-300 border border-emerald-500/40"
                    : "bg-red-600/30 text-red-300 border border-red-500/40"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {s === "long" ? "Long Profile" : "Short Profile"}
            </button>
          ))}
        </div>

        <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold w-fit ${
          activeStrategy === "long"
            ? "border-emerald-500/40 bg-emerald-950/30 text-emerald-300"
            : "border-red-500/40 bg-red-950/30 text-red-300"
        }`}>
          <span className={`w-2 h-2 rounded-full ${activeStrategy === "long" ? "bg-emerald-400" : "bg-red-400"}`} />
          Editing: {activeStrategy === "long" ? "LONG" : "SHORT"} profile
        </div>

        <ProfileEditor key={activeStrategy} strategy={activeStrategy} />
      </div>

      <div className="border-t border-slate-800 pt-8 space-y-4">
        <h2 className="text-base font-bold text-slate-100">Watchlist</h2>
        <WatchlistEditor />
      </div>

      <div className="border-t border-slate-800 pt-8 space-y-4">
        <h2 className="text-base font-bold text-slate-100">Inverse-ETF Mapping</h2>
        <InverseEtfEditor />
      </div>

      <div className="border-t border-slate-800 pt-8 space-y-4">
        <h2 className="text-base font-bold text-slate-100">Daily Schedule</h2>
        <ScheduleToggle />
      </div>
    </div>
  );
}
