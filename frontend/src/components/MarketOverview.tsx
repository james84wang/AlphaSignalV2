import { useQuery } from "@tanstack/react-query";
import { fetchMarketOverview, fetchSparkline } from "../lib/api";
import type { IndexTile, FearAndGreed } from "../lib/types";

// ── helpers ──────────────────────────────────────────────────────────────────

const INDEX_ORDER = [
  "sp500", "dji", "nyse", "midcap", "smallcap", "xlk", "nasdaq", "ndx100", "vix",
] as const;

function changeCls(pct: number | undefined) {
  if (pct === undefined) return "text-slate-500";
  return pct >= 0 ? "text-emerald-400" : "text-red-400";
}

function formatChange(pct: number) {
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

// ── Sparkline ─────────────────────────────────────────────────────────────────

function Sparkline({ symbol, positive }: { symbol: string; positive: boolean }) {
  const { data } = useQuery({
    queryKey: ["sparkline", symbol],
    queryFn: () => fetchSparkline(symbol),
    staleTime: 15 * 60 * 1000,
    retry: false,
    enabled: true,
  });

  if (!data || data.bars.length < 2) {
    return <div className="w-[80px] h-8 mt-1" />;
  }

  const closes = data.bars.map((b) => b.close);
  const minV = Math.min(...closes);
  const maxV = Math.max(...closes);
  const range = maxV - minV || 1;

  const W = 80, H = 32;
  const pts = closes
    .map((p, i) => {
      const x = (i / (closes.length - 1)) * W;
      const y = H - ((p - minV) / range) * (H - 2) - 1;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const color = positive ? "#34d399" : "#f87171";

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="mt-1 opacity-80">
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

// ── Index tile ────────────────────────────────────────────────────────────────

function IndexCard({ tile }: { tile: IndexTile }) {
  if (tile.status === "unavailable") {
    return (
      <div className="flex flex-col items-center px-4 py-2 min-w-[100px]">
        <span className="text-[10px] text-slate-500 uppercase tracking-wider mb-1 truncate max-w-[90px]">
          {tile.label}
        </span>
        <span className="text-xs text-slate-600 italic">unavailable</span>
        <div className="w-[80px] h-8 mt-1" />
      </div>
    );
  }

  const positive = (tile.change_pct ?? 0) >= 0;

  return (
    <div className="flex flex-col items-center px-4 py-2 min-w-[100px]">
      <span className="text-[10px] text-slate-500 uppercase tracking-wider mb-1 truncate max-w-[90px]">
        {tile.label}
      </span>
      <span className="text-sm font-bold text-slate-100 font-mono leading-none">
        {tile.last !== undefined
          ? tile.last >= 1000
            ? tile.last.toLocaleString("en-US", { maximumFractionDigits: 0 })
            : tile.last.toFixed(2)
          : "—"}
      </span>
      <span className={`text-[11px] font-semibold font-mono leading-none mt-0.5 ${changeCls(tile.change_pct)}`}>
        {tile.change_pct !== undefined ? formatChange(tile.change_pct) : "—"}
      </span>
      <Sparkline symbol={tile.symbol} positive={positive} />
    </div>
  );
}

// ── Fear & Greed gauge ────────────────────────────────────────────────────────

const GAUGE_SEGMENTS = [
  { label: "Extreme Fear", from: 0,  to: 20,  color: "#ef4444" },   // red-500
  { label: "Fear",         from: 20, to: 40,  color: "#f97316" },   // orange-500
  { label: "Neutral",      from: 40, to: 60,  color: "#eab308" },   // yellow-500
  { label: "Greed",        from: 60, to: 80,  color: "#84cc16" },   // lime-500
  { label: "Extreme Greed",from: 80, to: 100, color: "#22c55e" },   // green-500
];

// SVG canvas: 120 × 70, arc centred at (60, 62), r=50
const CX = 60, CY = 62, R = 50;

function toRad(deg: number) { return (deg * Math.PI) / 180; }

/** Point on the arc: score 0 → left (180°), score 100 → right (0°) */
function arcPt(score: number, radius: number) {
  const θ = 180 - (score / 100) * 180;
  return {
    x: CX + radius * Math.cos(toRad(θ)),
    y: CY - radius * Math.sin(toRad(θ)),
  };
}

/** SVG arc path for one coloured segment. */
function segPath(fromScore: number, toScore: number, r: number): string {
  const p1 = arcPt(fromScore, r);
  const p2 = arcPt(toScore, r);
  // sweep=1 draws clockwise in SVG (which is counter-clockwise in standard math),
  // going from left → top → right through the upper semicircle.
  return `M ${p1.x.toFixed(2)} ${p1.y.toFixed(2)} A ${r} ${r} 0 0 1 ${p2.x.toFixed(2)} ${p2.y.toFixed(2)}`;
}

const FG_LABEL_COLOR: Record<string, string> = {
  "Extreme Fear": "text-red-400",
  Fear: "text-orange-400",
  Neutral: "text-yellow-400",
  Greed: "text-lime-400",
  "Extreme Greed": "text-green-400",
};

function FearGreedGauge({ fg }: { fg: FearAndGreed }) {
  if (fg.status === "unavailable") {
    return (
      <div className="flex flex-col items-center px-4 py-2 min-w-[130px]">
        <span className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Fear & Greed</span>
        <span className="text-xs text-slate-600 italic">unavailable</span>
      </div>
    );
  }

  const score = fg.score ?? 50;
  const needle = arcPt(score, R - 6);
  const ratingCls = fg.rating ? (FG_LABEL_COLOR[fg.rating] ?? "text-slate-300") : "text-slate-300";

  return (
    <div className="flex flex-col items-center px-3 py-1 min-w-[130px]">
      <span className="text-[10px] text-slate-500 uppercase tracking-wider mb-0.5">Fear & Greed</span>

      {/* SVG gauge */}
      <svg width="120" height="70" viewBox="0 0 120 70" className="-mt-1">
        {/* Background arc (dark track) */}
        <path
          d={segPath(0, 100, R)}
          stroke="#1e293b"
          strokeWidth="10"
          fill="none"
          strokeLinecap="butt"
        />

        {/* Coloured segments */}
        {GAUGE_SEGMENTS.map((seg) => (
          <path
            key={seg.label}
            d={segPath(seg.from, seg.to, R)}
            stroke={seg.color}
            strokeWidth="10"
            fill="none"
            strokeLinecap="butt"
            opacity="0.85"
          />
        ))}

        {/* Needle */}
        <line
          x1={CX}
          y1={CY}
          x2={needle.x.toFixed(2)}
          y2={needle.y.toFixed(2)}
          stroke="white"
          strokeWidth="2"
          strokeLinecap="round"
        />
        {/* Needle pivot */}
        <circle cx={CX} cy={CY} r="3" fill="white" />

        {/* Score label */}
        <text
          x={CX}
          y={CY + 14}
          textAnchor="middle"
          fontSize="13"
          fontWeight="bold"
          fontFamily="monospace"
          fill="white"
        >
          {score.toFixed(0)}
        </text>
      </svg>

      {/* Rating label */}
      <span className={`text-[11px] font-semibold -mt-1 ${ratingCls}`}>
        {fg.rating ?? "—"}
      </span>
    </div>
  );
}

// ── Divider ───────────────────────────────────────────────────────────────────

function Divider() {
  return <div className="w-px h-10 bg-slate-700 self-center flex-shrink-0" />;
}

// ── Main component ────────────────────────────────────────────────────────────

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
          <div key={i} className="min-w-[100px] h-16 bg-slate-800 rounded animate-pulse mx-1" />
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
        <FearGreedGauge fg={data.fear_and_greed} />
      </div>
    </div>
  );
}
