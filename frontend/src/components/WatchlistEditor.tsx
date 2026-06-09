import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchWatchlists, addToWatchlist, removeFromWatchlist } from "../lib/api";
import { LoadingState } from "./LoadingState";
import { useLang } from "../lib/LanguageContext";

export function WatchlistEditor() {
  const qc = useQueryClient();
  const { t } = useLang();
  const [activeList, setActiveList] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [addError, setAddError] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["watchlists"],
    queryFn: fetchWatchlists,
  });

  // Default the active tab to the first list once loaded.
  useEffect(() => {
    if (data && activeList === null && data.lists.length > 0) {
      setActiveList(data.lists[0].name);
    }
  }, [data, activeList]);

  const addMutation = useMutation({
    mutationFn: (sym: string) => addToWatchlist(activeList!, sym),
    onSuccess: () => {
      setInput("");
      setAddError(null);
      qc.invalidateQueries({ queryKey: ["watchlists"] });
      qc.invalidateQueries({ queryKey: ["signals"] });
    },
    onError: (e: Error) => setAddError(e.message),
  });

  const removeMutation = useMutation({
    mutationFn: (sym: string) => removeFromWatchlist(activeList!, sym),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["watchlists"] });
      qc.invalidateQueries({ queryKey: ["signals"] });
    },
  });

  function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    const sym = input.trim().toUpperCase();
    if (!sym || !activeList) return;
    if (!/^[A-Z0-9.\-]{1,10}$/.test(sym)) {
      setAddError(t("watchlist_symbol_error"));
      return;
    }
    setAddError(null);
    addMutation.mutate(sym);
  }

  if (isLoading) return <LoadingState label={t("watchlist_loading")} />;
  if (!data) return null;

  const current = data.lists.find((l) => l.name === activeList) ?? data.lists[0];

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-700 p-5 space-y-4">
      <p className="text-xs text-slate-500">{t("watchlists_desc")}</p>

      {/* List tabs */}
      <div className="flex flex-wrap gap-1 bg-slate-800 rounded-lg p-1 w-fit">
        {data.lists.map((l) => (
          <button
            key={l.name}
            onClick={() => { setActiveList(l.name); setAddError(null); }}
            className={`px-3 py-1.5 rounded text-xs font-semibold transition-all ${
              current?.name === l.name
                ? "bg-cyan-600/30 text-cyan-200 border border-cyan-500/40"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {l.name}
            <span className="ml-1.5 text-slate-500">{l.count}</span>
          </button>
        ))}
      </div>

      {/* Symbols in the active list */}
      <div className="space-y-1 max-h-56 overflow-y-auto">
        {!current || current.symbols.length === 0 ? (
          <p className="text-xs text-slate-500 italic">{t("watchlist_empty")}</p>
        ) : (
          current.symbols.map((entry) => (
            <div
              key={entry.symbol}
              className="flex items-center justify-between px-3 py-1.5 rounded-lg bg-slate-800 group"
            >
              <div className="flex items-center gap-3">
                <span className="text-sm font-semibold text-slate-100 font-mono">{entry.symbol}</span>
                {entry.note && <span className="text-xs text-slate-500">{entry.note}</span>}
              </div>
              <button
                onClick={() => removeMutation.mutate(entry.symbol)}
                disabled={removeMutation.isPending}
                className="text-slate-600 hover:text-red-400 transition-colors text-xs px-2 py-0.5 rounded hover:bg-red-950/40"
              >
                {t("remove")}
              </button>
            </div>
          ))
        )}
      </div>

      {/* Add form */}
      <form onSubmit={handleAdd} className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => { setInput(e.target.value); setAddError(null); }}
          placeholder={t("watchlist_ticker_hint")}
          className="flex-1 bg-slate-800 border border-slate-600 rounded px-3 py-1.5 text-sm font-mono text-slate-100 uppercase placeholder:normal-case placeholder:text-slate-500 focus:outline-none focus:border-cyan-500"
          maxLength={10}
        />
        <button
          type="submit"
          disabled={!input.trim() || addMutation.isPending}
          className="px-4 py-1.5 rounded-lg text-sm font-semibold bg-cyan-600 text-white hover:bg-cyan-500 disabled:bg-slate-700 disabled:text-slate-500 transition-colors"
        >
          {addMutation.isPending ? t("adding") : t("add")}
        </button>
      </form>
      {addError && <p className="text-xs text-red-400">{addError}</p>}
    </div>
  );
}
