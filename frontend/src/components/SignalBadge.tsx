import { useLang } from "../lib/LanguageContext";
import type { SignalLabel } from "../lib/types";

const STYLES: Record<SignalLabel, string> = {
  "Strong Buy": "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
  Buy: "bg-green-500/20 text-green-300 border-green-500/40",
  Hold: "bg-slate-500/20 text-slate-300 border-slate-500/40",
  Sell: "bg-orange-500/20 text-orange-300 border-orange-500/40",
  "Strong Sell": "bg-red-500/20 text-red-300 border-red-500/40",
};

const SIGNAL_KEY = {
  "Strong Buy": "signal_strong_buy",
  Buy: "signal_buy",
  Hold: "signal_hold",
  Sell: "signal_sell",
  "Strong Sell": "signal_strong_sell",
} as const;

export function signalColor(signal: SignalLabel): string {
  if (signal === "Strong Buy") return "text-emerald-400";
  if (signal === "Buy") return "text-green-400";
  if (signal === "Hold") return "text-slate-400";
  if (signal === "Sell") return "text-orange-400";
  return "text-red-400";
}

export function compositeColor(score: number): string {
  if (score >= 70) return "text-emerald-400";
  if (score >= 30) return "text-green-400";
  if (score > -30) return "text-slate-300";
  if (score > -70) return "text-orange-400";
  return "text-red-400";
}

export function SignalBadge({ signal }: { signal: SignalLabel }) {
  const { t } = useLang();
  return (
    <span
      className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold border ${STYLES[signal]}`}
    >
      {t(SIGNAL_KEY[signal])}
    </span>
  );
}
