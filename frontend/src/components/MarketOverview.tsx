import { useQuery } from "@tanstack/react-query";
import { fetchMarketOverview } from "../lib/api";
import type { IndexTile, FearAndGreed } from "../lib/types";

const INDEX_ORDER = [
  "sp500", "midcap", "smallcap", "xlk", "nasdaq", "ndx100", "vix",
] as const;

const FG_COLOR: Record<string, string> = {
  "Extreme Fear": "text-red-400",
  Fear: "text-orange-400",
  Neutral: "text-slate-300",
  Greed: "text-emerald-400",
  "Extreme Greed": "text-emerald-300",
};

function changeCls(pct: number | undefined) {
  if (pct === undefined) return "text-slate-500";
  return pct >= 0 ? "text-emerald-400" : "text-red-400";
}

function formatChange(pct: number) {
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

function IndexCard({ tile }: { tile: IndexTile }) {
  if (tile.status === "unavailable") {
    return (
      <div className="flex flex-col items-center px-4 py-2 min-w-[110px]">
        <span className="text-[10px] text-slate-500 uppercase tracking-wider mb-1 truncate max-w-[100px]">
          {tile.label}
        </span>
        <span className="text-xs text-slate-600 italic">unavailable</span>
      </div>
    );
  }
  return (
    <div className="flex flex-col items-center px-4 py-2 min-w-[110px]">
      <span className="text-[10px] text-slate-500 uppercase tracking-wider mb-1 truncate max-w-[100px]">
        {tile.label}
      </span>
      <span className="text-sm font-bold text-slate-100 font-mono">
        {tile.last !== undefined
          ? tile.last >= 1000
            ? tile.last.toLocaleString("en-US", { maximumFractionDigits: 0 })
            : tile.last.toFixed(2)
          : "—"}
      </span>
      <span className={`text-[11px] font-semibold font-mono ${changeCls(tile.change_pct)}`}>
        {tile.change_pct !== undefined ? formatChange(tile.change_pct) : "—"}
      </span>
    </div>
  );
}

function FgCard({ fg }: { fg: FearAndGreed }) {
  if (fg.status === "unavailable") {
    return (
      <div className="flex flex-col items-center px-4 py-2 min-w-[130px]">
        <span className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Fear & Greed</span>
        <span className="text-xs text-slate-600 italic">unavailable</span>
      </div>
    );
  }
  const ratingCls = fg.rating ? (FG_COLOR[fg.rating] ?? "text-slate-300") : "text-slate-300";
  return (
    <div className="flex flex-col items-center px-4 py-2 min-w-[130px]">
      <span className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Fear & Greed</span>
      <span className={`text-sm font-bold font-mono ${ratingCls}`}>
        {fg.score !== undefined ? fg.score.toFixed(0) : "—"}
      </span>
      <span className={`text-[11px] font-semibold ${ratingCls}`}>{fg.rating ?? "—"}</span>
    </div>
  );
}

function Divider() {
  return <div className="w-px h-8 bg-slate-700 self-center flex-shrink-0" />;
}

export function MarketOverview() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["marketOverview"],
    queryFn: () => fetchMarketOverview(),
    refetchInterval: 15 * 60 * 1000,
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="bg-slate-900 border-b border-slate-800 px-6 py-2 flex items-center gap-1 overflow-x-auto">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="min-w-[110px] h-10 bg-slate-800 rounded animate-pulse mx-1" />
        ))}
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="bg-slate-900 border-b border-slate-800 px-6 py-2 text-xs text-slate-500 italic">
        Market overview unavailable
      </div>
    );
  }

  const tiles = INDEX_ORDER.map((k) => data.indices[k]).filter(Boolean);

  return (
    <div className="bg-slate-900 border-b border-slate-800 px-2 overflow-x-auto flex-shrink-0">
      <div className="flex items-stretch min-w-max">
        {tiles.map((tile, i) => (
          <span key={tile.symbol} className="flex items-stretch">
            <IndexCard tile={tile} />
            {i < tiles.length - 1 && <Divider />}
          </span>
        ))}
        <Divider />
        <FgCard fg={data.fear_and_greed} />
      </div>
    </div>
  );
}
