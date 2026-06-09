import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchSignals, postDailyRun, fetchDailyRun, fetchWatchlists } from "../lib/api";
import { MarketOverview } from "../components/MarketOverview";
import { SignalBadge, compositeColor } from "../components/SignalBadge";
import { ProgressBar, type ProgressInfo } from "../components/ProgressBar";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { useLang } from "../lib/LanguageContext";
import { ENTRY_COMPONENTS, EXIT_COMPONENTS, type SignalEntry } from "../lib/types";

type RunStatus = "idle" | "running" | "done" | "error";

function sideScore(entry: SignalEntry, names: readonly string[]): number {
  return names.reduce((s, n) => s + (entry.sub_scores[n] ?? 0), 0);
}

function ScoreCell({ value, accent }: { value: number; accent: string }) {
  return (
    <td className={`px-3 py-3 text-right text-xs font-mono ${value > 0 ? accent : "text-slate-600"}`}>
      {value.toFixed(0)}
    </td>
  );
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
          {entry.composite.toFixed(0)}
        </span>
      </td>
      <td className="px-4 py-3 text-right">
        <SignalBadge signal={entry.signal} />
      </td>
      <ScoreCell value={sideScore(entry, ENTRY_COMPONENTS)} accent="text-emerald-400" />
      <ScoreCell value={sideScore(entry, EXIT_COMPONENTS)} accent="text-orange-400" />
    </tr>
  );
}

function SectionTable({
  title, color, entries, emptyMessage, onRowClick,
}: {
  title: string;
  color: string;
  entries: SignalEntry[];
  emptyMessage: string;
  onRowClick: (sym: string) => void;
}) {
  const { t } = useLang();
  return (
    <div className="bg-slate-900 rounded-xl border border-slate-700 overflow-x-auto">
      <div className="px-4 py-2.5 border-b border-slate-700 flex items-center gap-2">
        <span className={`text-[10px] font-bold uppercase tracking-widest ${color}`}>{title}</span>
        <span className="text-xs text-slate-500">({entries.length})</span>
      </div>
      {entries.length === 0 ? (
        <p className="px-4 py-5 text-sm text-slate-500 italic">{emptyMessage}</p>
      ) : (
        <table className="w-full text-left min-w-[560px]">
          <thead>
            <tr className="border-b border-slate-800 text-[10px] text-slate-500 uppercase font-medium">
              <th className="px-4 py-2">{t("col_rank")}</th>
              <th className="px-4 py-2">{t("col_symbol")}</th>
              <th className="px-4 py-2 text-right">{t("col_score")}</th>
              <th className="px-4 py-2 text-right">{t("col_signal")}</th>
              <th className="px-3 py-2 text-right">{t("col_entry_score")}</th>
              <th className="px-3 py-2 text-right">{t("col_exit_score")}</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <SignalRow key={entry.symbol} entry={entry} onClick={() => onRowClick(entry.symbol)} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function RunButton({ status, onRun }: { status: RunStatus; onRun: () => void }) {
  const { t } = useLang();
  const cls = {
    idle: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20",
    running: "border-amber-500/40 bg-amber-500/10 text-amber-300 cursor-wait",
    done: "border-emerald-500/40 bg-emerald-500/20 text-emerald-200",
    error: "border-red-500/40 bg-red-500/20 text-red-300",
  }[status];
  const label = {
    idle: t("run_signals"), running: t("run_running"), done: t("run_done"), error: t("run_error"),
  }[status];
  return (
    <button
      onClick={onRun}
      disabled={status === "running"}
      className={`py-2 px-6 rounded-lg text-sm font-semibold border transition-all ${cls}`}
    >
      {label}
    </button>
  );
}

const BUY_SIGNALS = ["Buy", "Strong Buy"];
const SELL_SIGNALS = ["Sell", "Strong Sell"];

export function Dashboard() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { t } = useLang();

  const [status, setStatus] = useState<RunStatus>("idle");
  const [progress, setProgress] = useState<ProgressInfo | null>(null);
  const [universe, setUniverse] = useState("combined");

  const { data: signals, isLoading: sigLoading, error: sigError, refetch: sigRefetch } = useQuery({
    queryKey: ["signals", universe],
    queryFn: () => fetchSignals({ universe }),
    retry: false,
  });

  const { data: watchlists } = useQuery({
    queryKey: ["watchlists"],
    queryFn: fetchWatchlists,
    retry: false,
  });

  const pollJob = useCallback(
    (jobId: string) => {
      const interval = setInterval(async () => {
        try {
          const result = await fetchDailyRun(jobId);
          if (result.n_total !== undefined && result.n_done !== undefined && result.started_at !== undefined) {
            setProgress({
              nDone: result.n_done, nTotal: result.n_total,
              phase: result.phase ?? "", startedAt: result.started_at,
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

  async function handleRun() {
    try {
      setStatus("running");
      setProgress(null);
      const result = await postDailyRun({ universe });
      pollJob(result.job_id);
    } catch {
      setStatus("error");
      setTimeout(() => setStatus("idle"), 5000);
    }
  }

  const watchlistSymbols = new Set(
    (watchlists?.lists ?? []).flatMap((l) => l.symbols.map((s) => s.symbol)),
  );

  const buySignals =
    signals?.signals.filter((s) => BUY_SIGNALS.includes(s.signal)).sort((a, b) => b.composite - a.composite) ?? [];
  const sellSignals =
    signals?.signals.filter((s) => SELL_SIGNALS.includes(s.signal)).sort((a, b) => a.composite - b.composite) ?? [];
  const watchlistSignals = signals?.signals.filter((s) => watchlistSymbols.has(s.symbol)) ?? [];

  return (
    <div className="flex flex-col h-full">
      <MarketOverview />

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Universe selector + run */}
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-xs text-slate-400 shrink-0">{t("universe_label")}</label>
          <select
            value={universe}
            onChange={(e) => setUniverse(e.target.value)}
            className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100 focus:outline-none focus:border-cyan-500"
          >
            {(watchlists?.lists ?? []).map((l) => (
              <option key={l.name} value={`wl:${l.name}`}>{l.name}</option>
            ))}
            <option value="watchlist">{t("universe_watchlist")}</option>
            <option value="sp500">{t("universe_sp500")}</option>
            <option value="nasdaq100">{t("universe_nasdaq100")}</option>
            <option value="midcap">{t("universe_midcap")}</option>
            <option value="smallcap">{t("universe_smallcap")}</option>
            <option value="combined">{t("universe_combined")}</option>
          </select>
          <RunButton status={status} onRun={handleRun} />
          {status === "running" && progress && <div className="flex-1 min-w-[200px]"><ProgressBar {...progress} /></div>}
        </div>

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
                message={is404 ? t("no_signals_yet") : `${t("error")}: ${msg}`}
                onRetry={is404 ? undefined : () => sigRefetch()}
              />
            );
          })()
        ) : (
          <>
            <SectionTable
              title={t("section_buy")} color="text-emerald-400" entries={buySignals}
              emptyMessage={t("empty_buy")} onRowClick={(sym) => navigate(`/symbol/${sym}`)}
            />
            <SectionTable
              title={t("section_sell")} color="text-orange-400" entries={sellSignals}
              emptyMessage={t("empty_sell")} onRowClick={(sym) => navigate(`/symbol/${sym}`)}
            />
            <SectionTable
              title={t("section_watchlist")} color="text-cyan-400" entries={watchlistSignals}
              emptyMessage={t("empty_watchlist")} onRowClick={(sym) => navigate(`/symbol/${sym}`)}
            />
          </>
        )}

        <p className="text-xs text-slate-600">{t("click_row_hint")}</p>
      </div>
    </div>
  );
}
