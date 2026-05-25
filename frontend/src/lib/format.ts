/** Shared number-formatting helpers. */

/**
 * Format a dollar value with thousands separator.
 * e.g.  4210.5  → "$4,211"
 *      -1230    → "-$1,230"
 */
export function fmtMoney(n: number, decimals = 0): string {
  const abs = Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  return n >= 0 ? `$${abs}` : `-$${abs}`;
}

/**
 * Format a percentage with sign.
 * e.g.  7.346  → "+7.35%"
 *      -3.2    → "-3.20%"
 */
export function fmtPct(n: number, decimals = 2): string {
  return `${n >= 0 ? "+" : ""}${n.toFixed(decimals)}%`;
}
