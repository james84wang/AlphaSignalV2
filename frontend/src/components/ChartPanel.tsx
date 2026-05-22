import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  CrosshairMode,
  LineStyle,
  type IChartApi,
} from "lightweight-charts";
import type { Bar } from "../lib/types";
import {
  computeEma,
  computeMacd,
  computeRsi,
} from "../lib/indicators";

const BG = "#0f172a";
const GRID = "#1e293b";
const TEXT = "#94a3b8";
const BORDER = "#334155";

const EMA_COLORS: Record<number, string> = {
  20: "#22d3ee",
  50: "#a78bfa",
  100: "#fb923c",
  200: "#f59e0b",
};

function makeChart(el: HTMLDivElement, height: number): IChartApi {
  return createChart(el, {
    layout: {
      background: { type: ColorType.Solid, color: BG },
      textColor: TEXT,
    },
    grid: {
      vertLines: { color: GRID },
      horzLines: { color: GRID },
    },
    crosshair: { mode: CrosshairMode.Normal },
    rightPriceScale: { borderColor: BORDER },
    timeScale: { borderColor: BORDER, timeVisible: true },
    width: el.clientWidth,
    height,
  });
}

interface Props {
  bars: Bar[];
}

export function ChartPanel({ bars }: Props) {
  const mainRef = useRef<HTMLDivElement>(null);
  const macdRef = useRef<HTMLDivElement>(null);
  const rsiRef = useRef<HTMLDivElement>(null);
  const chartsRef = useRef<IChartApi[]>([]);

  useEffect(() => {
    if (!mainRef.current || !macdRef.current || !rsiRef.current) return;
    if (bars.length === 0) return;

    // Cleanup previous charts
    chartsRef.current.forEach((c) => c.remove());
    chartsRef.current = [];

    // --- Main chart ---
    const main = makeChart(mainRef.current, 360);
    chartsRef.current.push(main);

    const candle = main.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });
    candle.setData(bars.map((b) => ({ ...b, time: b.time as string })));

    for (const period of [20, 50, 100, 200]) {
      const data = computeEma(bars, period);
      if (data.length > 0) {
        const s = main.addLineSeries({
          color: EMA_COLORS[period],
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          title: `EMA${period}`,
        });
        s.setData(data as never);
      }
    }

    // --- MACD chart ---
    const macd = makeChart(macdRef.current, 130);
    macd.applyOptions({ timeScale: { visible: false } });
    chartsRef.current.push(macd);

    const { macdLine, signalLine, histogram } = computeMacd(bars);

    const histSeries = macd.addHistogramSeries({
      color: "#22c55e",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    histSeries.setData(histogram as never);

    const macdSeries = macd.addLineSeries({
      color: "#22d3ee",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    macdSeries.setData(macdLine as never);

    const sigSeries = macd.addLineSeries({
      color: "#f59e0b",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    sigSeries.setData(signalLine as never);

    // --- RSI chart ---
    const rsi = makeChart(rsiRef.current, 110);
    rsi.applyOptions({ timeScale: { visible: false } });
    chartsRef.current.push(rsi);

    const rsiData = computeRsi(bars);
    const rsiSeries = rsi.addLineSeries({
      color: "#c084fc",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    rsiSeries.setData(rsiData as never);

    // Reference lines at 30/50/70
    for (const { price, color } of [
      { price: 70, color: "#ef444466" },
      { price: 50, color: "#64748b66" },
      { price: 30, color: "#22c55e66" },
    ]) {
      rsiSeries.createPriceLine({
        price,
        color,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "",
      });
    }

    // Sync time scales: any chart drives the others
    let syncing = false;
    const charts = [main, macd, rsi];
    charts.forEach((src) => {
      src.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (syncing || range === null) return;
        syncing = true;
        charts.forEach((dst) => {
          if (dst !== src) dst.timeScale().setVisibleLogicalRange(range);
        });
        syncing = false;
      });
    });

    // ResizeObserver for the main container
    const ro = new ResizeObserver(() => {
      const w = mainRef.current?.clientWidth ?? 0;
      if (w > 0) {
        main.applyOptions({ width: w });
        macd.applyOptions({ width: w });
        rsi.applyOptions({ width: w });
      }
    });
    if (mainRef.current) ro.observe(mainRef.current);

    return () => {
      ro.disconnect();
      chartsRef.current.forEach((c) => c.remove());
      chartsRef.current = [];
    };
  }, [bars]);

  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl overflow-hidden">
      {/* EMA legend */}
      <div className="flex items-center gap-4 px-4 py-2 border-b border-slate-700 text-xs">
        {[20, 50, 100, 200].map((p) => (
          <span key={p} className="flex items-center gap-1.5">
            <span
              className="inline-block w-6 h-0.5 rounded"
              style={{ backgroundColor: EMA_COLORS[p] }}
            />
            <span style={{ color: EMA_COLORS[p] }}>EMA{p}</span>
          </span>
        ))}
      </div>

      <div ref={mainRef} />

      {/* MACD label */}
      <div className="flex items-center gap-3 px-4 pt-2 text-xs text-slate-400 border-t border-slate-800">
        <span className="font-medium text-slate-300">MACD</span>
        <span className="flex items-center gap-1">
          <span className="w-4 h-0.5 bg-cyan-400 inline-block" />
          <span>MACD</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="w-4 h-0.5 bg-amber-400 inline-block" />
          <span>Signal</span>
        </span>
      </div>
      <div ref={macdRef} />

      {/* RSI label */}
      <div className="flex items-center gap-3 px-4 pt-2 text-xs text-slate-400 border-t border-slate-800">
        <span className="font-medium text-slate-300">RSI (14)</span>
        <span className="flex items-center gap-1">
          <span className="w-4 h-0.5 bg-purple-400 inline-block" />
          <span>RSI</span>
        </span>
        <span className="text-slate-600">— 30 / 50 / 70</span>
      </div>
      <div ref={rsiRef} />
    </div>
  );
}
