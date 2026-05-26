import { useQuery } from "@tanstack/react-query";
import { fetchInverseEtfs } from "../lib/api";
import { LoadingState } from "./LoadingState";
import { ErrorState } from "./ErrorState";
import { useLang } from "../lib/LanguageContext";

export function InverseEtfEditor() {
  const { t } = useLang();
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["inverseEtfs"],
    queryFn: fetchInverseEtfs,
  });

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-700 p-5 space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-slate-200">{t("inverse_etf_title")}</h2>
        <p className="text-xs text-slate-500 mt-1">{t("inverse_etf_desc")}</p>
      </div>

      {isLoading ? (
        <LoadingState label={t("loading")} />
      ) : error ? (
        <ErrorState
          message={`${t("error")}: ${(error as Error).message}`}
          onRetry={() => refetch()}
        />
      ) : !data || data.count === 0 ? (
        <p className="text-xs text-slate-500 italic">{t("inverse_etf_empty")}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-700 text-slate-500 uppercase">
                <th className="pb-2 pr-4">{t("col_underlying")}</th>
                <th className="pb-2 pr-4">{t("col_inverse_etf")}</th>
                <th className="pb-2 pr-4">{t("col_leverage")}</th>
                <th className="pb-2">{t("note")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {Object.entries(data.map).map(([underlying, entry]) => (
                <tr key={underlying}>
                  <td className="py-1.5 pr-4 font-mono font-semibold text-slate-200">
                    {underlying}
                  </td>
                  <td className="py-1.5 pr-4 font-mono text-cyan-400">
                    {entry.inverse_etf_symbol}
                  </td>
                  <td className="py-1.5 pr-4 text-slate-400">{entry.leverage}×</td>
                  <td className="py-1.5 text-slate-500">{entry.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
