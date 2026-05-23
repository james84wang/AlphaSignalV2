import { useState, useRef, useEffect } from "react";
import { postBacktest, fetchBacktest } from "../lib/api";
import { LoadingState } from "../components/LoadingState";
import type { BacktestResult, BacktestMetrics, TradeEntry } from "../lib/types";
import { createChart, ColorType, CrosshairMode } from "lightweight-charts";

const today = new Date().toISOString().slice(0, 10);
const fiveYearsAgo = new Date(Date.now() - 5 * 365 * 24 * 60 * 60 * 1000)
  .toISOString()
  .slice(0, 10);

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-slate-800 rounded-xl px-4 py-3">
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className="text-lg font-bold font-mono text-slate-100">{value}</p>
    </div>
  );
}

function EquityCurveChart({
  data,
}: {
  data: Array<{ date: string; equity: number }>;
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

    const series = chart.addLineSeries({ color: "#22d3ee", lineWidth: 2, priceLineVisible: false });
    series.setData(data.map((d) => ({ time: d.date as string, value: d.equity })));
    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => {
      if (ref.current) chart.applyOptions({ width: ref.current.clientWidth });
    });
    ro.observe(ref.current);

    return () => {
      ro.disconnect();
      chart.remove();
    };
  }, [data]);

  return <div ref={ref} />;
}

function MetricsDisplay({ metrics }: { metrics: BacktestMetrics }) {
  const pct = (n: number) => `${n.toFixed(1)}%`;
  const money = (n: number) =>
    n >= 0
      ? `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
      : `-$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
      <MetricCard label="Total Return" value={pct(metrics.total_return_pct)} />
      <MetricCard label="CAGR" value={pct(metrics.cagr)} />
      <MetricCard label="Sharpe Ratio" value={metrics.sharpe.toFixed(2)} />
      <MetricCard label="Max Drawdown" value={pct(metrics.max_drawdown_pct)} />
      <MetricCard label="Hit Rate" value={pct(metrics.hit_rate * 100)} />
      <MetricCard label="Profit Factor" value={metrics.profit_factor.toFixed(2)} />
      <MetricCard label="Avg Win" value={money(metrics.avg_win)} />
      <MetricCard label="Avg Loss" value={money(metrics.avg_loss)} />
      <MetricCard label="# Trades" value={String(metrics.n_trades)} />
      <MetricCard label="Exposure" value={pct(metrics.exposure_pct)} />
      <MetricCard label="Final Equity" value={money(metrics.final_equity)} />
    </div>
  );
}

function TradeLog({ trades }: { trades: TradeEntry[] }) {
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl overflow-x-auto">
      <table className="w-full min-w-[700px] text-left text-sm">
        <thead>
          <tr className="border-b border-slate-700 text-xs text-slate-500 uppercase font-medium">
            <th className="px-4 py-2">Symbol</th>
            <th className="px-4 py-2">Side</th>
            <th className="px-4 py-2">Entry</th>
            <th className="px-4 py-2 text-right">Entry $</th>
            <th className="px-4 py-2">Exit</th>
            <th className="px-4 py-2 text-right">Exit $</th>
            <th className="px-4 py-2 text-right">P&L</th>
            <th className="px-4 py-2 text-right">P&L %</th>
            <th className="px-4 py-2">Reason</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => (
            <tr key={i} className="border-b border-slate-800 hover:bg-slate-800/50 transition-colors">
              <td className="px-4 py-2 font-semibold text-slate-200">{t.symbol}</td>
              <td className={`px-4 py-2 text-xs font-semibold ${t.side === "long" ? "text-green-400" : "text-red-400"}`}>
                {t.side.toUpperCase()}
              </td>
              <td className="px-4 py-2 text-slate-400 text-xs">{t.entry_date}</td>
              <td className="px-4 py-2 text-right font-mono text-slate-300">
                {t.entry_price.toFixed(2)}
              </td>
              <td className="px-4 py-2 text-slate-400 text-xs">{t.exit_date}</td>
              <td className="px-4 py-2 text-right font-mono text-slate-300">
                {t.exit_price.toFixed(2)}
              </td>
              <td
                className={`px-4 py-2 text-right font-mono font-semibold ${
                  t.pnl >= 0 ? "text-green-400" : "text-red-400"
                }`}
              >
                {t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(0)}
              </td>
              <td
                className={`px-4 py-2 text-right font-mono font-semibold ${
                  t.pnl_pct >= 0 ? "text-green-400" : "text-red-400"
                }`}
              >
                {t.pnl_pct >= 0 ? "+" : ""}
                {t.pnl_pct.toFixed(2)}%
              </td>
              <td className="px-4 py-2 text-xs text-slate-500">{t.exit_reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Backtest() {
  const [universe, setUniverse] = useState("watchlist");
  const [start, setStart] = useState(fiveYearsAgo);
  const [end, setEnd] = useState(today);
  const [initialAccount, setInitialAccount] = useState(100000);

  const [jobId, setJobId] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [polling, setPolling] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function handleRun() {
    setSubmitError(null);
    setResult(null);
    setPolling(true);
    try {
      const job = await postBacktest({ universe, start, end, initial_account: initialAccount });
      setJobId(job.job_id);
      pollRef.current = setInterval(async () => {
        try {
          const r = await fetchBacktest(job.job_id);
          if (r.status === "done" || r.status === "error") {
            clearInterval(pollRef.current!);
            pollRef.current = null;
            setPolling(false);
            setResult(r);
          }
        } catch (e) {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          setPolling(false);
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

  return (
    <div className="p-6 space-y-6 max-w-4xl">
      <div>
        <h1 className="text-xl font-bold text-slate-100">Backtest</h1>
        <p className="text-sm text-slate-500 mt-1">
          Run the strategy over historical data with current config weights.
        </p>
      </div>

      {/* Form */}
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
              <option value="midcap">S&amp;P MidCap 400</option>
              <option value="smallcap">S&amp;P SmallCap 600</option>
              <option value="combined">Full Universe (Watchlist + S&amp;P 500/400/600)</option>
            </select>
          </div>

          {/* Initial account */}
          <div>
            <label className="block text-xs text-slate-400 mb-1">Initial Account ($)</label>
            <input
              type="number"
              value={initialAccount}
              onChange={(e) => setInitialAccount(Number(e.target.value))}
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500"
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
            <span className="text-xs text-slate-500">Job {jobId}</span>
          )}
        </div>

        {submitError && (
          <div className="mt-3 text-sm text-red-400 bg-red-950/40 border border-red-800 rounded-lg px-4 py-2">
            {submitError}
          </div>
        )}
      </div>

      {/* Loading state while polling */}
      {polling && <LoadingState label="Running backtest — this may take a minute…" />}

      {/* Results */}
      {result && result.status === "error" && (
        <div className="rounded-xl border border-red-800 bg-red-950/40 px-5 py-4 text-red-300 text-sm">
          Backtest failed: {result.error}
        </div>
      )}

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
              {result.params.n_symbols_loaded} symbols · initial $
              {result.params.initial_account.toLocaleString()} ·{" "}
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

          {/* Trade log */}
          {result.trades && result.trades.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold text-slate-200 mb-3">
                Trade Log ({result.trades.length} trades)
              </h2>
              <TradeLog trades={result.trades} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
