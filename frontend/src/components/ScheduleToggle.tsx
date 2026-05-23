import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchSchedule, putSchedule } from "../lib/api";
import { LoadingState } from "./LoadingState";
import { ErrorState } from "./ErrorState";

function formatUtc(iso: string | null) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
      hour12: false, timeZoneName: "short",
    });
  } catch {
    return iso;
  }
}

export function ScheduleToggle() {
  const qc = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["schedule"],
    queryFn: fetchSchedule,
    refetchInterval: 60_000,
  });

  const toggleMutation = useMutation({
    mutationFn: (enabled: boolean) => putSchedule(enabled),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedule"] }),
  });

  if (isLoading) return <LoadingState label="Loading schedule…" />;
  if (error)
    return (
      <ErrorState
        message={`Failed to load schedule: ${(error as Error).message}`}
        onRetry={() => refetch()}
      />
    );
  if (!data) return null;

  const pending = toggleMutation.isPending;

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-700 p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-slate-200">Daily Auto-Run</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Runs <strong className="text-slate-300">both</strong> long &amp; short strategies at{" "}
            <span className="text-cyan-400 font-mono">{data.time} {data.tz}</span> each weekday.
          </p>
        </div>

        {/* Toggle switch */}
        <button
          onClick={() => toggleMutation.mutate(!data.enabled)}
          disabled={pending}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
            data.enabled ? "bg-cyan-600" : "bg-slate-700"
          } ${pending ? "opacity-60 cursor-wait" : "cursor-pointer"}`}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              data.enabled ? "translate-x-6" : "translate-x-1"
            }`}
          />
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3 text-xs">
        <div className="bg-slate-800 rounded-lg px-3 py-2">
          <p className="text-slate-500 mb-0.5">Last run</p>
          <p className="text-slate-200 font-mono">{data.last_run_date ?? "never"}</p>
        </div>
        <div className="bg-slate-800 rounded-lg px-3 py-2">
          <p className="text-slate-500 mb-0.5">Next run</p>
          <p className="text-slate-200 font-mono">
            {data.enabled && data.next_run ? formatUtc(data.next_run) : "—"}
          </p>
        </div>
      </div>

      <p className="text-[11px] text-slate-600 leading-relaxed border-t border-slate-800 pt-3">
        {data.note}
      </p>

      {toggleMutation.error && (
        <p className="text-xs text-red-400">{(toggleMutation.error as Error).message}</p>
      )}
    </div>
  );
}
