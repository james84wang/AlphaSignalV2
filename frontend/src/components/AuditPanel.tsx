import type { SignalAudit, ConfluenceComponent } from "../lib/types";
import { ENTRY_COMPONENTS, EXIT_COMPONENTS } from "../lib/types";
import { SignalBadge } from "./SignalBadge";
import { useLang } from "../lib/LanguageContext";

const COMPONENT_LABEL_KEY: Record<string, Parameters<ReturnType<typeof useLang>["t"]>[0]> = {
  macd_hidden_bull: "w_macd_hidden_bull",
  rsi_hidden_bull: "w_rsi_hidden_bull",
  rsi_zone: "w_rsi_zone",
  demark_td9_buy: "w_demark_td9_buy",
  demark_td13_sell: "w_demark_td13_sell",
  macd_regular_bear: "w_macd_regular_bear",
  rsi_regular_bear: "w_rsi_regular_bear",
  demark_td9_sell: "w_demark_td9_sell",
};

function fmt(n: number) {
  return n.toFixed(1);
}

function ComponentTable({
  title,
  names,
  components,
  accent,
}: {
  title: string;
  names: readonly string[];
  components: Record<string, ConfluenceComponent>;
  accent: string;
}) {
  const { t } = useLang();
  return (
    <div className="bg-slate-800/40 rounded-xl border border-slate-700 overflow-hidden">
      <div className="px-4 py-2 border-b border-slate-700">
        <span className={`text-[11px] font-bold uppercase tracking-widest ${accent}`}>{title}</span>
      </div>
      <div className="divide-y divide-slate-700/40">
        {names.map((name) => {
          const c = components[name];
          if (!c) return null;
          return (
            <div key={name} className="grid grid-cols-[1fr_44px_56px_64px] gap-x-3 items-center px-4 py-2">
              <span className="text-sm text-slate-200">{t(COMPONENT_LABEL_KEY[name])}</span>
              <span className="text-right text-xs font-mono text-slate-400">{fmt(c.weight)}</span>
              <span className={`text-right text-xs font-semibold ${c.fired ? accent : "text-slate-600"}`}>
                {c.fired ? t("audit_fired") : "—"}
              </span>
              <span
                className={`text-right text-sm font-mono font-semibold ${
                  c.contribution > 0 ? accent : "text-slate-600"
                }`}
              >
                {fmt(c.contribution)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface Props {
  audit: SignalAudit;
}

export function AuditPanel({ audit }: Props) {
  const { t } = useLang();
  const uptrend = audit.regime.long_allowed;

  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl p-5 space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <span className="text-2xl font-bold text-slate-100">{fmt(audit.composite)}</span>
            <SignalBadge signal={audit.signal} />
            <span className="text-xs text-slate-500 uppercase">
              {audit.source === "db" ? "from DB" : "computed"}
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-1">{audit.date}</p>
        </div>

        {/* Regime gate (long-only) */}
        <div
          className={`text-xs font-semibold px-3 py-1.5 rounded-lg border ${
            uptrend
              ? "border-emerald-500/40 bg-emerald-950/30 text-emerald-300"
              : "border-slate-600 bg-slate-800/40 text-slate-400"
          }`}
        >
          {uptrend ? t("regime_uptrend") : t("regime_no_uptrend")}
        </div>
      </div>

      {/* Entry / Exit score summary */}
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-slate-800 rounded-xl px-4 py-3">
          <p className="text-xs text-slate-500 mb-1">{t("audit_entry_score")}</p>
          <p className="text-lg font-bold font-mono text-emerald-400">{fmt(audit.entry_score)}</p>
        </div>
        <div className="bg-slate-800 rounded-xl px-4 py-3">
          <p className="text-xs text-slate-500 mb-1">{t("audit_exit_score")}</p>
          <p className="text-lg font-bold font-mono text-orange-400">{fmt(audit.exit_score)}</p>
        </div>
      </div>

      {/* Component breakdown */}
      <div className="space-y-3">
        <div className="grid grid-cols-[1fr_44px_56px_64px] gap-x-3 text-[10px] text-slate-500 uppercase font-medium px-4">
          <span>{t("audit_entry_components")}</span>
          <span className="text-right">Wt</span>
          <span className="text-right">Hit</span>
          <span className="text-right">Pts</span>
        </div>
        <ComponentTable
          title={t("audit_entry_components")}
          names={ENTRY_COMPONENTS}
          components={audit.components}
          accent="text-emerald-400"
        />
        <ComponentTable
          title={t("audit_exit_components")}
          names={EXIT_COMPONENTS}
          components={audit.components}
          accent="text-orange-400"
        />
      </div>
    </div>
  );
}
