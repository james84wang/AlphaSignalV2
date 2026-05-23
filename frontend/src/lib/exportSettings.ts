/**
 * Export Long + Short strategy settings to a formatted .xlsx workbook.
 * Each strategy gets its own worksheet with sections for Weights,
 * Thresholds, and all eight Scoring Tables.
 */
import * as XLSX from "xlsx";
import type { ConfigResponse } from "./types";

const WEIGHT_LABELS: Record<string, string> = {
  candlestick: "Candlestick Pattern",
  p3: "3-Bar Pattern (P3)",
  p5: "5-Bar Pattern (P5)",
  volume: "Volume",
  ema: "EMA System",
  sr: "Support / Resistance",
  macd: "MACD",
  rsi: "RSI",
};

const THRESHOLD_LABELS: Record<string, string> = {
  strong_buy: "Strong Buy",
  buy: "Buy",
  sell: "Sell",
  strong_sell: "Strong Sell",
};

const SCORING_TABLE_LABELS: Array<{
  key: keyof ReturnType<typeof getScoringTables>;
  label: string;
}> = [
  { key: "candlestick", label: "Candlestick Patterns" },
  { key: "p3",          label: "3-Bar Patterns (P3)" },
  { key: "p5",          label: "5-Bar Patterns (P5)" },
  { key: "ema_stacking", label: "EMA Stacking" },
  { key: "ema_cross",   label: "EMA Crossovers" },
  { key: "sr",          label: "Support / Resistance" },
  { key: "macd",        label: "MACD Micro-Signals" },
  { key: "rsi",         label: "RSI Zones" },
];

function getScoringTables(cfg: ConfigResponse) {
  return {
    candlestick: cfg.candlestick.scores,
    p3:          cfg.p3.scores,
    p5:          cfg.p5.scores,
    ema_stacking: cfg.ema.stacking_scores,
    ema_cross:   cfg.ema.cross_scores,
    sr:          cfg.sr.scores,
    macd:        cfg.macd.micro_signals,
    rsi:         cfg.rsi.scores,
  };
}

/** Build an array-of-arrays for one strategy sheet. */
function buildSheetData(label: string, cfg: ConfigResponse): unknown[][] {
  const rows: unknown[][] = [];
  const today = new Date().toLocaleDateString("en-US", {
    year: "numeric", month: "long", day: "numeric",
  });

  // ── Title ──────────────────────────────────────────────────────────────────
  rows.push([`AlphaSignal — ${label} Strategy Settings`]);
  rows.push([`Exported: ${today}`]);
  rows.push([]);

  // ── Component Weights ──────────────────────────────────────────────────────
  rows.push(["COMPONENT WEIGHTS"]);
  rows.push(["Component", "Weight (%)"]);
  const weightKeys = ["candlestick", "p3", "p5", "volume", "ema", "sr", "macd", "rsi"] as const;
  let total = 0;
  for (const k of weightKeys) {
    const v = cfg.weights[k];
    rows.push([WEIGHT_LABELS[k] ?? k, v]);
    total += v;
  }
  rows.push(["TOTAL", total]);
  rows.push([]);

  // ── Signal Thresholds ──────────────────────────────────────────────────────
  rows.push(["SIGNAL THRESHOLDS"]);
  rows.push(["Threshold", "Score"]);
  for (const [k, lbl] of Object.entries(THRESHOLD_LABELS)) {
    rows.push([lbl, cfg.thresholds[k as keyof typeof cfg.thresholds]]);
  }
  rows.push([]);

  // ── Scoring Tables ─────────────────────────────────────────────────────────
  rows.push(["SCORING TABLES"]);
  const tables = getScoringTables(cfg);

  for (const { key, label: tableLabel } of SCORING_TABLE_LABELS) {
    rows.push([]);
    rows.push([tableLabel]);
    rows.push(["Pattern / Signal", "Score"]);
    const entries = tables[key] ?? {};
    for (const [pattern, score] of Object.entries(entries)) {
      rows.push([pattern.replace(/_/g, " "), score]);
    }
  }

  return rows;
}

/** Set column widths and bold header rows in the worksheet. */
function styleSheet(ws: XLSX.WorkSheet, data: unknown[][]): void {
  // Column widths: col A = 36 chars, col B = 14 chars
  ws["!cols"] = [{ wch: 36 }, { wch: 14 }];

  // Bold the title row (row 0), section headers, and column headers
  const HEADER_ROWS = new Set<number>();
  HEADER_ROWS.add(0); // title
  data.forEach((row, r) => {
    const cell0 = row[0];
    if (typeof cell0 === "string") {
      if (
        cell0 === "COMPONENT WEIGHTS" ||
        cell0 === "SIGNAL THRESHOLDS" ||
        cell0 === "SCORING TABLES" ||
        cell0 === "Component" ||
        cell0 === "Threshold" ||
        cell0 === "Pattern / Signal" ||
        cell0 === "TOTAL" ||
        SCORING_TABLE_LABELS.some((t) => t.label === cell0)
      ) {
        HEADER_ROWS.add(r);
      }
    }
  });

  for (const r of HEADER_ROWS) {
    const row = data[r];
    if (!row) continue;
    row.forEach((_, c) => {
      const addr = XLSX.utils.encode_cell({ r, c });
      if (!ws[addr]) return;
      if (!ws[addr].s) ws[addr].s = {};
      ws[addr].s.font = { bold: true };
    });
  }
}

/** Download a two-sheet workbook: Long Strategy + Short Strategy. */
export function exportSettingsToExcel(
  longConfig: ConfigResponse,
  shortConfig: ConfigResponse,
): void {
  const wb = XLSX.utils.book_new();

  const longData = buildSheetData("Long", longConfig);
  const shortData = buildSheetData("Short", shortConfig);

  const wsLong = XLSX.utils.aoa_to_sheet(longData);
  const wsShort = XLSX.utils.aoa_to_sheet(shortData);

  styleSheet(wsLong, longData);
  styleSheet(wsShort, shortData);

  XLSX.utils.book_append_sheet(wb, wsLong, "Long Strategy");
  XLSX.utils.book_append_sheet(wb, wsShort, "Short Strategy");

  const dateTag = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  XLSX.writeFile(wb, `alphasignal_settings_${dateTag}.xlsx`);
}
