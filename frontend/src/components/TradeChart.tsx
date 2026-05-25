/**
 * TradeChart — candlestick chart for one symbol with backtest trade markers.
 *
 * Entry points: green ▲ below the bar
 * Exit points : red   ▼ above the bar
 *
 * Click any marked bar → detail panel shows P&L, cumulative P&L,
 * and the strategy score for that date (fetched lazily from the API).
 */
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createChart, ColorType, CrosshairMode, type IChartApi } from "lightweight-charts";
import { fetchBars, fetchSignalAudit } from "../lib/api";
import { fmtMoney, fmtPct } from "../lib/format";
import type { TradeEntry } from "../lib/types";

const BG = "#0f172a";
const GRID = "#1e293b";
const TEXT = "#94a3b8";
const BORDER = "#334155";

interface ClickedPoint {
  trade: TradeEntry;
  type: "entry" | "exit";
  /** Running P&L for this symbol across all trades up to and including this one. */
  cumulativePnl: number;
}

interface Props {
  /** Underlying ticker (used for bar fetch + signal score fetch). */
  symbol: string;
  /** All trades for this symbol, chronological order. */
  trades: TradeEntry[];
  onClose: () => void;
}

export function TradeChart({ symbol, trades, onClose }: Props) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartApi = useRef<IChartApi | null>(null);
  const [clicked, setClicked] = useState<ClickedPoint | null>(null);

  // ── Data fetching ────────────────────────────────────────────────────────
  const { data: barsData, isLoading: barsLoading } = useQuery({
    queryKey: ["bars", symbol, "5y"],
    queryFn: () => fetchBars(symbol, "5y"),
    retry: false,
  });

  // Score is fetched lazily when a marker is clicked.
  const clickDate =
    clicked?.type === "entry" ? clicked.trade.entry_date : clicked?.trade.exit_date;

  const { data: auditData, isLoading: auditLoading } = useQuery({
    queryKey: ["signalAudit", symbol, clickDate],
    queryFn: () => fetchSignalAudit(symbol, clickDate!),
    enabled: !!clicked,
    retry: false,
  });

  // ── Cumulative P&L per trade index ───────────────────────────────────────
  const cumulativePnls = trades.reduce<number[]>((acc, t) => {
    acc.push((acc[acc.length - 1] ?? 0) + t.pnl);
    return acc;
  }, []);
  const totalPnl = cumulativePnls[cumulativePnls.length - 1] ?? 0;

  // ── Chart + markers ──────────────────────────────────────────────────────
  useEffect(() => {
    if (!chartRef.current || !barsData?.bars.length) return;

    if (chartApi.current) {
      chartApi.current.remove();
      chartApi.current = null;
    }

    const chart = createChart(chartRef.current, {
      layout: { background: { type: ColorType.Solid, color: BG }, textColor: TEXT },
      grid: { vertLines: { color: GRID }, horzLines: { color: GRID } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: BORDER },
      timeScale: { borderColor: BORDER, timeVisible: true },
      width: chartRef.current.clientWidth,
      height: 380,
    });
    chartApi.current = chart;

    // Candlestick
    const candle = chart.addCandlestickSeries({
      upColor: "#22c55e", downColor: "#ef4444",
      borderUpColor: "#22c55e", borderDownColor: "#ef4444",
      wickUpColor: "#22c55e", wickDownColor: "#ef4444",
    });
    candle.setData(barsData.bars.map((b) => ({ ...b, time: b.time as string })));

    // Volume overlay — bottom 20 %
    const volSeries = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    volSeries.setData(
      barsData.bars.map((b) => ({
        time: b.time as string,
        value: b.volume,
        color: b.close >= b.open ? "#22c55e55" : "#ef444455",
      }))
    );

    // Trade markers — sort by time (required by lightweight-charts)
    const markers: Array<{
      time: string;
      position: "aboveBar" | "belowBar";
      color: string;
      shape: "arrowUp" | "arrowDown";
      text: string;
      size: number;
    }> = [];

    for (const t of trades) {
      markers.push({
        time: t.entry_date,
        position: "belowBar",
        color: "#22c55e",
        shape: "arrowUp",
        text: `Buy $${t.entry_price.toFixed(2)}`,
        size: 1,
      });
      markers.push({
        time: t.exit_date,
        position: "aboveBar",
        color: "#ef4444",
        shape: "arrowDown",
        text: `Sell $${t.exit_price.toFixed(2)}`,
        size: 1,
      });
    }
    markers.sort((a, b) => a.time.localeCompare(b.time));
    candle.setMarkers(markers as never);

    // Fit visible range to include all trades + a bit of context
    chart.timeScale().fitContent();

    // Click handler — find nearest marked trade and surface details
    chart.subscribeClick((param) => {
      if (!param.time) { setClicked(null); return; }
      const t = param.time as string;

      // Prefer exit (shows P&L) over entry when same bar
      const exitIdx = trades.findIndex((tr) => tr.exit_date === t);
      if (exitIdx >= 0) {
        setClicked({ trade: trades[exitIdx], type: "exit", cumulativePnl: cumulativePnls[exitIdx] });
        return;
      }
      const entryIdx = trades.findIndex((tr) => tr.entry_date === t);
      if (entryIdx >= 0) {
        setClicked({ trade: trades[entryIdx], type: "entry", cumulativePnl: cumulativePnls[entryIdx] });
        return;
      }
      setClicked(null);
    });

    // Resize
    const ro = new ResizeObserver(() => {
      chartApi.current?.applyOptions({ width: chartRef.current?.clientWidth ?? 0 });
    });
    ro.observe(chartRef.current);

    return () => {
      ro.disconnect();
      chartApi.current?.remove();
      chartApi.current = null;
    };
  }, [barsData, trades]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl overflow-hidden">

      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700">
        <div className="flex items-center gap-3">
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-100 text-sm transition-colors"
          >
            ← All symbols
          </button>
          <span className="text-slate-700">|</span>
          <span className="text-lg font-bold text-slate-100">{symbol}</span>
          <span className="text-xs text-slate-500">{trades.length} trade{trades.length !== 1 ? "s" : ""}</span>
        </div>
        <div className="text-sm font-semibold font-mono">
          <span className="text-slate-500 text-xs font-normal mr-1">Total P&L</span>
          <span className={totalPnl >= 0 ? "text-emerald-400" : "text-red-400"}>
            {fmtMoney(totalPnl)}
          </span>
        </div>
      </div>

      {/* Chart */}
      {barsLoading ? (
        <div className="h-96 flex items-center justify-center text-slate-500 text-sm">
          Loading chart data…
        </div>
      ) : (
        <>
          <div className="px-4 py-1.5 text-[10px] text-slate-600 border-b border-slate-800">
            Click a <span className="text-emerald-400 font-semibold">▲ buy</span> or{" "}
            <span className="text-red-400 font-semibold">▼ sell</span> marker to view trade details
          </div>
          <div ref={chartRef} />
        </>
      )}

      {/* Clicked-marker detail panel */}
      {clicked && (
        <div className="border-t border-slate-700 px-4 py-4 space-y-4">
          <div className="flex items-start justify-between">
            <div className="space-y-3 flex-1">
              <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">
                {clicked.type === "entry" ? "🟢 Buy point" : "🔴 Sell point"}
              </p>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                {/* Date */}
                <div>
                  <p className="text-[10px] text-slate-500 uppercase mb-0.5">Date</p>
                  <p className="text-sm font-mono text-slate-200">
                    {clicked.type === "entry" ? clicked.trade.entry_date : clicked.trade.exit_date}
                  </p>
                </div>

                {/* Price */}
                <div>
                  <p className="text-[10px] text-slate-500 uppercase mb-0.5">Price</p>
                  <p className="text-sm font-mono text-slate-200">
                    ${(clicked.type === "entry"
                      ? clicked.trade.entry_price
                      : clicked.trade.exit_price
                    ).toFixed(2)}
                  </p>
                </div>

                {/* Entry-specific: shares + stop */}
                {clicked.type === "entry" && (
                  <>
                    <div>
                      <p className="text-[10px] text-slate-500 uppercase mb-0.5">Shares</p>
                      <p className="text-sm font-mono text-slate-200">
                        {clicked.trade.shares.toFixed(2)}
                      </p>
                    </div>
                    <div>
                      <p className="text-[10px] text-slate-500 uppercase mb-0.5">Initial stop</p>
                      <p className="text-sm font-mono text-slate-200">
                        ${clicked.trade.initial_stop.toFixed(2)}
                      </p>
                    </div>
                  </>
                )}

                {/* Exit-specific: trade P&L + cumulative */}
                {clicked.type === "exit" && (
                  <>
                    <div>
                      <p className="text-[10px] text-slate-500 uppercase mb-0.5">Trade P&L</p>
                      <p className={`text-sm font-mono font-semibold ${clicked.trade.pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {fmtMoney(clicked.trade.pnl)}{" "}
                        <span className="text-xs font-normal">
                          ({fmtPct(clicked.trade.pnl_pct)})
                        </span>
                      </p>
                    </div>
                    <div>
                      <p className="text-[10px] text-slate-500 uppercase mb-0.5">Cumulative P&L</p>
                      <p className={`text-sm font-mono font-semibold ${clicked.cumulativePnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {fmtMoney(clicked.cumulativePnl)}
                      </p>
                    </div>
                    <div>
                      <p className="text-[10px] text-slate-500 uppercase mb-0.5">Exit reason</p>
                      <p className="text-sm text-slate-300 capitalize">
                        {clicked.trade.exit_reason.replace(/_/g, " ")}
                      </p>
                    </div>
                  </>
                )}
              </div>
            </div>
            <button
              onClick={() => setClicked(null)}
              className="text-slate-600 hover:text-slate-300 text-xl leading-none ml-4 mt-0.5"
            >
              ×
            </button>
          </div>

          {/* Strategy score */}
          {auditLoading && (
            <p className="text-xs text-slate-600 animate-pulse">Loading strategy score…</p>
          )}
          {auditData && (
            <div className="pt-3 border-t border-slate-800 space-y-2">
              <p className="text-[10px] text-slate-500 uppercase tracking-wide">
                Strategy score on {clickDate}
              </p>
              <div className="flex flex-wrap items-center gap-6">
                <div>
                  <p className="text-[10px] text-slate-500 mb-0.5">Composite</p>
                  <p className={`text-xl font-bold font-mono ${auditData.composite >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {auditData.composite >= 0 ? "+" : ""}{auditData.composite.toFixed(1)}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] text-slate-500 mb-0.5">Signal</p>
                  <p className="text-sm text-slate-200">{auditData.signal}</p>
                </div>
                <div className="flex gap-3 flex-wrap">
                  {Object.entries(auditData.components).map(([key, val]) => (
                    <div key={key} className="text-center">
                      <p className="text-[9px] text-slate-600 uppercase mb-0.5">{key}</p>
                      <p className={`text-xs font-mono ${val.sub >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {val.sub.toFixed(0)}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Per-symbol trade list */}
      <div className="border-t border-slate-800 overflow-x-auto">
        <table className="w-full text-left min-w-[640px]">
          <thead>
            <tr className="border-b border-slate-800 text-[10px] text-slate-500 uppercase font-medium">
              <th className="px-4 py-2">#</th>
              <th className="px-4 py-2">Side</th>
              <th className="px-4 py-2">Entry</th>
              <th className="px-4 py-2 text-right">Entry $</th>
              <th className="px-4 py-2">Exit</th>
              <th className="px-4 py-2 text-right">Exit $</th>
              <th className="px-4 py-2 text-right">P&L</th>
              <th className="px-4 py-2 text-right">P&L %</th>
              <th className="px-4 py-2 text-right">Cumul.</th>
              <th className="px-4 py-2">Reason</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t, i) => (
              <tr
                key={i}
                onClick={() => setClicked({ trade: t, type: "exit", cumulativePnl: cumulativePnls[i] })}
                className={`border-b border-slate-800 cursor-pointer transition-colors hover:bg-slate-800/40 ${
                  clicked?.trade === t ? "bg-slate-800/60" : ""
                }`}
              >
                <td className="px-4 py-2 text-slate-500 text-xs">{i + 1}</td>
                <td className={`px-4 py-2 text-xs font-semibold ${t.side === "long" ? "text-emerald-400" : "text-red-400"}`}>
                  {t.side.toUpperCase()}
                </td>
                <td className="px-4 py-2 text-slate-400 text-xs">{t.entry_date}</td>
                <td className="px-4 py-2 text-right font-mono text-slate-300 text-xs">
                  ${t.entry_price.toFixed(2)}
                </td>
                <td className="px-4 py-2 text-slate-400 text-xs">{t.exit_date}</td>
                <td className="px-4 py-2 text-right font-mono text-slate-300 text-xs">
                  ${t.exit_price.toFixed(2)}
                </td>
                <td className={`px-4 py-2 text-right font-mono font-semibold text-xs ${t.pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {fmtMoney(t.pnl)}
                </td>
                <td className={`px-4 py-2 text-right font-mono text-xs ${t.pnl_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {fmtPct(t.pnl_pct)}
                </td>
                <td className={`px-4 py-2 text-right font-mono text-xs ${cumulativePnls[i] >= 0 ? "text-emerald-400/70" : "text-red-400/70"}`}>
                  {fmtMoney(cumulativePnls[i])}
                </td>
                <td className="px-4 py-2 text-xs text-slate-500">
                  {t.exit_reason.replace(/_/g, " ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
