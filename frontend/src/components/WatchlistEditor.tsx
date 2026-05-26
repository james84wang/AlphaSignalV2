import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchWatchlist, addToWatchlist, removeFromWatchlist } from "../lib/api";
import { LoadingState } from "./LoadingState";
import { useLang } from "../lib/LanguageContext";

export function WatchlistEditor() {
  const qc = useQueryClient();
  const { t } = useLang();
  const [input, setInput] = useState("");
  const [addError, setAddError] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["watchlist"],
    queryFn: fetchWatchlist,
  });

  const addMutation = useMutation({
    mutationFn: (sym: string) => addToWatchlist(sym.trim().toUpperCase()),
    onSuccess: () => {
      setInput("");
      setAddError(null);
      qc.invalidateQueries({ queryKey: ["watchlist"] });
    },
    onError: (e: Error) => setAddError(e.message),
  });

  const removeMutation = useMutation({
    mutationFn: (sym: string) => removeFromWatchlist(sym),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });

  function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    const sym = input.trim().toUpperCase();
    if (!sym) return;
    if (!/^[A-Z0-9]{1,10}$/.test(sym)) {
      setAddError(t("watchlist_symbol_error"));
      return;
    }
    setAddError(null);
    addMutation.mutate(sym);
  }

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-700 p-5 space-y-4">
      <h2 className="text-sm font-semibold text-slate-200">{t("watchlist_title")}</h2>

      {isLoading ? (
        <LoadingState label={t("watchlist_loading")} />
      ) : (
        <div className="space-y-1 max-h-48 overflow-y-auto">
          {!data || data.symbols.length === 0 ? (
            <p className="text-xs text-slate-500 italic">{t("watchlist_empty")}</p>
          ) : (
            data.symbols.map((entry) => (
              <div
                key={entry.symbol}
                className="flex items-center justify-between px-3 py-1.5 rounded-lg bg-slate-800 group"
              >
                <div className="flex items-center gap-3">
                  <span className="text-sm font-semibold text-slate-100 font-mono">
                    {entry.symbol}
                  </span>
                  {entry.note && (
                    <span className="text-xs text-slate-500">{entry.note}</span>
                  )}
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
      )}

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
