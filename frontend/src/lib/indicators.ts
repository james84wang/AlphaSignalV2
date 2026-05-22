import type { Bar } from "./types";

export interface TimeValue {
  time: string;
  value: number;
}

export interface MacdData {
  macdLine: TimeValue[];
  signalLine: TimeValue[];
  histogram: Array<{ time: string; value: number; color: string }>;
}

function emaValues(values: number[], period: number): (number | null)[] {
  const result: (number | null)[] = new Array(values.length).fill(null);
  if (values.length < period) return result;
  const k = 2 / (period + 1);
  let ema = values.slice(0, period).reduce((s, v) => s + v, 0) / period;
  result[period - 1] = ema;
  for (let i = period; i < values.length; i++) {
    ema = values[i] * k + ema * (1 - k);
    result[i] = ema;
  }
  return result;
}

export function computeEma(bars: Bar[], period: number): TimeValue[] {
  const closes = bars.map((b) => b.close);
  const vals = emaValues(closes, period);
  const result: TimeValue[] = [];
  vals.forEach((v, i) => {
    if (v !== null) result.push({ time: bars[i].time, value: v });
  });
  return result;
}

export function computeMacd(bars: Bar[], fast = 12, slow = 26, sig = 9): MacdData {
  const closes = bars.map((b) => b.close);
  const times = bars.map((b) => b.time);

  const fastEma = emaValues(closes, fast);
  const slowEma = emaValues(closes, slow);

  const macdRaw: (number | null)[] = closes.map((_, i) =>
    fastEma[i] !== null && slowEma[i] !== null ? fastEma[i]! - slowEma[i]! : null
  );

  // Compute signal line on the valid portion of macdRaw
  const validStart = macdRaw.findIndex((v) => v !== null);
  if (validStart === -1) return { macdLine: [], signalLine: [], histogram: [] };

  const macdSlice = macdRaw.slice(validStart) as number[];
  const sigSlice = emaValues(macdSlice, sig);

  const sigLine: (number | null)[] = new Array(closes.length).fill(null);
  sigSlice.forEach((v, i) => { sigLine[validStart + i] = v; });

  const macdLine: TimeValue[] = [];
  const signalLine: TimeValue[] = [];
  const histogram: Array<{ time: string; value: number; color: string }> = [];

  closes.forEach((_, i) => {
    const m = macdRaw[i];
    const s = sigLine[i];
    if (m !== null) macdLine.push({ time: times[i], value: m });
    if (s !== null) signalLine.push({ time: times[i], value: s });
    if (m !== null && s !== null) {
      const h = m - s;
      histogram.push({
        time: times[i],
        value: h,
        color: h >= 0 ? "#22c55e" : "#ef4444",
      });
    }
  });

  return { macdLine, signalLine, histogram };
}

export function computeRsi(bars: Bar[], period = 14): TimeValue[] {
  const closes = bars.map((b) => b.close);
  const times = bars.map((b) => b.time);
  const result: TimeValue[] = [];

  if (closes.length < period + 1) return result;

  const gains: number[] = [];
  const losses: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    gains.push(d > 0 ? d : 0);
    losses.push(d < 0 ? -d : 0);
  }

  let avgG = gains.slice(0, period).reduce((a, b) => a + b, 0) / period;
  let avgL = losses.slice(0, period).reduce((a, b) => a + b, 0) / period;
  result.push({ time: times[period], value: avgL === 0 ? 100 : 100 - 100 / (1 + avgG / avgL) });

  for (let i = period + 1; i < closes.length; i++) {
    avgG = (avgG * (period - 1) + gains[i - 1]) / period;
    avgL = (avgL * (period - 1) + losses[i - 1]) / period;
    result.push({ time: times[i], value: avgL === 0 ? 100 : 100 - 100 / (1 + avgG / avgL) });
  }

  return result;
}
