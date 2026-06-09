/**
 * Export the Hidden-Divergence Confluence strategy settings to a formatted
 * .xlsx workbook: entry weights + threshold, exit weights + threshold, and the
 * underlying indicator parameters.
 */
import * as XLSX from "xlsx";
import type { ConfigResponse } from "./types";

const ENTRY_LABELS: Record<string, string> = {
  macd_hidden_bull: "MACD hidden bullish divergence",
  rsi_hidden_bull: "RSI hidden bullish divergence",
  rsi_zone: "RSI pullback zone (40–55)",
  demark_td9_buy: "DeMark TD9 buy setup",
};

const EXIT_LABELS: Record<string, string> = {
  demark_td13_sell: "DeMark TD13 sell countdown",
  macd_regular_bear: "MACD regular bearish divergence",
  rsi_regular_bear: "RSI regular bearish divergence",
  demark_td9_sell: "DeMark TD9 sell setup",
};

function buildSheetData(cfg: ConfigResponse): unknown[][] {
  const rows: unknown[][] = [];
  const today = new Date().toLocaleDateString("en-US", {
    year: "numeric", month: "long", day: "numeric",
  });

  rows.push(["AlphaSignal — Hidden-Divergence Confluence Strategy"]);
  rows.push([`Exported: ${today}`]);
  rows.push([]);

  // Entry
  rows.push(["ENTRY SIGNAL (BUY)"]);
  rows.push(["Component", "Score"]);
  let entryMax = 0;
  for (const [k, lbl] of Object.entries(ENTRY_LABELS)) {
    const v = cfg.entry.weights[k as keyof typeof cfg.entry.weights];
    rows.push([lbl, v]);
    entryMax += v;
  }
  rows.push(["Max possible entry score", entryMax]);
  rows.push(["Buy threshold (entry score ≥)", cfg.entry.threshold]);
  rows.push(["Confluence window (bars)", cfg.entry.conf_window]);
  rows.push([]);

  // Exit
  rows.push(["EXIT SIGNAL (SELL)"]);
  rows.push(["Component", "Score"]);
  let exitMax = 0;
  for (const [k, lbl] of Object.entries(EXIT_LABELS)) {
    const v = cfg.exit.weights[k as keyof typeof cfg.exit.weights];
    rows.push([lbl, v]);
    exitMax += v;
  }
  rows.push(["Max possible exit score", exitMax]);
  rows.push(["Sell threshold (exit score ≥)", cfg.exit.threshold]);
  rows.push(["Confluence window (bars)", cfg.exit.conf_window]);
  rows.push([]);

  // Parameters
  rows.push(["INDICATOR PARAMETERS"]);
  rows.push(["Group", "Field", "Value"]);
  const groups: Array<[string, Record<string, number>]> = [
    ["Regime", cfg.regime as unknown as Record<string, number>],
    ["Pivots", cfg.pivots as unknown as Record<string, number>],
    ["MACD", cfg.macd as unknown as Record<string, number>],
    ["RSI", cfg.rsi as unknown as Record<string, number>],
    ["DeMark", cfg.demark as unknown as Record<string, number>],
  ];
  for (const [group, obj] of groups) {
    for (const [field, value] of Object.entries(obj)) {
      rows.push([group, field.replace(/_/g, " "), value]);
    }
  }

  return rows;
}

export function exportSettingsToExcel(cfg: ConfigResponse): void {
  const wb = XLSX.utils.book_new();
  const data = buildSheetData(cfg);
  const ws = XLSX.utils.aoa_to_sheet(data);
  ws["!cols"] = [{ wch: 36 }, { wch: 22 }, { wch: 12 }];
  XLSX.utils.book_append_sheet(wb, ws, "Strategy");
  const dateTag = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  XLSX.writeFile(wb, `alphasignal_strategy_${dateTag}.xlsx`);
}
