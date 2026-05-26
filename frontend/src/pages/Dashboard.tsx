import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchSignals, postDailyRun, fetchDailyRun, fetchWatchlist, fetchInverseEtfs } from "../lib/api";
import { MarketOverview } from "../components/MarketOverview";
import { SignalBadge, compositeColor } from "../components/SignalBadge";
import { ProgressBar, type ProgressInfo } from "../components/ProgressBar";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { useLang } from "../lib/LanguageContext";
import type { SignalEntry, InverseEtfMapResponse } from "../lib/types";

const COMPONENT_KEYS = ["candlestick", "p3", "p5", "volume", "ema", "sr", "macd", "rsi"] as const;
const COMPONENT_SHORT: Record<string, string> = {
  candlestick: "Candle", p3: "P3", p5: "P5", volume: "Vol",
  ema: "EMA", sr: "S/R", macd: "MACD", rsi: "RSI",
};

type RunStatus = "idle" | "running" | "done" | "error";

function SubScoreCell({ value }: { value: number }) {
  const color =
    value >= 50 ? "text-emerald-400"
    : value >= 0 ? "text-green-400"
    : value >= -50 ? "text-orange-400"
    : "text-red-400";
  return (
    <td className={`px-2 py-3 text-right text-xs font-mono ${color}`}>
      {value.toFixed(0)}
    </td>
  );
}

function inverseEtfLabel(
  entry: SignalEntry,
  etfMap: InverseEtfMapResponse | undefined,
) {
  if (entry.inverse_etf) return entry.inverse_etf;
  if (etfMap?.map[entry.symbol]) return etfMap.map[entry.symbol].inverse_etf_symbol;
  return null;
}

function SignalRow({
  entry,
  showInverseEtf,
  etfMap,
  strategy,
  runTimestamp,
  onClick,
}: {
  entry: SignalEntry;
  showInverseEtf: boolean;
  etfMap: InverseEtfMapResponse | undefined;
  strategy?: string;
  runTimestamp?: string;
  onClick: () => void;
}) {
  const { t } = useLang();
  const etf = showInverseEtf ? inverseEtfLabel(entry, etfMap) : null;
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
      {showInverseEtf && (
        <td className="px-4 py-3 text-sm">
          {etf ? (
            <span className="font-mono font-semibold text-amber-300">{etf}</span>
          ) : (
            <span className="text-slate-500 italic text-xs">{t("no_inverse_etf")}</span>
          )}
        </td>
      )}
      {COMPONENT_KEYS.map((k) => (
        <SubScoreCell key={k} value={entry.sub_scores[k]} />
      ))}
      {strategy && (
        <td className="px-3 py-3 text-[10px] text-slate-500 whitespace-nowrap">
          {strategy}
          {runTimestamp && (
            <><br />{new Date(runTimestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</>
          )}
        </td>
      )}
    </tr>
  );
}

function SectionTable({
  title,
  color,
  entries,
  showInverseEtf,
  etfMap,
  runTimestamp,
  emptyMessage,
  onRowClick,
}: {
  title: string;
  color: string;
  entries: SignalEntry[];
  showInverseEtf: boolean;
  etfMap: InverseEtfMapResponse | undefined;
  runTimestamp?: string;
  emptyMessage: string;
  onRowClick: (sym: string) => void;
}) {
  const { t } = useLang();
  return (
    <div className="bg-slate-900 rounded-xl border border-slate-700 overflow-x-auto">
      <div className={`px-4 py-2.5 border-b border-slate-700 flex items-center gap-2`}>
        <span className={`text-[10px] font-bold uppercase tracking-widest ${color}`}>
          {title}
        </span>
        <span className="text-xs text-slate-500">({entries.length})</span>
      </div>
      {entries.length === 0 ? (
        <p className="px-4 py-5 text-sm text-slate-500 italic">{emptyMessage}</p>
      ) : (
        <table className="w-full text-left min-w-[860px]">
          <thead>
            <tr className="border-b border-slate-800 text-[10px] text-slate-500 uppercase font-medium">
              <th className="px-4 py-2">{t("col_rank")}</th>
              <th className="px-4 py-2">{t("col_symbol")}</th>
              <th className="px-4 py-2 text-right">{t("col_score")}</th>
              <th className="px-4 py-2 text-right">{t("col_signal")}</th>
              {showInverseEtf && <th className="px-4 py-2">{t("col_inverse_etf")}</th>}
              {COMPONENT_KEYS.map((k) => (
                <th key={k} className="px-2 py-2 text-right">{COMPONENT_SHORT[k]}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <SignalRow
                key={entry.symbol}
                entry={entry}
                showInverseEtf={showInverseEtf}
                etfMap={etfMap}
                runTimestamp={runTimestamp}
                onClick={() => onRowClick(entry.symbol)}
              />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function RunButton({
  label,
  strategy,
  status,
  onRun,
}: {
  label: string;
  strategy: "long" | "short";
  status: RunStatus;
  onRun: () => void;
}) {
  const { t } = useLang();
  const isLong = strategy === "long";
  const baseColor = isLong
    ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
    : "border-red-500/40 bg-red-500/10 text-red-300 hover:bg-red-500/20";
  const runningColor = "border-amber-500/40 bg-amber-500/10 text-amber-300 cursor-wait";
  const doneColor = "border-emerald-500/40 bg-emerald-500/20 text-emerald-200";
  const errorColor = "border-red-500/40 bg-red-500/20 text-red-300";

  const cls = {
    idle: baseColor,
    running: runningColor,
    done: doneColor,
    error: errorColor,
  }[status];

  const labelMap = {
    idle: label,
    running: t("run_running"),
    done: t("run_done"),
    error: t("run_error"),
  };

  return (
    <button
      onClick={onRun}
      disabled={status === "running"}
      className={`flex-1 py-2 px-4 rounded-lg text-sm font-semibold border transition-all ${cls}`}
    >
      {labelMap[status]}
    </button>
  );
}

const LONG_SIGNALS: Array<"Buy" | "Strong Buy"> = ["Buy", "Strong Buy"];
const SHORT_SIGNALS: Array<"Sell" | "Strong Sell"> = ["Sell", "Strong Sell"];

export function Dashboard() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { t } = useLang();

  const [longStatus, setLongStatus] = useState<RunStatus>("idle");
  const [shortStatus, setShortStatus] = useState<RunStatus>("idle");
  const [longProgress, setLongProgress] = useState<ProgressInfo | null>(null);
  const [shortProgress, setShortProgress] = useState<ProgressInfo | null>(null);
  const [universe, setUniverse] = useState("combined");

  const { data: signals, isLoading: sigLoading, error: sigError, refetch: sigRefetch } = useQuery({
    queryKey: ["signals", universe],
    queryFn: () => fetchSignals({ universe }),
    retry: false,
  });

  const { data: watchlist } = useQuery({
    queryKey: ["watchlist"],
    queryFn: fetchWatchlist,
    retry: false,
  });

  const { data: etfMap } = useQuery({
    queryKey: ["inverseEtfs"],
    queryFn: fetchInverseEtfs,
    retry: false,
  });

  const pollJob = useCallback(
    (
      jobId: string,
      setStatus: (s: RunStatus) => void,
      setProgress: (p: ProgressInfo | null) => void,
    ) => {
      const interval = setInterval(async () => {
        try {
          const result = await fetchDailyRun(jobId);
          if (
            result.n_total !== undefined &&
            result.n_done !== undefined &&
            result.started_at !== undefined
          ) {
            setProgress({
              nDone: result.n_done,
              nTotal: result.n_total,
              phase: result.phase ?? "",
              startedAt: result.started_at,
            });
          }
          if (result.status === "done") {
            clearInterval(interval);
            setStatus("done");
            setProgress(null);
            qc.invalidateQueries({ queryKey: ["signals"] });
            setTimeout(() => setStatus("idle"), 4000);
          } else if (result.status === "error") {
            clearInterval(interval);
            setStatus("error");
            setProgress(null);
            setTimeout(() => setStatus("idle"), 5000);
          }
        } catch {
          clearInterval(interval);
          setStatus("error");
          setProgress(null);
          setTimeout(() => setStatus("idle"), 5000);
        }
      }, 1500);
    },
    [qc],
  );

  async function handleRun(strategy: "long" | "short") {
    const setStatus = strategy === "long" ? setLongStatus : setShortStatus;
    const setProgress = strategy === "long" ? setLongProgress : setShortProgress;
    try {
      setStatus("running");
      setProgress(null);
      const result = await postDailyRun({ universe, strategy });
      pollJob(result.job_id, setStatus, setProgress);
    } catch {
      setStatus("error");
      setTimeout(() => setStatus("idle"), 5000);
    }
  }

  const watchlistSymbols = new Set(watchlist?.symbols.map((s) => s.symbol) ?? []);

  const longSignals =
    signals?.signals
      .filter((s) => (LONG_SIGNALS as string[]).includes(s.signal))
      .sort((a, b) => b.composite - a.composite) ?? [];

  const shortSignals =
    signals?.signals
      .filter((s) => (SHORT_SIGNALS as string[]).includes(s.signal))
      .sort((a, b) => a.composite - b.composite) ?? [];

  const watchlistSignals =
    signals?.signals.filter((s) => watchlistSymbols.has(s.symbol)) ?? [];

  return (
    <div className="flex flex-col h-full">
      <MarketOverview />

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Universe selector */}
        <div className="flex items-center gap-3">
          <label className="text-xs text-slate-400 shrink-0">{t("universe_label")}</label>
          <select
            value={universe}
            onChange={(e) => setUniverse(e.target.value)}
            className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100 focus:outline-none focus:border-cyan-500"
          >
            <option value="watchlist">{t("universe_watchlist")}</option>
            <option value="sp500">{t("universe_sp500")}</option>
            <option value="nasdaq100">{t("universe_nasdaq100")}</option>
            <option value="midcap">{t("universe_midcap")}</option>
            <option value="smallcap">{t("universe_smallcap")}</option>
            <option value="combined">{t("universe_combined")}</option>
          </select>
        </div>

        {/* Run buttons */}
        <div className="flex gap-3">
          <div className="flex-1 space-y-2">
            <RunButton
              label={t("run_long")}
              strategy="long"
              status={longStatus}
              onRun={() => handleRun("long")}
            />
            {longStatus === "running" && longProgress && (
              <ProgressBar {...longProgress} />
            )}
          </div>
          <div className="flex-1 space-y-2">
            <RunButton
              label={t("run_short")}
              strategy="short"
              status={shortStatus}
              onRun={() => handleRun("short")}
            />
            {shortStatus === "running" && shortProgress && (
              <ProgressBar {...shortProgress} />
            )}
          </div>
        </div>

        {/* Signals meta */}
        {signals && (
          <p className="text-xs text-slate-600">
            {t("last_run")} #{signals.run_id} · {signals.date} · {signals.n_signals} {t("total_signals")}
          </p>
        )}

        {sigLoading ? (
          <LoadingState label={t("loading")} />
        ) : sigError ? (
          (() => {
            const msg = (sigError as Error).message;
            const is404 = msg.startsWith("404");
            return (
              <ErrorState
                message={
                  is404
                    ? t("no_signals_yet")
                    : `${t("error")}: ${msg}`
                }
                onRetry={is404 ? undefined : () => sigRefetch()}
              />
            );
          })()
        ) : (
          <>
            {/* Section 1 — Long */}
            <SectionTable
              title={t("section_long")}
              color="text-emerald-400"
              entries={longSignals}
              showInverseEtf={false}
              etfMap={etfMap}
              runTimestamp={signals?.run_timestamp}
              emptyMessage={t("empty_long")}
              onRowClick={(sym) => navigate(`/symbol/${sym}`)}
            />

            {/* Section 2 — Short */}
            <SectionTable
              title={t("section_short")}
              color="text-red-400"
              entries={shortSignals}
              showInverseEtf={true}
              etfMap={etfMap}
              runTimestamp={signals?.run_timestamp}
              emptyMessage={t("empty_short")}
              onRowClick={(sym) => navigate(`/symbol/${sym}`)}
            />

            {/* Section 3 — Watchlist */}
            <SectionTable
              title={t("section_watchlist")}
              color="text-cyan-400"
              entries={watchlistSignals}
              showInverseEtf={true}
              etfMap={etfMap}
              runTimestamp={signals?.run_timestamp}
              emptyMessage={t("empty_watchlist")}
              onRowClick={(sym) => navigate(`/symbol/${sym}`)}
            />
          </>
        )}

        <p className="text-xs text-slate-600">
          {t("click_row_hint")}
        </p>
      </div>
    </div>
  );
}
