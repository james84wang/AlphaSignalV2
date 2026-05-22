import type { SignalAudit, ComponentKey } from "../lib/types";
import { SignalBadge } from "./SignalBadge";

const COMPONENT_LABELS: Record<ComponentKey, string> = {
  candlestick: "Candlestick",
  p3: "3-Bar Pattern",
  p5: "5-Bar Pattern",
  volume: "Volume",
  ema: "EMA System",
  sr: "Support/Resistance",
  macd: "MACD",
  rsi: "RSI",
};

function ScoreBar({ value }: { value: number }) {
  const pct = ((value + 100) / 200) * 100;
  const color =
    value >= 50
      ? "bg-emerald-500"
      : value >= 0
      ? "bg-green-500"
      : value >= -50
      ? "bg-orange-500"
      : "bg-red-500";
  return (
    <div className="relative h-1.5 w-full bg-slate-700 rounded-full overflow-hidden">
      <div
        className={`absolute left-1/2 h-full rounded-full ${color}`}
        style={{
          width: `${Math.abs(value) / 2}%`,
          transform: value >= 0 ? "translateX(0)" : "translateX(-100%)",
        }}
      />
      {/* Center line */}
      <div className="absolute left-1/2 top-0 w-px h-full bg-slate-500" />
    </div>
  );
}

function fmt(n: number) {
  return n.toFixed(1);
}

interface Props {
  audit: SignalAudit;
}

export function AuditPanel({ audit }: Props) {
  const components = (Object.keys(COMPONENT_LABELS) as ComponentKey[]).map(
    (key) => ({ key, label: COMPONENT_LABELS[key], ...audit.components[key] })
  );

  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl p-5">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="flex items-center gap-3">
            <span className="text-2xl font-bold text-slate-100">
              {fmt(audit.composite)}
            </span>
            <SignalBadge signal={audit.signal} />
            <span className="text-xs text-slate-500 uppercase">
              {audit.source === "db" ? "from DB" : "computed"}
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-1">{audit.date}</p>
        </div>

        {/* Regime gate */}
        <div className="text-right text-xs space-y-1">
          <div
            className={`font-medium ${
              audit.regime.long_allowed ? "text-green-400" : "text-slate-500 line-through"
            }`}
          >
            Long allowed
          </div>
          <div
            className={`font-medium ${
              audit.regime.short_allowed ? "text-red-400" : "text-slate-500 line-through"
            }`}
          >
            Short allowed
          </div>
        </div>
      </div>

      {/* Component breakdown table */}
      <div className="space-y-2">
        <div className="grid grid-cols-[1fr_60px_56px_72px] gap-x-3 text-xs text-slate-500 uppercase font-medium px-1 mb-1">
          <span>Component</span>
          <span className="text-right">Sub</span>
          <span className="text-right">Weight</span>
          <span className="text-right">Contrib</span>
        </div>
        {components.map(({ key, label, sub, weight, weighted }) => (
          <div key={key} className="grid grid-cols-[1fr_60px_56px_72px] gap-x-3 items-center px-1 py-1.5 rounded-lg hover:bg-slate-800 transition-colors">
            <div>
              <div className="text-sm text-slate-200 mb-1">{label}</div>
              <ScoreBar value={sub} />
            </div>
            <span
              className={`text-right text-sm font-mono font-semibold ${
                sub >= 0 ? "text-green-400" : "text-red-400"
              }`}
            >
              {fmt(sub)}
            </span>
            <span className="text-right text-sm font-mono text-slate-400">
              {fmt(weight)}%
            </span>
            <span
              className={`text-right text-sm font-mono font-semibold ${
                weighted >= 0 ? "text-green-300" : "text-red-300"
              }`}
            >
              {weighted >= 0 ? "+" : ""}
              {fmt(weighted)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
