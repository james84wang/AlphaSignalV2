/**
 * TradeChart — candlestick chart for one symbol with backtest trade markers.
 *
 * Bi-directional linking:
 *   • Click a chart marker → highlights the corresponding table row and zooms chart.
 *   • Click a table row   → highlights the chart markers and zooms chart to that trade.
 */
import { useEffect, useRef, useState, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { createChart, ColorType, CrosshairMode, type IChartApi } from "lightweight-charts";
import { fetchBars, fetchSignalAudit } from "../lib/api";
import { fmtMoney, fmtPct } from "../lib/format";
import type { TradeEntry } from "../lib/types";

const BG = "#0f172a";
const GRID = "#1e293b";
const TEXT = "#94a3b8";
const BORDER = "#334155";

// ── Exit reason labels ────────────────────────────────────────────────────────

const EXIT_REASON_LABELS: Record<string, string> = {
  stop: "Stop Loss",
  signal: "Signal Flip",
  end_of_data: "End of Period",
};

function fmtExitReason(reason: string): string {
  return EXIT_REASON_LABELS[reason] ?? reason.replace(/_/g, " ");
}

// ── Component ─────────────────────────────────────────────────────────────────

interface Props {
  symbol: string;
  trades: TradeEntry[];
  onClose: () => void;
}

export function TradeChart({ symbol, trades, onClose }: Props) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartApi = useRef<IChartApi | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const candleRef = useRef<any>(null);
  const rowRefs = useRef<(HTMLTableRowElement | null)[]>([]);

  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [selectedType, setSelectedType] = useState<"entry" | "exit">("exit");

  // ── Data fetching ─────────────────────────────────────────────────────────
  const { data: barsData, isLoading: barsLoading } = useQuery({
    queryKey: ["bars", symbol, "5y"],
    queryFn: () => fetchBars(symbol, "5y"),
    retry: false,
  });

  const clickDate =
    selectedIdx !== null
      ? selectedType === "entry"
        ? trades[selectedIdx]?.entry_date
        : trades[selectedIdx]?.exit_date
      : undefined;

  const { data: auditData, isLoading: auditLoading } = useQuery({
    queryKey: ["signalAudit", symbol, clickDate],
    queryFn: () => fetchSignalAudit(symbol, clickDate!),
    enabled: !!clickDate,
    retry: false,
  });

  // ── Cumulative P&L ────────────────────────────────────────────────────────
  const cumulativePnls = trades.reduce<number[]>((acc, t) => {
    acc.push((acc[acc.length - 1] ?? 0) + t.pnl);
    return acc;
  }, []);
  const totalPnl = cumulativePnls[cumulativePnls.length - 1] ?? 0;

  // ── Build markers (with optional highlighting) ────────────────────────────
  const buildMarkers = useCallback(
    (selIdx: number | null) => {
      const markers: Array<{
        time: string;
        position: "aboveBar" | "belowBar";
        color: string;
        shape: "arrowUp" | "arrowDown";
        text: string;
        size: number;
      }> = [];

      for (let i = 0; i < trades.length; i++) {
        const t = trades[i];
        const sel = i === selIdx;
        markers.push({
          time: t.entry_date,
          position: "belowBar",
          color: sel ? "#4ade80" : "#22c55e",
          shape: "arrowUp",
          text: `Buy $${t.entry_price.toFixed(2)}`,
          size: sel ? 2 : 1,
        });
        markers.push({
          time: t.exit_date,
          position: "aboveBar",
          color: sel ? "#f87171" : "#ef4444",
          shape: "arrowDown",
          text: `Sell $${t.exit_price.toFixed(2)}`,
          size: sel ? 2 : 1,
        });
      }
      markers.sort((a, b) => a.time.localeCompare(b.time));
      return markers;
    },
    [trades]
  );

  // ── Main chart creation effect ─────────────────────────────────────────────
  useEffect(() => {
    if (!chartRef.current || !barsData?.bars.length) return;

    if (chartApi.current) {
      chartApi.current.remove();
      chartApi.current = null;
    }
    candleRef.current = null;

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

    const candle = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });
    candle.setData(barsData.bars.map((b) => ({ ...b, time: b.time as string })));
    candleRef.current = candle;
    // Set all markers immediately so they're visible as soon as the chart loads
    candle.setMarkers(buildMarkers(null) as never);

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

    chart.timeScale().fitContent();

    chart.subscribeClick((param) => {
      if (!param.time) {
        setSelectedIdx(null);
        return;
      }
      const t = param.time as string;
      const exitIdx = trades.findIndex((tr) => tr.exit_date === t);
      if (exitIdx >= 0) {
        setSelectedIdx(exitIdx);
        setSelectedType("exit");
        return;
      }
      const entryIdx = trades.findIndex((tr) => tr.entry_date === t);
      if (entryIdx >= 0) {
        setSelectedIdx(entryIdx);
        setSelectedType("entry");
        return;
      }
      setSelectedIdx(null);
    });

    const ro = new ResizeObserver(() => {
      chartApi.current?.applyOptions({ width: chartRef.current?.clientWidth ?? 0 });
    });
    ro.observe(chartRef.current);

    return () => {
      ro.disconnect();
      chartApi.current?.remove();
      chartApi.current = null;
      candleRef.current = null;
    };
  }, [barsData, trades]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Update markers when selection changes ──────────────────────────────────
  useEffect(() => {
    if (!candleRef.current) return;
    candleRef.current.setMarkers(buildMarkers(selectedIdx) as never);
  }, [selectedIdx, buildMarkers]);

  // ── Zoom chart + scroll table row when selection changes ───────────────────
  useEffect(() => {
    if (selectedIdx === null || !barsData?.bars) return;

    const trade = trades[selectedIdx];
    const entryI = barsData.bars.findIndex((b) => b.time === trade.entry_date);
    const exitI = barsData.bars.findIndex((b) => b.time === trade.exit_date);

    if (entryI >= 0 && chartApi.current) {
      const BUFFER = 15;
      const from = Math.max(0, entryI - BUFFER);
      const to = Math.min(
        barsData.bars.length - 1,
        (exitI >= 0 ? exitI : entryI) + BUFFER
      );
      chartApi.current.timeScale().setVisibleLogicalRange({ from, to });
    }

    rowRefs.current[selectedIdx]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [selectedIdx, barsData, trades]);

  // ── Derived selected-trade data ────────────────────────────────────────────
  const selected =
    selectedIdx !== null
      ? {
          trade: trades[selectedIdx],
          type: selectedType,
          cumulativePnl: cumulativePnls[selectedIdx],
        }
      : null;

  // ── Render ─────────────────────────────────────────────────────────────────
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
          <span className="text-xs text-slate-500">
            {trades.length} trade{trades.length !== 1 ? "s" : ""}
          </span>
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
            <span className="text-red-400 font-semibold">▼ sell</span> marker — or click
            a table row — to highlight and zoom
          </div>
          <div ref={chartRef} />
        </>
      )}

      {/* Detail panel */}
      {selected && (
        <div className="border-t border-slate-700 px-4 py-4 space-y-4">
          <div className="flex items-start justify-between">
            <div className="space-y-3 flex-1">
              <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">
                {selected.type === "entry" ? "🟢 Buy point" : "🔴 Sell point"}
              </p>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                <div>
                  <p className="text-[10px] text-slate-500 uppercase mb-0.5">Date</p>
                  <p className="text-sm font-mono text-slate-200">
                    {selected.type === "entry"
                      ? selected.trade.entry_date
                      : selected.trade.exit_date}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] text-slate-500 uppercase mb-0.5">Price</p>
                  <p className="text-sm font-mono text-slate-200">
                    ${(selected.type === "entry"
                      ? selected.trade.entry_price
                      : selected.trade.exit_price
                    ).toFixed(2)}
                  </p>
                </div>
                {selected.type === "entry" && (
                  <>
                    <div>
                      <p className="text-[10px] text-slate-500 uppercase mb-0.5">Shares</p>
                      <p className="text-sm font-mono text-slate-200">
                        {selected.trade.shares.toFixed(2)}
                      </p>
                    </div>
                    <div>
                      <p className="text-[10px] text-slate-500 uppercase mb-0.5">Initial Stop</p>
                      <p className="text-sm font-mono text-slate-200">
                        ${selected.trade.initial_stop.toFixed(2)}
                      </p>
                    </div>
                  </>
                )}
                {selected.type === "exit" && (
                  <>
                    <div>
                      <p className="text-[10px] text-slate-500 uppercase mb-0.5">Trade P&L</p>
                      <p
                        className={`text-sm font-mono font-semibold ${
                          selected.trade.pnl >= 0 ? "text-emerald-400" : "text-red-400"
                        }`}
                      >
                        {fmtMoney(selected.trade.pnl)}{" "}
                        <span className="text-xs font-normal">
                          ({fmtPct(selected.trade.pnl_pct)})
                        </span>
                      </p>
                    </div>
                    <div>
                      <p className="text-[10px] text-slate-500 uppercase mb-0.5">
                        Cumulative P&L
                      </p>
                      <p
                        className={`text-sm font-mono font-semibold ${
                          selected.cumulativePnl >= 0 ? "text-emerald-400" : "text-red-400"
                        }`}
                      >
                        {fmtMoney(selected.cumulativePnl)}
                      </p>
                    </div>
                    <div>
                      <p className="text-[10px] text-slate-500 uppercase mb-0.5">Exit Reason</p>
                      <p className="text-sm text-slate-300">
                        {fmtExitReason(selected.trade.exit_reason)}
                      </p>
                    </div>
                  </>
                )}
              </div>
            </div>
            <button
              onClick={() => setSelectedIdx(null)}
              className="text-slate-600 hover:text-slate-300 text-xl leading-none ml-4 mt-0.5"
            >
              ×
            </button>
          </div>

          {/* Strategy score on clicked date */}
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
                  <p
                    className={`text-xl font-bold font-mono ${
                      auditData.composite >= 0 ? "text-emerald-400" : "text-red-400"
                    }`}
                  >
                    {auditData.composite >= 0 ? "+" : ""}
                    {auditData.composite.toFixed(1)}
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
                      <p
                        className={`text-xs font-mono ${
                          !val.fired
                            ? "text-slate-600"
                            : val.side === "entry"
                            ? "text-emerald-400"
                            : "text-orange-400"
                        }`}
                      >
                        {val.contribution.toFixed(0)}
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
                ref={(el) => {
                  rowRefs.current[i] = el;
                }}
                onClick={() => {
                  setSelectedIdx(i);
                  setSelectedType("exit");
                }}
                className={`border-b border-slate-800 cursor-pointer transition-colors ${
                  i === selectedIdx
                    ? "bg-cyan-900/25 border-l-2 border-l-cyan-500"
                    : "hover:bg-slate-800/40"
                }`}
              >
                <td className="px-4 py-2 text-slate-500 text-xs">{i + 1}</td>
                <td
                  className={`px-4 py-2 text-xs font-semibold ${
                    t.side === "long" ? "text-emerald-400" : "text-red-400"
                  }`}
                >
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
                <td
                  className={`px-4 py-2 text-right font-mono font-semibold text-xs ${
                    t.pnl >= 0 ? "text-emerald-400" : "text-red-400"
                  }`}
                >
                  {fmtMoney(t.pnl)}
                </td>
                <td
                  className={`px-4 py-2 text-right font-mono text-xs ${
                    t.pnl_pct >= 0 ? "text-emerald-400" : "text-red-400"
                  }`}
                >
                  {fmtPct(t.pnl_pct)}
                </td>
                <td
                  className={`px-4 py-2 text-right font-mono text-xs ${
                    cumulativePnls[i] >= 0 ? "text-emerald-400/70" : "text-red-400/70"
                  }`}
                >
                  {fmtMoney(cumulativePnls[i])}
                </td>
                <td className="px-4 py-2 text-xs text-slate-500">
                  {fmtExitReason(t.exit_reason)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
