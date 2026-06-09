import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchConfig, putConfig, downloadPineScript } from "../lib/api";
import { WatchlistEditor } from "../components/WatchlistEditor";
import { ScheduleToggle } from "../components/ScheduleToggle";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { exportSettingsToExcel } from "../lib/exportSettings";
import { useLang } from "../lib/LanguageContext";
import type {
  ConfigResponse,
  EntrySide,
  ExitSide,
  StrategyParams,
  EntryWeights,
  ExitWeights,
} from "../lib/types";

type TKey = Parameters<ReturnType<typeof useLang>["t"]>[0];

const ENTRY_WEIGHT_KEYS: Array<[keyof EntryWeights, TKey]> = [
  ["macd_hidden_bull", "w_macd_hidden_bull"],
  ["rsi_hidden_bull", "w_rsi_hidden_bull"],
  ["rsi_zone", "w_rsi_zone"],
  ["demark_td9_buy", "w_demark_td9_buy"],
];

const EXIT_WEIGHT_KEYS: Array<[keyof ExitWeights, TKey]> = [
  ["demark_td13_sell", "w_demark_td13_sell"],
  ["macd_regular_bear", "w_macd_regular_bear"],
  ["rsi_regular_bear", "w_rsi_regular_bear"],
  ["demark_td9_sell", "w_demark_td9_sell"],
];

const PARAM_FIELD_KEY: Record<string, TKey> = {
  ema_fast: "pf_ema_fast", ema_slow: "pf_ema_slow", slope_lookback: "pf_slope_lookback",
  left: "pf_left", right: "pf_right", min_bars: "pf_min_bars", max_bars: "pf_max_bars",
  fast: "pf_fast", slow: "pf_slow", signal: "pf_signal",
  period: "pf_period", zone_low: "pf_zone_low", zone_high: "pf_zone_high",
  setup: "pf_setup", countdown: "pf_countdown",
  setup_lookback: "pf_setup_lookback", countdown_lookback: "pf_countdown_lookback",
};

const PARAM_GROUPS: Array<[keyof StrategyParams, TKey]> = [
  ["regime", "pg_regime"],
  ["pivots", "pg_pivots"],
  ["macd", "pg_macd"],
  ["rsi", "pg_rsi"],
  ["demark", "pg_demark"],
];

// ── Small inputs ───────────────────────────────────────────────────────────────

function WeightRow({
  label, value, accent, onChange,
}: { label: string; value: number; accent: string; onChange: (n: number) => void }) {
  return (
    <div className="flex items-center gap-4">
      <label className="w-64 text-sm text-slate-300 flex-shrink-0">{label}</label>
      <input
        type="range" min={0} max={50} step={1} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className={`flex-1 ${accent}`}
      />
      <input
        type="number" min={0} max={100} step={1} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
        className="w-16 bg-slate-800 border border-slate-600 rounded px-2 py-1 text-sm text-right font-mono text-slate-100 focus:outline-none focus:border-cyan-500"
      />
    </div>
  );
}

function NumField({
  label, value, onChange,
}: { label: string; value: number; onChange: (n: number) => void }) {
  return (
    <div>
      <label className="block text-xs text-slate-400 mb-1">{label}</label>
      <input
        type="number" value={value} step={1}
        onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
        className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 font-mono focus:outline-none focus:border-cyan-500"
      />
    </div>
  );
}

// ── Entry / Exit side editor ────────────────────────────────────────────────────

function SideEditor({
  titleKey, descKey, thresholdKey, accent, weightKeys, side, onChange,
}: {
  titleKey: TKey; descKey: TKey; thresholdKey: TKey; accent: string;
  weightKeys: Array<[string, TKey]>;
  side: EntrySide | ExitSide;
  onChange: (s: EntrySide | ExitSide) => void;
}) {
  const { t } = useLang();
  const weights = side.weights as unknown as Record<string, number>;
  const maxScore = Object.values(weights).reduce((a, b) => a + b, 0);

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-700 p-5 space-y-4">
      <div>
        <h2 className={`text-sm font-bold ${accent}`}>{t(titleKey)}</h2>
        <p className="text-xs text-slate-500 mt-1">{t(descKey)}</p>
      </div>

      <div className="space-y-3">
        <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">
          {t("cfg_component_scores")}
        </p>
        {weightKeys.map(([key, lblKey]) => (
          <WeightRow
            key={key}
            label={t(lblKey)}
            accent={accent === "text-emerald-400" ? "accent-emerald-400" : "accent-orange-400"}
            value={weights[key]}
            onChange={(n) => onChange({ ...side, weights: { ...weights, [key]: n } } as unknown as EntrySide)}
          />
        ))}
        <p className="text-xs text-slate-500">
          {t("cfg_max_score")}: <span className="font-mono text-slate-300">{maxScore}</span>
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 border-t border-slate-800 pt-4">
        <NumField
          label={t(thresholdKey)}
          value={side.threshold}
          onChange={(n) => onChange({ ...side, threshold: n })}
        />
        <NumField
          label={t("cfg_conf_window")}
          value={side.conf_window}
          onChange={(n) => onChange({ ...side, conf_window: Math.max(1, Math.round(n)) })}
        />
      </div>
    </div>
  );
}

// ── Export button ────────────────────────────────────────────────────────────

const DOWNLOAD_ICON = (
  <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
    <path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clipRule="evenodd" />
  </svg>
);

function ExportButton({ cfg, dirty }: { cfg: ConfigResponse | undefined; dirty: boolean }) {
  const { t } = useLang();
  const [pineErr, setPineErr] = useState<string | null>(null);
  const [pineBusy, setPineBusy] = useState(false);

  async function onDownloadPine() {
    setPineErr(null);
    setPineBusy(true);
    try {
      await downloadPineScript();
    } catch (e) {
      setPineErr((e as Error).message);
    } finally {
      setPineBusy(false);
    }
  }

  const btnBase =
    "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold border transition-all";
  const btnEnabled =
    "border-slate-600 bg-slate-800 text-slate-200 hover:border-cyan-500 hover:text-cyan-300";
  const btnDisabled = "border-slate-700 bg-slate-800/40 text-slate-500 cursor-not-allowed";

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={() => cfg && exportSettingsToExcel(cfg)}
          disabled={!cfg}
          className={`${btnBase} ${!cfg ? btnDisabled : btnEnabled}`}
        >
          {DOWNLOAD_ICON}
          {t("export_xlsx")}
        </button>
        <button
          onClick={onDownloadPine}
          disabled={pineBusy}
          className={`${btnBase} ${pineBusy ? btnDisabled : btnEnabled}`}
        >
          {DOWNLOAD_ICON}
          {pineBusy ? t("exporting") : t("export_pine")}
        </button>
        <span className="text-xs text-slate-500">{t("export_pine_desc")}</span>
      </div>
      {dirty && <p className="text-xs text-amber-400/80">{t("export_pine_dirty")}</p>}
      {pineErr && <p className="text-xs text-red-400">{pineErr}</p>}
    </div>
  );
}

// ── Strategy editor ────────────────────────────────────────────────────────────

function StrategyEditor() {
  const qc = useQueryClient();
  const { t } = useLang();

  const { data: config, isLoading, error, refetch } = useQuery({
    queryKey: ["config"],
    queryFn: fetchConfig,
  });

  const [entry, setEntry] = useState<EntrySide | null>(null);
  const [exitSide, setExitSide] = useState<ExitSide | null>(null);
  const [params, setParams] = useState<StrategyParams | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  useEffect(() => {
    if (config && !dirty) {
      setEntry({ ...config.entry, weights: { ...config.entry.weights } });
      setExitSide({ ...config.exit, weights: { ...config.exit.weights } });
      setParams({
        regime: { ...config.regime }, pivots: { ...config.pivots },
        macd: { ...config.macd }, rsi: { ...config.rsi }, demark: { ...config.demark },
      });
    }
  }, [config, dirty]);

  const saveMutation = useMutation({
    mutationFn: () => putConfig({ entry: entry!, exit: exitSide!, params: params! }),
    onSuccess: () => {
      setSaveSuccess(true);
      setDirty(false);
      qc.invalidateQueries({ queryKey: ["config"] });
      qc.invalidateQueries({ queryKey: ["signals"] });
      setTimeout(() => setSaveSuccess(false), 4000);
    },
  });

  function markDirty() { setDirty(true); setSaveSuccess(false); }

  if (isLoading) return <LoadingState label={t("loading")} />;
  if (error) return <ErrorState message={`${t("error")}: ${(error as Error).message}`} onRetry={() => refetch()} />;
  if (!config || !entry || !exitSide || !params) return null;

  return (
    <div className="space-y-6">
      {/* Save bar */}
      {dirty && (
        <div className="flex items-center justify-between gap-4 rounded-xl border border-cyan-600/40 bg-cyan-950/30 px-4 py-3">
          <p className="text-sm text-cyan-200">
            <strong>{t("unsaved_changes")}</strong> {t("unsaved_strategy")}
          </p>
          <div className="flex items-center gap-3 flex-shrink-0">
            {saveSuccess && <span className="text-sm text-emerald-400 font-medium">{t("saved")}</span>}
            {saveMutation.error && (
              <span className="text-xs text-red-400 max-w-xs">{(saveMutation.error as Error).message}</span>
            )}
            <button
              onClick={() => {
                setEntry({ ...config.entry, weights: { ...config.entry.weights } });
                setExitSide({ ...config.exit, weights: { ...config.exit.weights } });
                setParams({
                  regime: { ...config.regime }, pivots: { ...config.pivots },
                  macd: { ...config.macd }, rsi: { ...config.rsi }, demark: { ...config.demark },
                });
                setDirty(false);
              }}
              className="px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-slate-200 border border-slate-600 hover:border-slate-400 transition-colors"
            >
              {t("reset")}
            </button>
            <button
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending}
              className="px-5 py-1.5 rounded-lg text-sm font-semibold bg-cyan-600 text-white hover:bg-cyan-500 disabled:bg-cyan-600/50 disabled:cursor-wait"
            >
              {saveMutation.isPending ? t("saving") : t("save_strategy")}
            </button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <SideEditor
          titleKey="cfg_entry_section" descKey="cfg_entry_desc" thresholdKey="cfg_entry_threshold"
          accent="text-emerald-400" weightKeys={ENTRY_WEIGHT_KEYS as Array<[string, TKey]>}
          side={entry}
          onChange={(s) => { setEntry(s as EntrySide); markDirty(); }}
        />
        <SideEditor
          titleKey="cfg_exit_section" descKey="cfg_exit_desc" thresholdKey="cfg_exit_threshold"
          accent="text-orange-400" weightKeys={EXIT_WEIGHT_KEYS as Array<[string, TKey]>}
          side={exitSide}
          onChange={(s) => { setExitSide(s as ExitSide); markDirty(); }}
        />
      </div>

      {/* Indicator parameters */}
      <div className="bg-slate-900 rounded-xl border border-slate-700 p-5 space-y-4">
        <div>
          <h2 className="text-sm font-semibold text-slate-200">{t("cfg_indicator_params")}</h2>
          <p className="text-xs text-slate-500 mt-1">{t("cfg_indicator_params_hint")}</p>
        </div>
        {PARAM_GROUPS.map(([group, groupKey]) => {
          const obj = params[group] as unknown as Record<string, number>;
          return (
            <div key={group} className="space-y-2">
              <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">{t(groupKey)}</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {Object.entries(obj).map(([field, value]) => (
                  <NumField
                    key={field}
                    label={t(PARAM_FIELD_KEY[field] ?? (field as TKey))}
                    value={value}
                    onChange={(n) => {
                      setParams({ ...params, [group]: { ...obj, [field]: n } });
                      markDirty();
                    }}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <ExportButton cfg={config} dirty={dirty} />
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function Settings() {
  const { t } = useLang();
  return (
    <div className="p-6 max-w-5xl space-y-10">
      <div>
        <h1 className="text-xl font-bold text-slate-100">{t("settings_title")}</h1>
        <p className="text-sm text-slate-500 mt-1">{t("settings_desc_v2")}</p>
      </div>

      <StrategyEditor />

      <div className="border-t border-slate-800 pt-8 space-y-4">
        <h2 className="text-base font-bold text-slate-100">{t("watchlists_title")}</h2>
        <WatchlistEditor />
      </div>

      <div className="border-t border-slate-800 pt-8 space-y-4">
        <h2 className="text-base font-bold text-slate-100">{t("schedule_title")}</h2>
        <ScheduleToggle />
      </div>
    </div>
  );
}
