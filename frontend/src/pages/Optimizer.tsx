import { useState, useRef, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  postOptimize,
  fetchOptimize,
  promoteCandidate,
  optimizeReportUrl,
  fetchWatchlists,
} from "../lib/api";
import { ProgressBar, type ProgressInfo } from "../components/ProgressBar";
import { useLang } from "../lib/LanguageContext";
import type { OptimizeStatus } from "../lib/types";

const today = new Date().toISOString().slice(0, 10);
const fiveYearsAgo = new Date(Date.now() - 5 * 365 * 24 * 60 * 60 * 1000)
  .toISOString()
  .slice(0, 10);

const ENTRY_WEIGHT_ORDER = ["macd_hidden_bull", "rsi_hidden_bull", "rsi_zone", "demark_td9_buy"];
const EXIT_WEIGHT_ORDER = ["demark_td13_sell", "macd_regular_bear", "rsi_regular_bear", "demark_td9_sell"];

// Which metric keys to surface, and how to format each.
type Fmt = "pct" | "num" | "ratio";
const METRIC_ROWS: Array<[string, Fmt]> = [
  ["cagr", "pct"],
  ["total_return", "pct"],
  ["sharpe_ratio", "num"],
  ["max_drawdown", "pct"],
  ["win_rate", "ratio"],
  ["profit_factor", "num"],
];

function fmtMetric(v: number | undefined, fmt: Fmt): string {
  if (v === undefined || v === null || Number.isNaN(v)) return "—";
  if (fmt === "pct") return `${v.toFixed(1)}%`;
  if (fmt === "ratio") return `${(v * 100).toFixed(0)}%`;
  return v.toFixed(2);
}

// ── Small inputs ────────────────────────────────────────────────────────────────

function NumInput({
  label, value, onChange, step, min, suffix,
}: {
  label: string; value: number; onChange: (n: number) => void;
  step?: number; min?: number; suffix?: string;
}) {
  return (
    <div>
      <label className="block text-xs text-slate-400 mb-1">{label}</label>
      <div className="relative">
        <input
          type="number" value={value} step={step ?? 1} min={min ?? 0}
          onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
          className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 font-mono focus:outline-none focus:border-cyan-500 pr-8"
        />
        {suffix && (
          <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-slate-500 pointer-events-none">
            {suffix}
          </span>
        )}
      </div>
    </div>
  );
}

function Toggle({ label, checked, onChange, hint }: {
  label: string; checked: boolean; onChange: (b: boolean) => void; hint?: string;
}) {
  return (
    <label className="flex items-start gap-3 cursor-pointer">
      <input
        type="checkbox" checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 accent-cyan-500"
      />
      <span>
        <span className="text-sm text-slate-200">{label}</span>
        {hint && <span className="block text-[11px] text-slate-500">{hint}</span>}
      </span>
    </label>
  );
}

// ── Verdict banner ──────────────────────────────────────────────────────────────

function VerdictBanner({ result }: { result: OptimizeStatus }) {
  const { t } = useLang();
  const tier = result.verdict_tier ?? "OVERFIT";
  const pass = result.pass_verdict ?? false;
  const palette: Record<string, string> = {
    ROBUST: "border-emerald-600/50 bg-emerald-950/30 text-emerald-300",
    SUSPECT: "border-amber-600/50 bg-amber-950/30 text-amber-300",
    OVERFIT: "border-red-700/50 bg-red-950/30 text-red-300",
  };
  return (
    <div className={`rounded-xl border px-5 py-4 ${palette[tier] ?? palette.OVERFIT}`}>
      <div className="flex items-center gap-3">
        <span className="text-2xl">{pass ? "✅" : "❌"}</span>
        <div>
          <p className="text-sm font-bold uppercase tracking-wider">
            {pass ? t("opt_pass") : t("opt_fail")} · {tier}
          </p>
          <p className="text-xs opacity-80">
            {result.n_trials} {t("opt_trials_done")} · {result.wall_clock_seconds?.toFixed(0)}s ·{" "}
            {result.universe_size} {t("opt_symbols")}
          </p>
        </div>
      </div>
      {result.verdict_notes && result.verdict_notes.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs">
          {result.verdict_notes.map((n, i) => (
            <li key={i} className="opacity-90">• {n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── IS / Holdout / Walk-forward metrics table ─────────────────────────────────

function MetricsTable({ result }: { result: OptimizeStatus }) {
  const { t } = useLang();
  const LABELS: Record<string, string> = {
    cagr: t("m_cagr"), total_return: t("m_total_return"),
    sharpe_ratio: t("m_sharpe"), max_drawdown: t("m_max_drawdown"),
    win_rate: t("m_win_rate"), profit_factor: t("m_profit_factor"),
  };
  const is = result.insample_metrics ?? {};
  const ho = result.holdout_metrics ?? {};
  const wf = result.wf_metrics ?? {};
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl overflow-hidden">
      <div className="px-4 py-2.5 border-b border-slate-700 text-[10px] font-bold uppercase tracking-widest text-slate-400">
        {t("opt_metrics_title")}
      </div>
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-slate-800 text-[10px] text-slate-500 uppercase font-medium">
            <th className="px-4 py-2">{t("m_metric")}</th>
            <th className="px-4 py-2 text-right">{t("opt_in_sample")}</th>
            <th className="px-4 py-2 text-right">{t("opt_holdout")}</th>
            <th className="px-4 py-2 text-right text-cyan-500">{t("opt_walk_fwd")}</th>
          </tr>
        </thead>
        <tbody>
          {METRIC_ROWS.map(([key, fmt]) => (
            <tr key={key} className="border-b border-slate-800/50">
              <td className="px-4 py-2 text-xs text-slate-400">{LABELS[key] ?? key}</td>
              <td className="px-4 py-2 text-right text-sm font-mono text-slate-300">{fmtMetric(is[key], fmt)}</td>
              <td className="px-4 py-2 text-right text-sm font-mono text-slate-300">{fmtMetric(ho[key], fmt)}</td>
              <td className="px-4 py-2 text-right text-sm font-mono text-slate-100">{fmtMetric(wf[key], fmt)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Benchmark (holdout) ───────────────────────────────────────────────────────

function BenchmarkRow({ result }: { result: OptimizeStatus }) {
  const { t } = useLang();
  const bm = result.holdout_benchmark_metrics ?? {};
  const ho = result.holdout_metrics ?? {};
  if (bm.cagr === undefined) return null;
  const beats = (ho.cagr ?? 0) > (bm.cagr ?? 0);
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 flex flex-wrap items-center gap-x-8 gap-y-2 text-sm">
      <span className="text-xs text-slate-500 uppercase tracking-widest">{t("opt_vs_qqq")}</span>
      <span className="font-mono text-slate-300">QQQ CAGR {fmtMetric(bm.cagr, "pct")}</span>
      <span className="font-mono text-slate-300">QQQ Sharpe {fmtMetric(bm.sharpe_ratio, "num")}</span>
      <span className={`font-semibold ${beats ? "text-emerald-400" : "text-red-400"}`}>
        {t("opt_beats_qqq")}: {beats ? t("opt_yes") : t("opt_no")}
      </span>
    </div>
  );
}

// ── Anti-overfitting summary ──────────────────────────────────────────────────

function AntiOverfit({ result }: { result: OptimizeStatus }) {
  const { t } = useLang();
  const la = (result.luck_audit ?? {}) as Record<string, number | string>;
  const cl = (result.cluster_analysis ?? {}) as Record<string, string>;
  const pert = (result.perturbation_results ?? []).filter((p) => !("error" in p));
  const meanSharpe =
    pert.length > 0
      ? pert.reduce((a, p) => a + (Number(p.sharpe) || 0), 0) / pert.length
      : null;

  const Card = ({ title, children }: { title: string; children: React.ReactNode }) => (
    <div className="bg-slate-900 border border-slate-700 rounded-xl p-4 space-y-1">
      <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">{title}</p>
      <div className="text-xs text-slate-300">{children}</div>
    </div>
  );

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
      <Card title={t("opt_luck_audit")}>
        <p className="font-mono text-slate-200">
          {String(la.n_holdout_winners ?? 0)}/{String(la.top_200_evaluated_on_holdout ?? 0)} {t("opt_beat_qqq_holdout")}
        </p>
        <p className="text-slate-500">
          {t("opt_random_baseline")}: {String(la.null_holdout_wins ?? 0)}/{String(la.null_trials ?? 0)}
        </p>
        {la.assessment && <p className="mt-1 text-slate-400">{String(la.assessment)}</p>}
      </Card>
      <Card title={t("opt_cluster")}>
        <p className="text-slate-400">{cl.assessment ? String(cl.assessment) : "—"}</p>
      </Card>
      <Card title={t("opt_perturbation")}>
        {meanSharpe === null ? (
          <p className="text-slate-500">—</p>
        ) : (
          <p className="font-mono text-slate-200">
            {pert.length} {t("opt_nudges")} · {t("opt_mean_holdout_sharpe")} {meanSharpe.toFixed(3)}
          </p>
        )}
      </Card>
    </div>
  );
}

// ── Best weights ──────────────────────────────────────────────────────────────

function BestWeights({ result }: { result: OptimizeStatus }) {
  const { t } = useLang();
  const best = result.best_strat;
  if (!best) return null;
  type TKey = Parameters<typeof t>[0];
  const Side = ({
    titleKey, order, side, accent,
  }: {
    titleKey: TKey; order: string[];
    side: { threshold: number; conf_window: number; weights: Record<string, number> };
    accent: string;
  }) => (
    <div className="bg-slate-900 border border-slate-700 rounded-xl p-4 space-y-2">
      <p className={`text-xs font-bold ${accent}`}>{t(titleKey)}</p>
      <table className="w-full text-sm">
        <tbody>
          {order.map((k) => (
            <tr key={k} className="border-b border-slate-800/50">
              <td className="py-1 text-xs text-slate-400">{t(`w_${k}` as TKey)}</td>
              <td className="py-1 text-right font-mono text-slate-200">{(side.weights[k] ?? 0).toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-xs text-slate-500">
        {t("opt_threshold")}: <span className="font-mono text-slate-300">{side.threshold.toFixed(0)}</span>
        {"  ·  "}
        {t("cfg_conf_window")}: <span className="font-mono text-slate-300">{side.conf_window}</span>
      </p>
    </div>
  );
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      <Side titleKey="cfg_entry_section" order={ENTRY_WEIGHT_ORDER} side={best.entry} accent="text-emerald-400" />
      <Side titleKey="cfg_exit_section" order={EXIT_WEIGHT_ORDER} side={best.exit} accent="text-orange-400" />
    </div>
  );
}

// ── Promote action ────────────────────────────────────────────────────────────

function PromoteBar({ jobId, result }: { jobId: string; result: OptimizeStatus }) {
  const { t } = useLang();
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function doPromote() {
    setBusy(true);
    setErr(null);
    try {
      await promoteCandidate(jobId);
      setDone(true);
      setConfirm(false);
      qc.invalidateQueries({ queryKey: ["config"] });
      qc.invalidateQueries({ queryKey: ["signals"] });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <a
          href={optimizeReportUrl(jobId)}
          target="_blank"
          rel="noopener noreferrer"
          className="px-4 py-2 rounded-lg text-sm font-semibold border border-slate-600 bg-slate-800 text-slate-200 hover:border-cyan-500 hover:text-cyan-300 transition-all"
        >
          {t("opt_view_report")}
        </a>
        {!confirm && !done && (
          <button
            onClick={() => setConfirm(true)}
            className="px-4 py-2 rounded-lg text-sm font-semibold bg-cyan-600 text-white hover:bg-cyan-500 transition-all"
          >
            {t("opt_promote")}
          </button>
        )}
        {done && <span className="text-sm text-emerald-400 font-medium">{t("opt_promoted")}</span>}
      </div>

      {!result.pass_verdict && !confirm && !done && (
        <p className="text-[11px] text-amber-400/80">{t("opt_promote_fail_warn")}</p>
      )}

      {confirm && (
        <div className="rounded-lg border border-amber-600/40 bg-amber-950/30 px-4 py-3 space-y-2">
          <p className="text-xs text-amber-200">{t("opt_promote_confirm")}</p>
          <div className="flex items-center gap-3">
            <button
              onClick={doPromote}
              disabled={busy}
              className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-amber-600 text-white hover:bg-amber-500 disabled:opacity-60"
            >
              {busy ? t("saving") : t("opt_promote_yes")}
            </button>
            <button
              onClick={() => setConfirm(false)}
              className="px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-slate-200 border border-slate-600"
            >
              {t("reset")}
            </button>
          </div>
        </div>
      )}
      {err && <p className="text-xs text-red-400">{err}</p>}
      {result.candidate_path && (
        <p className="text-[10px] text-slate-600 font-mono break-all">{result.candidate_path}</p>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function Optimizer() {
  const { t } = useLang();

  const { data: watchlists } = useQuery({ queryKey: ["watchlists"], queryFn: fetchWatchlists, retry: false });
  const [universe, setUniverse] = useState("watchlist");
  const [start, setStart] = useState(fiveYearsAgo);
  const [end, setEnd] = useState(today);
  const [trials, setTrials] = useState(200);
  const [folds, setFolds] = useState(4);
  const [seed, setSeed] = useState(42);
  const [tuneWindows, setTuneWindows] = useState(false);
  const [tuneSizing, setTuneSizing] = useState(false);

  const [jobId, setJobId] = useState<string | null>(null);
  const [result, setResult] = useState<OptimizeStatus | null>(null);
  const [polling, setPolling] = useState(false);
  const [progress, setProgress] = useState<ProgressInfo | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function handleRun() {
    setSubmitError(null);
    setResult(null);
    setProgress(null);
    setPolling(true);
    try {
      const job = await postOptimize({
        universe, start, end, trials, folds, seed,
        include_scoring_tables: tuneWindows,
        include_sizing: tuneSizing,
      });
      setJobId(job.job_id);
      pollRef.current = setInterval(async () => {
        try {
          const r = await fetchOptimize(job.job_id);
          if (r.n_total !== undefined && r.n_done !== undefined && r.started_at) {
            setProgress({ nDone: r.n_done, nTotal: r.n_total, phase: r.phase ?? "", startedAt: r.started_at });
          }
          if (r.status === "done" || r.status === "error") {
            clearInterval(pollRef.current!);
            pollRef.current = null;
            setPolling(false);
            setProgress(null);
            setResult(r);
          }
        } catch (e) {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          setPolling(false);
          setProgress(null);
          setSubmitError((e as Error).message);
        }
      }, 1500);
    } catch (e) {
      setPolling(false);
      setSubmitError((e as Error).message);
    }
  }

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  return (
    <div className="p-6 space-y-6 max-w-5xl">
      <div>
        <h1 className="text-xl font-bold text-slate-100">{t("opt_title")}</h1>
        <p className="text-sm text-slate-500 mt-1">{t("opt_desc")}</p>
      </div>

      {/* Parameters */}
      <div className="bg-slate-900 rounded-xl border border-slate-700 p-5 space-y-5">
        <h2 className="text-sm font-semibold text-slate-200">{t("bt_params")}</h2>

        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-xs text-slate-400 mb-1">{t("universe_label")}</label>
            <select
              value={universe}
              onChange={(e) => setUniverse(e.target.value)}
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500"
            >
              <option value="watchlist">{t("universe_watchlist")} ({t("opt_all_lists")})</option>
              {(watchlists?.lists ?? []).map((l) => (
                <option key={l.name} value={`wl:${l.name}`}>{l.name}</option>
              ))}
              <option value="sp500">{t("universe_sp500")}</option>
              <option value="nasdaq100">{t("universe_nasdaq100")}</option>
              <option value="midcap">{t("universe_midcap")}</option>
              <option value="smallcap">{t("universe_smallcap")}</option>
              <option value="combined">{t("universe_combined")}</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">{t("bt_start_date")}</label>
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)}
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500" />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">{t("bt_end_date")}</label>
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)}
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500" />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-4">
          <NumInput label={t("opt_trials")} value={trials} onChange={(n) => setTrials(Math.max(1, Math.round(n)))} step={50} min={1} />
          <NumInput label={t("opt_folds")} value={folds} onChange={(n) => setFolds(Math.max(2, Math.round(n)))} step={1} min={2} />
          <NumInput label={t("opt_seed")} value={seed} onChange={(n) => setSeed(Math.round(n))} step={1} />
        </div>

        <div className="border-t border-slate-800 pt-4 space-y-3">
          <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">{t("opt_advanced")}</p>
          <Toggle label={t("opt_tune_windows")} hint={t("opt_tune_windows_hint")} checked={tuneWindows} onChange={setTuneWindows} />
          <Toggle label={t("opt_tune_sizing")} hint={t("opt_tune_sizing_hint")} checked={tuneSizing} onChange={setTuneSizing} />
        </div>

        <div className="border-t border-slate-800 pt-4 flex items-center gap-4">
          <button
            onClick={handleRun}
            disabled={polling}
            className={`px-6 py-2 rounded-lg text-sm font-semibold transition-all ${
              polling ? "bg-amber-500/20 text-amber-300 border border-amber-500/40 cursor-wait" : "bg-cyan-600 text-white hover:bg-cyan-500"
            }`}
          >
            {polling ? t("opt_running") : t("opt_run")}
          </button>
          {jobId && polling && <span className="text-xs text-slate-500 font-mono">Job {jobId}</span>}
        </div>

        {submitError && (
          <div className="text-sm text-red-400 bg-red-950/40 border border-red-800 rounded-lg px-4 py-2">{submitError}</div>
        )}
      </div>

      {/* Progress */}
      {polling && (
        <div className="bg-slate-900 border border-slate-700 rounded-xl px-5 py-4 space-y-3">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">{t("opt_running_label")}</p>
          {progress ? (
            <ProgressBar {...progress} />
          ) : (
            <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div className="h-full w-1/3 bg-cyan-600 rounded-full animate-pulse" />
            </div>
          )}
        </div>
      )}

      {/* Error */}
      {result && result.status === "error" && (
        <div className="rounded-xl border border-red-800 bg-red-950/40 px-5 py-4 text-red-300 text-sm">
          {t("opt_failed")}{result.error}
        </div>
      )}

      {/* Results */}
      {result && result.status === "done" && (
        <div className="space-y-5">
          <p className="text-xs text-slate-500">
            {t("opt_in_sample")} {result.insample_start} → {result.insample_end} ·{" "}
            {t("opt_holdout")} {result.holdout_start} → {result.holdout_end}
          </p>
          <VerdictBanner result={result} />
          <MetricsTable result={result} />
          <BenchmarkRow result={result} />
          <div>
            <h2 className="text-sm font-semibold text-slate-200 mb-2">{t("opt_antioverfit")}</h2>
            <AntiOverfit result={result} />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-slate-200 mb-2">{t("opt_best_config")}</h2>
            <BestWeights result={result} />
          </div>
          {jobId && <PromoteBar jobId={jobId} result={result} />}
        </div>
      )}
    </div>
  );
}
