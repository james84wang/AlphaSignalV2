import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchSignals, postDailyRun, fetchDailyRun } from "../lib/api";
import logo from "../assets/logo.jpeg";

interface Props {
  children: React.ReactNode;
  universe: string;
  onUniverseChange: (u: string) => void;
}

function NavItem({
  to,
  label,
  icon,
}: {
  to: string;
  label: string;
  icon: React.ReactNode;
}) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
          isActive
            ? "bg-cyan-500/15 text-cyan-300 font-medium"
            : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
        }`
      }
    >
      {icon}
      {label}
    </NavLink>
  );
}

export function Layout({ children, universe, onUniverseChange }: Props) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [runJobId, setRunJobId] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<"idle" | "running" | "done" | "error">("idle");

  const { data: signals } = useQuery({
    queryKey: ["signals", universe],
    queryFn: () => fetchSignals({ universe }),
    retry: false,
  });

  const runMutation = useMutation({
    mutationFn: () => postDailyRun({ universe }),
    onSuccess: (data) => {
      setRunJobId(data.job_id);
      setRunStatus("running");
      pollJob(data.job_id);
    },
    onError: () => setRunStatus("error"),
  });

  function pollJob(jobId: string) {
    const interval = setInterval(async () => {
      try {
        const status = await fetchDailyRun(jobId);
        if (status.status === "done") {
          clearInterval(interval);
          setRunStatus("done");
          setRunJobId(null);
          qc.invalidateQueries({ queryKey: ["signals"] });
          setTimeout(() => setRunStatus("idle"), 3000);
        } else if (status.status === "error") {
          clearInterval(interval);
          setRunStatus("error");
          setTimeout(() => setRunStatus("idle"), 4000);
        }
      } catch {
        clearInterval(interval);
        setRunStatus("error");
        setTimeout(() => setRunStatus("idle"), 4000);
      }
    }, 1500);
  }

  const watchlist = signals?.signals.slice(0, 20) ?? [];

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100 overflow-hidden">
      {/* Sidebar */}
      <aside className="w-52 flex-shrink-0 bg-slate-900 border-r border-slate-800 flex flex-col">
        {/* Logo */}
        <div className="p-4 border-b border-slate-800">
          <button
            onClick={() => navigate("/")}
            className="flex items-center gap-3 hover:opacity-80 transition-opacity"
          >
            <img src={logo} alt="AlphaSignal" className="h-8 w-8 rounded-lg" />
            <span className="font-bold text-slate-100 tracking-tight">AlphaSignal</span>
          </button>
        </div>

        {/* Nav */}
        <nav className="p-3 space-y-1 border-b border-slate-800">
          <NavItem
            to="/"
            label="Dashboard"
            icon={
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
              </svg>
            }
          />
          <NavItem
            to="/settings"
            label="Settings"
            icon={
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            }
          />
          <NavItem
            to="/backtest"
            label="Backtest"
            icon={
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
            }
          />
        </nav>

        {/* Universe selector */}
        <div className="p-3 border-b border-slate-800">
          <p className="text-xs text-slate-500 uppercase font-medium mb-2 px-1">Universe</p>
          <div className="flex gap-1">
            {(["watchlist", "sp500"] as const).map((u) => (
              <button
                key={u}
                onClick={() => onUniverseChange(u)}
                className={`flex-1 py-1 text-xs rounded font-medium transition-colors ${
                  universe === u
                    ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                    : "text-slate-400 hover:text-slate-300 border border-transparent hover:border-slate-600"
                }`}
              >
                {u === "watchlist" ? "Watchlist" : "S&P 500"}
              </button>
            ))}
          </div>
        </div>

        {/* Run signals button */}
        <div className="p-3 border-b border-slate-800">
          <button
            onClick={() => runMutation.mutate()}
            disabled={runStatus === "running"}
            className={`w-full py-1.5 text-xs rounded-lg font-semibold transition-all ${
              runStatus === "running"
                ? "bg-amber-500/20 text-amber-300 border border-amber-500/40 cursor-wait"
                : runStatus === "done"
                ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                : runStatus === "error"
                ? "bg-red-500/20 text-red-300 border border-red-500/40"
                : "bg-cyan-500/15 text-cyan-300 border border-cyan-500/30 hover:bg-cyan-500/25"
            }`}
          >
            {runStatus === "running"
              ? "Running…"
              : runStatus === "done"
              ? "Done!"
              : runStatus === "error"
              ? "Error"
              : "Run Signals"}
          </button>
        </div>

        {/* Watchlist */}
        <div className="flex-1 overflow-y-auto">
          {watchlist.length > 0 && (
            <div className="p-3">
              <p className="text-xs text-slate-500 uppercase font-medium mb-2 px-1">
                Watchlist
              </p>
              <div className="space-y-0.5">
                {watchlist.map((s) => (
                  <button
                    key={s.symbol}
                    onClick={() => navigate(`/symbol/${s.symbol}`)}
                    className="w-full flex items-center justify-between px-2 py-1.5 rounded-lg hover:bg-slate-800 transition-colors group"
                  >
                    <span className="text-sm font-medium text-slate-300 group-hover:text-slate-100">
                      {s.symbol}
                    </span>
                    <span
                      className={`text-xs font-semibold ${
                        s.composite >= 0 ? "text-green-400" : "text-red-400"
                      }`}
                    >
                      {s.composite >= 0 ? "+" : ""}
                      {s.composite.toFixed(0)}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto flex flex-col">
        {children}

        {/* Footer with TradingView attribution */}
        <footer className="mt-auto px-6 py-3 border-t border-slate-800 text-xs text-slate-600 flex items-center justify-between flex-shrink-0">
          <span>AlphaSignal — personal use only</span>
          <a
            href="https://www.tradingview.com/"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-slate-400 transition-colors"
          >
            Charts powered by TradingView
          </a>
        </footer>
      </main>
    </div>
  );
}
