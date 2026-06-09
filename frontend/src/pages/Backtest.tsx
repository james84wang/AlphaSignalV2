import { useState, useRef, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { postBacktest, fetchBacktest, fetchWatchlists } from "../lib/api";
import { ProgressBar, type ProgressInfo } from "../components/ProgressBar";
import { TradeChart } from "../components/TradeChart";
import { fmtMoney } from "../lib/format";
import { useLang } from "../lib/LanguageContext";
import type {
  BacktestResult,
  BacktestMetrics,
  BenchmarkMetrics,
  Comparison,
  ConstraintCounts,
  TradeEntry,
} from "../lib/types";
import { createChart, ColorType, CrosshairMode, LineStyle } from "lightweight-charts";

const today = new Date().toISOString().slice(0, 10);
const fiveYearsAgo = new Date(Date.now() - 5 * 365 * 24 * 60 * 60 * 1000)
  .toISOString()
  .slice(0, 10);

// ── Small reusable components ─────────────────────────────────────────────────

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-slate-800 rounded-xl px-4 py-3">
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className="text-lg font-bold font-mono text-slate-100">{value}</p>
    </div>
  );
}

function NumInput({
  label,
  value,
  onChange,
  step,
  min,
  suffix,
}: {
  label: string;
  value: number;
  onChange: (n: number) => void;
  step?: number;
  min?: number;
  suffix?: string;
}) {
  return (
    <div>
      <label className="block text-xs text-slate-400 mb-1">{label}</label>
      <div className="relative">
        <input
          type="number"
          value={value}
          step={step ?? 1}
          min={min ?? 0}
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

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-3">
      {children}
    </p>
  );
}

// ── Equity curve chart (strategy + optional benchmark overlay) ────────────────

function EquityCurveChart({
  data,
  benchmarkData,
  benchmarkLabel,
  strategyLabel,
}: {
  data: Array<{ date: string; equity: number }>;
  benchmarkData?: Array<{ date: string; equity: number }>;
  benchmarkLabel?: string;
  strategyLabel?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || data.length === 0) return;
    const chart = createChart(ref.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#0f172a" },
        textColor: "#94a3b8",
      },
      grid: { vertLines: { color: "#1e293b" }, horzLines: { color: "#1e293b" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#334155" },
      timeScale: { borderColor: "#334155" },
      width: ref.current.clientWidth,
      height: 240,
    });

    const strategySeries = chart.addLineSeries({
      color: "#22d3ee",
      lineWidth: 2,
      priceLineVisible: false,
      title: strategyLabel ?? "Strategy",
    });
    strategySeries.setData(data.map((d) => ({ time: d.date as string, value: d.equity })));

    if (benchmarkData && benchmarkData.length > 0) {
      const bkSeries = chart.addLineSeries({
        color: "#64748b",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        priceLineVisible: false,
        title: benchmarkLabel ?? "Benchmark",
      });
      bkSeries.setData(benchmarkData.map((d) => ({ time: d.date as string, value: d.equity })));
    }

    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => {
      if (ref.current) chart.applyOptions({ width: ref.current.clientWidth });
    });
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.remove();
    };
  }, [data, benchmarkData, benchmarkLabel, strategyLabel]);

  return <div ref={ref} />;
}

// ── Metrics panels ────────────────────────────────────────────────────────────

function MetricsDisplay({ metrics }: { metrics: BacktestMetrics }) {
  const { t } = useLang();
  const pct = (n: number) => `${n.toFixed(1)}%`;
  const winRate = metrics.win_rate ?? metrics.hit_rate;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3">
      <MetricCard label={t("m_total_return")}  value={pct(metrics.total_return_pct)} />
      <MetricCard label={t("m_cagr")}           value={pct(metrics.cagr)} />
      <MetricCard label={t("m_sharpe")}         value={metrics.sharpe.toFixed(2)} />
      <MetricCard label={t("m_max_drawdown")}   value={pct(metrics.max_drawdown_pct)} />
      <MetricCard label={t("m_final_equity")}   value={fmtMoney(metrics.final_equity)} />
      <MetricCard label={t("m_win_rate")}       value={pct(winRate * 100)} />
      <MetricCard label={t("m_profit_factor")}  value={metrics.profit_factor.toFixed(2)} />
      <MetricCard label={t("m_avg_win")}        value={fmtMoney(metrics.avg_win)} />
      <MetricCard label={t("m_avg_loss")}       value={fmtMoney(metrics.avg_loss)} />
      <MetricCard label={t("m_n_trades")}       value={String(metrics.n_trades)} />
      <MetricCard label={t("m_exposure")}       value={pct(metrics.exposure_pct)} />
      {metrics.win_loss_ratio !== undefined && (
        <MetricCard label={t("m_win_loss_ratio")} value={metrics.win_loss_ratio.toFixed(2)} />
      )}
      {metrics.total_fees !== undefined && (
        <MetricCard label={t("m_total_fees")}   value={fmtMoney(metrics.total_fees)} />
      )}
      {metrics.turnover !== undefined && (
        <MetricCard label={t("m_turnover")}     value={pct(metrics.turnover * 100)} />
      )}
      {metrics.avg_holding_days !== undefined && (
        <MetricCard label={t("m_avg_hold")}     value={metrics.avg_holding_days.toFixed(1)} />
      )}
    </div>
  );
}

function BenchmarkMetricsDisplay({ metrics }: { metrics: BenchmarkMetrics }) {
  const { t } = useLang();
  // Backend returns these already as percentages (e.g. 15.2, not 0.152)
  const pct = (n: number) => `${n.toFixed(1)}%`;
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
      <MetricCard label={t("m_total_return")} value={pct(metrics.total_return)} />
      <MetricCard label={t("m_cagr")}         value={pct(metrics.cagr)} />
      <MetricCard label={t("m_sharpe")}       value={metrics.sharpe_ratio.toFixed(2)} />
      <MetricCard label={t("m_max_drawdown")} value={pct(metrics.max_drawdown)} />
      <MetricCard label={t("m_final_equity")} value={fmtMoney(metrics.final_equity)} />
    </div>
  );
}

// ── Strategy vs Benchmark comparison table ────────────────────────────────────

function ComparisonTable({
  comparison,
  benchmarkSymbol,
}: {
  comparison: Comparison;
  benchmarkSymbol?: string;
}) {
  const { t } = useLang();

  const METRIC_LABELS: Record<string, string> = {
    total_return: t("m_total_return"),
    cagr: t("m_cagr"),
    sharpe_ratio: t("m_sharpe"),
    max_drawdown: t("m_max_drawdown"),
    final_equity: t("m_final_equity"),
  };

  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl overflow-hidden">
      <div className="px-4 py-2.5 border-b border-slate-700 text-[10px] font-bold uppercase tracking-widest text-slate-400">
        {t("bt_strategy")} vs {benchmarkSymbol ?? "Benchmark"} ({t("bt_buy_hold")})
      </div>
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-slate-800 text-[10px] text-slate-500 uppercase font-medium">
            <th className="px-4 py-2">{t("m_metric")}</th>
            <th className="px-4 py-2 text-right text-cyan-500">{t("bt_strategy")}</th>
            <th className="px-4 py-2 text-right text-slate-400">{benchmarkSymbol ?? "Benchmark"}</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(comparison.metrics).map(([key, row]) => (
            <tr key={key} className="border-b border-slate-800/50">
              <td className="px-4 py-2 text-xs text-slate-400">
                {METRIC_LABELS[key] ?? key}
              </td>
              <td className="px-4 py-2 text-right text-sm font-mono text-slate-100">
                {formatComparisonVal(key, row.strategy)}
              </td>
              <td className="px-4 py-2 text-right text-sm font-mono text-slate-400">
                {formatComparisonVal(key, row.benchmark)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {comparison.fairness_caveat && (
        <p className="px-4 py-2 text-[10px] text-slate-500 italic border-t border-slate-800">
          {comparison.fairness_caveat}
        </p>
      )}
    </div>
  );
}

function formatComparisonVal(key: string, val: number): string {
  if (key === "final_equity") return fmtMoney(val);
  // Backend already returns these as percentages (e.g. 15.2, not 0.152)
  if (["total_return", "cagr", "max_drawdown"].includes(key)) return `${val.toFixed(1)}%`;
  return val.toFixed(2);
}

// ── Constraint counts chip ────────────────────────────────────────────────────

function ConstraintChip({ counts }: { counts: ConstraintCounts }) {
  const { t } = useLang();
  const total = counts.skipped_no_slot + counts.skipped_no_capital + counts.skipped_top_n;
  if (total === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 text-[11px]">
      <span className="text-slate-500">{t("bt_skipped")}</span>
      {counts.skipped_top_n > 0 && (
        <span className="rounded-full bg-amber-900/40 border border-amber-700/50 px-2.5 py-0.5 text-amber-400">
          {counts.skipped_top_n} {t("bt_ranked_out")}
        </span>
      )}
      {counts.skipped_no_slot > 0 && (
        <span className="rounded-full bg-orange-900/40 border border-orange-700/50 px-2.5 py-0.5 text-orange-400">
          {counts.skipped_no_slot} {t("bt_no_slot")}
        </span>
      )}
      {counts.skipped_no_capital > 0 && (
        <span className="rounded-full bg-red-900/40 border border-red-700/50 px-2.5 py-0.5 text-red-400">
          {counts.skipped_no_capital} {t("bt_no_capital")}
        </span>
      )}
    </div>
  );
}

// ── Grouped trade table ───────────────────────────────────────────────────────

interface SymbolStats {
  symbol: string;
  trades: TradeEntry[];
  nTrades: number;
  nWins: number;
  totalPnl: number;
  avgPnl: number;
  bestPnl: number;
  worstPnl: number;
}

function buildGrouped(trades: TradeEntry[]): SymbolStats[] {
  const map: Record<string, TradeEntry[]> = {};
  for (const t of trades) {
    const key = t.underlying_symbol ?? t.symbol;
    if (!map[key]) map[key] = [];
    map[key].push(t);
  }
  return Object.entries(map)
    .map(([symbol, ts]) => {
      const pnls = ts.map((t) => t.pnl);
      const totalPnl = pnls.reduce((a, b) => a + b, 0);
      return {
        symbol,
        trades: ts,
        nTrades: ts.length,
        nWins: ts.filter((t) => t.pnl >= 0).length,
        totalPnl,
        avgPnl: totalPnl / ts.length,
        bestPnl: Math.max(...pnls),
        worstPnl: Math.min(...pnls),
      };
    })
    .sort((a, b) => b.totalPnl - a.totalPnl);
}

function GroupedTradeTable({
  stats,
  selectedSymbol,
  onSelect,
}: {
  stats: SymbolStats[];
  selectedSymbol: string | null;
  onSelect: (sym: string) => void;
}) {
  const { t } = useLang();
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl overflow-x-auto">
      <div className="px-4 py-2.5 border-b border-slate-700 text-[10px] font-bold uppercase tracking-widest text-slate-400">
        {t("bt_results_by_symbol")}
      </div>
      <table className="w-full text-left min-w-[640px]">
        <thead>
          <tr className="border-b border-slate-800 text-[10px] text-slate-500 uppercase font-medium">
            <th className="px-4 py-2">{t("col_symbol")}</th>
            <th className="px-4 py-2 text-right">{t("col_n_trades")}</th>
            <th className="px-4 py-2 text-right">{t("col_win_pct")}</th>
            <th className="px-4 py-2 text-right">{t("col_total_pnl")}</th>
            <th className="px-4 py-2 text-right">{t("col_avg_trade")}</th>
            <th className="px-4 py-2 text-right">{t("col_best")}</th>
            <th className="px-4 py-2 text-right">{t("col_worst")}</th>
          </tr>
        </thead>
        <tbody>
          {stats.map((s) => {
            const winPct = (s.nWins / s.nTrades) * 100;
            const isSelected = selectedSymbol === s.symbol;
            return (
              <tr
                key={s.symbol}
                onClick={() => onSelect(s.symbol)}
                className={`border-b border-slate-800 cursor-pointer transition-colors group ${
                  isSelected ? "bg-slate-800/80" : "hover:bg-slate-800/40"
                }`}
              >
                <td className="px-4 py-3">
                  <span
                    className={`text-sm font-semibold transition-colors ${
                      isSelected ? "text-cyan-300" : "text-slate-100 group-hover:text-cyan-300"
                    }`}
                  >
                    {s.symbol}
                  </span>
                </td>
                <td className="px-4 py-3 text-right text-sm text-slate-300 font-mono">
                  {s.nTrades}
                </td>
                <td
                  className={`px-4 py-3 text-right text-sm font-mono ${
                    winPct >= 50 ? "text-emerald-400" : "text-red-400"
                  }`}
                >
                  {winPct.toFixed(0)}%
                </td>
                <td
                  className={`px-4 py-3 text-right text-sm font-mono font-semibold ${
                    s.totalPnl >= 0 ? "text-emerald-400" : "text-red-400"
                  }`}
                >
                  {fmtMoney(s.totalPnl)}
                </td>
                <td
                  className={`px-4 py-3 text-right text-sm font-mono ${
                    s.avgPnl >= 0 ? "text-emerald-400/80" : "text-red-400/80"
                  }`}
                >
                  {fmtMoney(s.avgPnl)}
                </td>
                <td className="px-4 py-3 text-right text-sm font-mono text-emerald-400/70">
                  {fmtMoney(s.bestPnl)}
                </td>
                <td className="px-4 py-3 text-right text-sm font-mono text-red-400/70">
                  {fmtMoney(s.worstPnl)}
                </td>
              </tr>
            );
          })}
        </tbody>
        {stats.length > 0 &&
          (() => {
            const grandTotal = stats.reduce((s, r) => s + r.totalPnl, 0);
            const totalTrades = stats.reduce((s, r) => s + r.nTrades, 0);
            const totalWins = stats.reduce((s, r) => s + r.nWins, 0);
            return (
              <tfoot>
                <tr className="border-t border-slate-700 text-[10px] text-slate-500 uppercase font-semibold bg-slate-900/60">
                  <td className="px-4 py-2">{t("total")}</td>
                  <td className="px-4 py-2 text-right">{totalTrades}</td>
                  <td className="px-4 py-2 text-right">
                    {((totalWins / totalTrades) * 100).toFixed(0)}%
                  </td>
                  <td
                    className={`px-4 py-2 text-right font-mono ${
                      grandTotal >= 0 ? "text-emerald-400" : "text-red-400"
                    }`}
                  >
                    {fmtMoney(grandTotal)}
                  </td>
                  <td colSpan={3} />
                </tr>
              </tfoot>
            );
          })()}
      </table>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function Backtest() {
  const { t } = useLang();

  // Universe & period
  const [universe, setUniverse] = useState("wl:Watchlist");
  const { data: watchlists } = useQuery({ queryKey: ["watchlists"], queryFn: fetchWatchlists, retry: false });
  const [start, setStart] = useState(fiveYearsAgo);
  const [end, setEnd] = useState(today);

  // Capital
  const [initialFund, setInitialFund] = useState(100_000);

  // Platform fees
  const [feePerShare, setFeePerShare] = useState(0.005);
  const [feeMin, setFeeMin] = useState(1.0);
  const [feeMaxPct, setFeeMaxPct] = useState(1.0); // displayed as %, sent as /100

  // Position sizing
  const [positionSizePct, setPositionSizePct] = useState(8); // displayed as %, sent as /100
  const [positionSizeMin, setPositionSizeMin] = useState(2000);
  const [perNameCapPct, setPerNameCapPct] = useState(30); // displayed as %, sent as /100
  const [maxConcurrent, setMaxConcurrent] = useState(15);

  // Risk & selection
  const [atrStopMultiple, setAtrStopMultiple] = useState(1.5);
  const [topN, setTopN] = useState(10);
  const [benchmarkSymbol, setBenchmarkSymbol] = useState("QQQ");

  // Run state
  const [jobId, setJobId] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [polling, setPolling] = useState(false);
  const [progress, setProgress] = useState<ProgressInfo | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const groupedStats = useMemo(
    () => (result?.trades ? buildGrouped(result.trades) : []),
    [result?.trades]
  );

  const selectedTrades = useMemo(() => {
    if (!selectedSymbol || !result?.trades) return [];
    return result.trades.filter(
      (tr) => (tr.underlying_symbol ?? tr.symbol) === selectedSymbol
    );
  }, [selectedSymbol, result?.trades]);

  async function handleRun() {
    setSubmitError(null);
    setResult(null);
    setProgress(null);
    setSelectedSymbol(null);
    setPolling(true);

    try {
      const job = await postBacktest({
        universe,
        start,
        end,
        initial_fund: initialFund,
        fee_per_share: feePerShare,
        fee_min: feeMin,
        fee_max_pct_of_trade: feeMaxPct / 100,
        position_size_pct: positionSizePct / 100,
        position_size_min: positionSizeMin,
        per_name_cap_pct: perNameCapPct / 100,
        max_concurrent_positions: maxConcurrent,
        atr_stop_multiple: atrStopMultiple,
        top_n: topN,
        benchmark_symbol: benchmarkSymbol,
      });
      setJobId(job.job_id);
      pollRef.current = setInterval(async () => {
        try {
          const r = await fetchBacktest(job.job_id);
          if (r.n_total !== undefined && r.n_done !== undefined && r.started_at) {
            setProgress({
              nDone: r.n_done,
              nTotal: r.n_total,
              phase: r.phase ?? "",
              startedAt: r.started_at,
            });
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
      }, 2000);
    } catch (e) {
      setPolling(false);
      setSubmitError((e as Error).message);
    }
  }

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const displayMetrics = result?.strategy_metrics ?? result?.metrics;
  const bkSymbol = result?.params?.benchmark_symbol ?? benchmarkSymbol;

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-100">{t("backtest_title")}</h1>
        <p className="text-sm text-slate-500 mt-1">{t("backtest_desc")}</p>
      </div>

      {/* ── Parameters form ── */}
      <div className="bg-slate-900 rounded-xl border border-slate-700 p-5 space-y-5">
        <h2 className="text-sm font-semibold text-slate-200">{t("bt_params")}</h2>

        {/* Universe & Period */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-slate-400 mb-1">{t("universe_label")}</label>
            <select
              value={universe}
              onChange={(e) => setUniverse(e.target.value)}
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500"
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
          </div>

          <div>
            <label className="block text-xs text-slate-400 mb-1">{t("bt_initial_fund")}</label>
            <input
              type="text"
              inputMode="numeric"
              value={initialFund.toLocaleString("en-US")}
              onChange={(e) => {
                const raw = e.target.value.replace(/[^0-9]/g, "");
                setInitialFund(raw ? parseInt(raw, 10) : 0);
              }}
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 font-mono focus:outline-none focus:border-cyan-500"
            />
          </div>

          <div>
            <label className="block text-xs text-slate-400 mb-1">{t("bt_start_date")}</label>
            <input
              type="date"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500"
            />
          </div>

          <div>
            <label className="block text-xs text-slate-400 mb-1">{t("bt_end_date")}</label>
            <input
              type="date"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500"
            />
          </div>
        </div>

        {/* Platform Fees */}
        <div className="border-t border-slate-800 pt-4">
          <SectionLabel>{t("bt_platform_fees")}</SectionLabel>
          <div className="grid grid-cols-3 gap-4">
            <NumInput
              label={t("bt_fee_per_share")}
              value={feePerShare}
              onChange={setFeePerShare}
              step={0.001}
            />
            <NumInput
              label={t("bt_fee_min")}
              value={feeMin}
              onChange={setFeeMin}
              step={0.5}
            />
            <NumInput
              label={t("bt_fee_max_pct")}
              value={feeMaxPct}
              onChange={setFeeMaxPct}
              step={0.1}
              suffix="%"
            />
          </div>
        </div>

        {/* Position Sizing */}
        <div className="border-t border-slate-800 pt-4">
          <SectionLabel>{t("bt_position_sizing")}</SectionLabel>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <NumInput
              label={t("bt_size_pct")}
              value={positionSizePct}
              onChange={setPositionSizePct}
              step={1}
              suffix="%"
            />
            <NumInput
              label={t("bt_min_position")}
              value={positionSizeMin}
              onChange={setPositionSizeMin}
              step={500}
            />
            <NumInput
              label={t("bt_per_name_cap")}
              value={perNameCapPct}
              onChange={setPerNameCapPct}
              step={5}
              suffix="%"
            />
            <NumInput
              label={t("bt_max_concurrent")}
              value={maxConcurrent}
              onChange={setMaxConcurrent}
              step={1}
              min={1}
            />
          </div>
        </div>

        {/* Risk & Selection */}
        <div className="border-t border-slate-800 pt-4">
          <SectionLabel>{t("bt_risk_selection")}</SectionLabel>
          <div className="grid grid-cols-3 gap-4">
            <NumInput
              label={t("bt_atr_stop")}
              value={atrStopMultiple}
              onChange={setAtrStopMultiple}
              step={0.1}
            />
            <NumInput
              label={t("bt_top_n")}
              value={topN}
              onChange={setTopN}
              step={1}
              min={1}
            />
            <div>
              <label className="block text-xs text-slate-400 mb-1">{t("bt_benchmark")}</label>
              <input
                type="text"
                value={benchmarkSymbol}
                onChange={(e) => setBenchmarkSymbol(e.target.value.toUpperCase())}
                className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 font-mono focus:outline-none focus:border-cyan-500"
              />
            </div>
          </div>
        </div>

        {/* Run button */}
        <div className="border-t border-slate-800 pt-4 flex items-center gap-4">
          <button
            onClick={handleRun}
            disabled={polling}
            className={`px-6 py-2 rounded-lg text-sm font-semibold transition-all ${
              polling
                ? "bg-amber-500/20 text-amber-300 border border-amber-500/40 cursor-wait"
                : "bg-cyan-600 text-white hover:bg-cyan-500"
            }`}
          >
            {polling ? t("bt_running") : t("bt_run")}
          </button>
          {jobId && polling && (
            <span className="text-xs text-slate-500 font-mono">Job {jobId}</span>
          )}
        </div>

        {submitError && (
          <div className="mt-3 text-sm text-red-400 bg-red-950/40 border border-red-800 rounded-lg px-4 py-2">
            {submitError}
          </div>
        )}
      </div>

      {/* ── Progress ── */}
      {polling && (
        <div className="bg-slate-900 border border-slate-700 rounded-xl px-5 py-4 space-y-3">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
            {t("bt_running_label")}
          </p>
          {progress ? (
            <ProgressBar {...progress} />
          ) : (
            <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div className="h-full w-1/3 bg-cyan-600 rounded-full animate-pulse" />
            </div>
          )}
          {jobId && <p className="text-[10px] text-slate-600 font-mono">job {jobId}</p>}
        </div>
      )}

      {/* ── Error result ── */}
      {result && result.status === "error" && (
        <div className="rounded-xl border border-red-800 bg-red-950/40 px-5 py-4 text-red-300 text-sm">
          {t("bt_failed")}{result.error}
        </div>
      )}

      {/* ── Success results ── */}
      {result && result.status === "done" && displayMetrics && (
        <div className="space-y-6">
          {/* Survivorship warning */}
          {result.survivorship_note && (
            <div className="rounded-xl border border-amber-600/50 bg-amber-950/30 px-4 py-3 text-xs text-amber-400">
              {result.survivorship_note}
            </div>
          )}

          {/* Params summary */}
          {result.params && (
            <p className="text-xs text-slate-500">
              {result.params.start} → {result.params.end} ·{" "}
              {result.params.n_symbols_loaded} symbols · initial{" "}
              {(result.params.initial_fund ?? result.params.initial_account ?? 0).toLocaleString(
                "en-US",
                { style: "currency", currency: "USD", maximumFractionDigits: 0 }
              )}{" "}
              · {result.duration_seconds?.toFixed(1)}s
            </p>
          )}

          {/* Strategy metrics */}
          <div>
            <h2 className="text-sm font-semibold text-slate-200 mb-3">{t("bt_strategy_perf")}</h2>
            <MetricsDisplay metrics={displayMetrics} />
          </div>

          {/* Benchmark metrics */}
          {result.benchmark_metrics?.final_equity !== undefined && (
            <div>
              <h2 className="text-sm font-semibold text-slate-200 mb-3">
                {bkSymbol} {t("bt_benchmark_perf")}
              </h2>
              <BenchmarkMetricsDisplay metrics={result.benchmark_metrics} />
            </div>
          )}

          {/* Constraint counts */}
          {result.constraint_counts && (
            <ConstraintChip counts={result.constraint_counts} />
          )}

          {/* Strategy vs Benchmark comparison */}
          {result.comparison?.metrics && Object.keys(result.comparison.metrics).length > 0 && (
            <div>
              <h2 className="text-sm font-semibold text-slate-200 mb-3">
                {t("bt_vs_benchmark")}
              </h2>
              <ComparisonTable comparison={result.comparison} benchmarkSymbol={bkSymbol} />
            </div>
          )}

          {/* Equity curve (with benchmark overlay) */}
          {result.equity_curve && result.equity_curve.length > 0 && (
            <div>
              <div className="flex items-center gap-4 mb-3">
                <h2 className="text-sm font-semibold text-slate-200">{t("bt_equity_curve")}</h2>
                <div className="flex items-center gap-3 text-[10px] text-slate-500">
                  <span className="flex items-center gap-1">
                    <span className="inline-block w-6 h-0.5 bg-cyan-400" /> {t("bt_strategy")}
                  </span>
                  {result.benchmark_equity_curve && (
                    <span className="flex items-center gap-1">
                      <span className="inline-block w-6 h-0.5 bg-slate-500 border-dashed" />{" "}
                      {bkSymbol} {t("bt_buy_hold")}
                    </span>
                  )}
                </div>
              </div>
              <div className="bg-slate-900 rounded-xl border border-slate-700 overflow-hidden">
                <EquityCurveChart
                  data={result.equity_curve}
                  benchmarkData={result.benchmark_equity_curve}
                  benchmarkLabel={bkSymbol}
                  strategyLabel={t("bt_strategy")}
                />
              </div>
            </div>
          )}

          {/* Trade results — grouped by symbol */}
          {result.trades && result.trades.length > 0 && (
            <div className="space-y-4">
              <h2 className="text-sm font-semibold text-slate-200">
                {t("bt_trade_results")} — {groupedStats.length} symbol
                {groupedStats.length !== 1 ? "s" : ""}
              </h2>

              {selectedSymbol && (
                <TradeChart
                  key={selectedSymbol}
                  symbol={selectedSymbol}
                  trades={selectedTrades}
                  onClose={() => setSelectedSymbol(null)}
                />
              )}

              <GroupedTradeTable
                stats={groupedStats}
                selectedSymbol={selectedSymbol}
                onSelect={(sym) => setSelectedSymbol((prev) => (prev === sym ? null : sym))}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
