import { useState, useRef, useEffect, useMemo } from "react";
import { postBacktest, fetchBacktest } from "../lib/api";
import { ProgressBar, type ProgressInfo } from "../components/ProgressBar";
import { TradeChart } from "../components/TradeChart";
import { fmtMoney, fmtPct } from "../lib/format";
import type { BacktestResult, BacktestMetrics, TradeEntry } from "../lib/types";
import { createChart, ColorType, CrosshairMode } from "lightweight-charts";

const today = new Date().toISOString().slice(0, 10);
const fiveYearsAgo = new Date(Date.now() - 5 * 365 * 24 * 60 * 60 * 1000)
  .toISOString()
  .slice(0, 10);

// ── Helpers ──────────────────────────────────────────────────────────────────

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-slate-800 rounded-xl px-4 py-3">
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className="text-lg font-bold font-mono text-slate-100">{value}</p>
    </div>
  );
}

function EquityCurveChart({ data }: { data: Array<{ date: string; equity: number }> }) {
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

    const series = chart.addLineSeries({
      color: "#22d3ee",
      lineWidth: 2,
      priceLineVisible: false,
    });
    series.setData(data.map((d) => ({ time: d.date as string, value: d.equity })));
    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => {
      if (ref.current) chart.applyOptions({ width: ref.current.clientWidth });
    });
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.remove(); };
  }, [data]);

  return <div ref={ref} />;
}

function MetricsDisplay({ metrics }: { metrics: BacktestMetrics }) {
  const pct = (n: number) => `${n.toFixed(1)}%`;

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
      <MetricCard label="Total Return"   value={pct(metrics.total_return_pct)} />
      <MetricCard label="CAGR"           value={pct(metrics.cagr)} />
      <MetricCard label="Sharpe Ratio"   value={metrics.sharpe.toFixed(2)} />
      <MetricCard label="Max Drawdown"   value={pct(metrics.max_drawdown_pct)} />
      <MetricCard label="Hit Rate"       value={pct(metrics.hit_rate * 100)} />
      <MetricCard label="Profit Factor"  value={metrics.profit_factor.toFixed(2)} />
      <MetricCard label="Avg Win"        value={fmtMoney(metrics.avg_win)} />
      <MetricCard label="Avg Loss"       value={fmtMoney(metrics.avg_loss)} />
      <MetricCard label="# Trades"       value={String(metrics.n_trades)} />
      <MetricCard label="Exposure"       value={pct(metrics.exposure_pct)} />
      <MetricCard label="Final Equity"   value={fmtMoney(metrics.final_equity)} />
    </div>
  );
}

// ── Grouped trade summary ─────────────────────────────────────────────────────

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
    // For short trades underlying_symbol is the stock; for longs symbol IS the stock.
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
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl overflow-x-auto">
      <div className="px-4 py-2.5 border-b border-slate-700 text-[10px] font-bold uppercase tracking-widest text-slate-400">
        Results by Symbol — click a row to view chart + trades
      </div>
      <table className="w-full text-left min-w-[640px]">
        <thead>
          <tr className="border-b border-slate-800 text-[10px] text-slate-500 uppercase font-medium">
            <th className="px-4 py-2">Symbol</th>
            <th className="px-4 py-2 text-right"># Trades</th>
            <th className="px-4 py-2 text-right">Win %</th>
            <th className="px-4 py-2 text-right">Total P&L</th>
            <th className="px-4 py-2 text-right">Avg / Trade</th>
            <th className="px-4 py-2 text-right">Best</th>
            <th className="px-4 py-2 text-right">Worst</th>
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
                  isSelected
                    ? "bg-slate-800/80"
                    : "hover:bg-slate-800/40"
                }`}
              >
                <td className="px-4 py-3">
                  <span className={`text-sm font-semibold transition-colors ${
                    isSelected ? "text-cyan-300" : "text-slate-100 group-hover:text-cyan-300"
                  }`}>
                    {s.symbol}
                  </span>
                </td>
                <td className="px-4 py-3 text-right text-sm text-slate-300 font-mono">
                  {s.nTrades}
                </td>
                <td className={`px-4 py-3 text-right text-sm font-mono ${
                  winPct >= 50 ? "text-emerald-400" : "text-red-400"
                }`}>
                  {winPct.toFixed(0)}%
                </td>
                <td className={`px-4 py-3 text-right text-sm font-mono font-semibold ${
                  s.totalPnl >= 0 ? "text-emerald-400" : "text-red-400"
                }`}>
                  {fmtMoney(s.totalPnl)}
                </td>
                <td className={`px-4 py-3 text-right text-sm font-mono ${
                  s.avgPnl >= 0 ? "text-emerald-400/80" : "text-red-400/80"
                }`}>
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
        {/* Totals footer */}
        {stats.length > 0 && (() => {
          const grandTotal = stats.reduce((s, r) => s + r.totalPnl, 0);
          const totalTrades = stats.reduce((s, r) => s + r.nTrades, 0);
          const totalWins = stats.reduce((s, r) => s + r.nWins, 0);
          return (
            <tfoot>
              <tr className="border-t border-slate-700 text-[10px] text-slate-500 uppercase font-semibold bg-slate-900/60">
                <td className="px-4 py-2">Total</td>
                <td className="px-4 py-2 text-right">{totalTrades}</td>
                <td className="px-4 py-2 text-right">
                  {((totalWins / totalTrades) * 100).toFixed(0)}%
                </td>
                <td className={`px-4 py-2 text-right font-mono ${grandTotal >= 0 ? "text-emerald-400" : "text-red-400"}`}>
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
  const [universe, setUniverse] = useState("watchlist");
  const [start, setStart] = useState(fiveYearsAgo);
  const [end, setEnd] = useState(today);
  const [initialAccount, setInitialAccount] = useState(100_000);

  const [jobId, setJobId] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [polling, setPolling] = useState(false);
  const [progress, setProgress] = useState<ProgressInfo | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Group trades by underlying symbol once the result arrives
  const groupedStats = useMemo(
    () => (result?.trades ? buildGrouped(result.trades) : []),
    [result?.trades]
  );

  // Trades for the selected symbol (for TradeChart)
  const selectedTrades = useMemo(() => {
    if (!selectedSymbol || !result?.trades) return [];
    return result.trades.filter(
      (t) => (t.underlying_symbol ?? t.symbol) === selectedSymbol
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
        initial_account: initialAccount,
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
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  return (
    <div className="p-6 space-y-6 max-w-5xl">
      <div>
        <h1 className="text-xl font-bold text-slate-100">Backtest</h1>
        <p className="text-sm text-slate-500 mt-1">
          Run the strategy over historical data with current config weights.
        </p>
      </div>

      {/* ── Parameters form ── */}
      <div className="bg-slate-900 rounded-xl border border-slate-700 p-5">
        <h2 className="text-sm font-semibold text-slate-200 mb-4">Parameters</h2>
        <div className="grid grid-cols-2 gap-4">
          {/* Universe */}
          <div>
            <label className="block text-xs text-slate-400 mb-1">Universe</label>
            <select
              value={universe}
              onChange={(e) => setUniverse(e.target.value)}
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500"
            >
              <option value="watchlist">Watchlist</option>
              <option value="sp500">S&amp;P 500</option>
              <option value="nasdaq100">NASDAQ-100</option>
              <option value="midcap">S&amp;P MidCap 400</option>
              <option value="smallcap">S&amp;P SmallCap 600</option>
              <option value="combined">Full Universe (Watchlist + S&amp;P 500/400/600)</option>
            </select>
          </div>

          {/* Initial account — text input so thousands commas render */}
          <div>
            <label className="block text-xs text-slate-400 mb-1">Initial Account ($)</label>
            <input
              type="text"
              inputMode="numeric"
              value={initialAccount.toLocaleString("en-US")}
              onChange={(e) => {
                const raw = e.target.value.replace(/[^0-9]/g, "");
                setInitialAccount(raw ? parseInt(raw, 10) : 0);
              }}
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 font-mono focus:outline-none focus:border-cyan-500"
            />
          </div>

          {/* Start date */}
          <div>
            <label className="block text-xs text-slate-400 mb-1">Start Date</label>
            <input
              type="date"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500"
            />
          </div>

          {/* End date */}
          <div>
            <label className="block text-xs text-slate-400 mb-1">End Date</label>
            <input
              type="date"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500"
            />
          </div>
        </div>

        <div className="mt-4 flex items-center gap-4">
          <button
            onClick={handleRun}
            disabled={polling}
            className={`px-6 py-2 rounded-lg text-sm font-semibold transition-all ${
              polling
                ? "bg-amber-500/20 text-amber-300 border border-amber-500/40 cursor-wait"
                : "bg-cyan-600 text-white hover:bg-cyan-500"
            }`}
          >
            {polling ? "Running backtest…" : "Run Backtest"}
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
            Backtest Running
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
          Backtest failed: {result.error}
        </div>
      )}

      {/* ── Success results ── */}
      {result && result.status === "done" && result.metrics && (
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
              {fmtMoney(result.params.initial_account)} ·{" "}
              {result.duration_seconds?.toFixed(1)}s
            </p>
          )}

          {/* Metrics */}
          <div>
            <h2 className="text-sm font-semibold text-slate-200 mb-3">Performance Metrics</h2>
            <MetricsDisplay metrics={result.metrics} />
          </div>

          {/* Equity curve */}
          {result.equity_curve && result.equity_curve.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold text-slate-200 mb-3">Equity Curve</h2>
              <div className="bg-slate-900 rounded-xl border border-slate-700 overflow-hidden">
                <EquityCurveChart data={result.equity_curve} />
              </div>
            </div>
          )}

          {/* Trade results — grouped by symbol */}
          {result.trades && result.trades.length > 0 && (
            <div className="space-y-4">
              <h2 className="text-sm font-semibold text-slate-200">
                Trade Results — {groupedStats.length} symbol{groupedStats.length !== 1 ? "s" : ""}
              </h2>

              {/* Symbol detail view (shown when a row is selected) */}
              {selectedSymbol && (
                <TradeChart
                  key={selectedSymbol}
                  symbol={selectedSymbol}
                  trades={selectedTrades}
                  onClose={() => setSelectedSymbol(null)}
                />
              )}

              {/* Grouped summary table — always visible, selected row highlighted */}
              <GroupedTradeTable
                stats={groupedStats}
                selectedSymbol={selectedSymbol}
                onSelect={(sym) =>
                  setSelectedSymbol((prev) => (prev === sym ? null : sym))
                }
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
