/**
 * Model input panel: the terrain exactly as given (contour, side lengths, zones, paths,
 * water points F1…Fn with their pumps, entrance), drawn to scale in SVG with north arrow and
 * scale bar. In "pick" mode a click returns the clicked position in local metres.
 */
import { useMemo, useRef } from "react";
import type { Scene, XY } from "../lib/scene";
import { bounds, ZONE_COLORS } from "../lib/scene";

type Props = {
  scene: Scene; height?: number; zoneLabels?: Record<string, string>; entranceLabel?: string;
  sourcesOverride?: { code: string; xy: XY | null; pump_kw?: number | null }[];
  entranceOverride?: XY | null;
  pick?: string | null; onPick?: (xy: XY) => void;
};

function niceStep(len: number) {
  const raw = len / 4, p = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((k) => k * p).find((v) => v >= raw) || raw;
}

export function InputPlan({ scene: s, height = 460, zoneLabels = {}, entranceLabel = "", sourcesOverride, entranceOverride, pick, onPick }: Props) {
  const svg = useRef<SVGSVGElement>(null);
  const b = bounds(s);
  const W = b.maxX - b.minX, H = b.maxY - b.minY;
  const pad = Math.max(W, H) * 0.09;
  const k = 1;                                             // 1 svg unit = 1 m
  const X = (p: XY) => (p[0] - b.minX) * k, Y = (p: XY) => (b.maxY - p[1]) * k;
  const path = (pts: XY[]) => pts.map((p, i) => `${i ? "L" : "M"}${X(p).toFixed(2)},${Y(p).toFixed(2)}`).join("") + "Z";
  const fs = Math.max(W, H) / 38;
  const sources = sourcesOverride ?? s.sources.map((w, i) => ({ code: w.code || `F${i + 1}`, xy: w.xy, pump_kw: w.pump_kw }));
  const entrance = entranceOverride !== undefined ? entranceOverride : s.entrance;
  const step = useMemo(() => niceStep(W), [W]);
  const cx = s.boundary.reduce((a, p) => a + X(p), 0) / s.boundary.length, cy = s.boundary.reduce((a, p) => a + Y(p), 0) / s.boundary.length;
  const click = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!pick || !onPick || !svg.current) return;
    const pt = svg.current.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
    const m = pt.matrixTransform(svg.current.getScreenCTM()!.inverse());
    onPick([Math.round((m.x / k + b.minX) * 10) / 10, Math.round((b.maxY - m.y / k) * 10) / 10]);
  };
  return (
    <svg ref={svg} viewBox={`${-pad} ${-pad} ${W + 2 * pad} ${H + 2 * pad}`} style={{ height, direction: "ltr" }}
      className={`w-full rounded-xl2 border border-brand-100 bg-[#f7faf6] ${pick ? "cursor-crosshair ring-2 ring-water-500" : ""}`}
      onClick={click} role="img" aria-label="plan du terrain">
      <defs>
        <pattern id="grid" width={step / 2} height={step / 2} patternUnits="userSpaceOnUse">
          <path d={`M ${step / 2} 0 L 0 0 0 ${step / 2}`} fill="none" stroke="#e3ebe3" strokeWidth={fs / 14} />
        </pattern>
      </defs>
      <rect x={-pad} y={-pad} width={W + 2 * pad} height={H + 2 * pad} fill="url(#grid)" />
      <path d={path(s.boundary)} fill="#eef6ec" stroke="#1f7a3d" strokeWidth={fs / 4} strokeLinejoin="round" />
      {s.zones.map((z, i) => (
        <g key={i}>
          <path d={path(z.polygon)} fill={ZONE_COLORS[z.kind] || "#9aa5a0"} fillOpacity={0.75} stroke="#5b6b61" strokeWidth={fs / 12} />
          {(() => { const xs = z.polygon.map((p) => p[0]), ys = z.polygon.map((p) => p[1]); const c: XY = [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2];
            return <text x={X(c)} y={Y(c)} fontSize={fs * 0.62} textAnchor="middle" dominantBaseline="middle" fill="#16201a">{zoneLabels[z.kind] || z.label}</text>; })()}
        </g>
      ))}
      {s.lines.filter((l) => l.kind === "path").map((l, i) => (
        <polyline key={i} points={l.line.map((p) => `${X(p)},${Y(p)}`).join(" ")} fill="none" stroke="#c9c3b5" strokeWidth={fs / 2.2} strokeLinecap="round" />
      ))}
      {s.boundary.map((p, i) => {
        const q = s.boundary[(i + 1) % s.boundary.length];
        const L = s.edges?.[i] ?? Math.hypot(q[0] - p[0], q[1] - p[1]);
        const mx = (X(p) + X(q)) / 2, my = (Y(p) + Y(q)) / 2;
        let ang = (Math.atan2(Y(q) - Y(p), X(q) - X(p)) * 180) / Math.PI; if (ang > 90) ang -= 180; if (ang < -90) ang += 180;
        if (L < Math.max(W, H) * 0.06) return null;
        // label outside the polygon: offset along the normal pointing away from the centre
        let nx = (Y(q) - Y(p)), ny = -(X(q) - X(p)); const nl = Math.hypot(nx, ny) || 1;
        if ((mx + nx - cx) ** 2 + (my + ny - cy) ** 2 < (mx - nx - cx) ** 2 + (my - ny - cy) ** 2) { nx = -nx; ny = -ny; }
        const off = -fs * 0.9;
        return <text key={i} x={mx - (nx / nl) * off} y={my - (ny / nl) * off} fontSize={fs * 0.72} fontWeight={600} fill="#1f7a3d"
          textAnchor="middle" dominantBaseline="middle" transform={`rotate(${ang} ${mx - (nx / nl) * off} ${my - (ny / nl) * off})`}>{L.toLocaleString(undefined, { maximumFractionDigits: 1 })} m</text>;
      })}
      {s.boundary.map((p, i) => <circle key={i} cx={X(p)} cy={Y(p)} r={fs / 5} fill="#1f7a3d" />)}
      {sources.map((w, i) => w.xy && (
        <g key={i}>
          <circle cx={X(w.xy)} cy={Y(w.xy)} r={fs * 0.55} fill="#fff" />
          <circle cx={X(w.xy)} cy={Y(w.xy)} r={fs * 0.4} fill="#1c6fb8" />
          <text x={X(w.xy) + fs * 0.75} y={Y(w.xy) - fs * 0.35} fontSize={fs * 0.8} fontWeight={700} fill="#134c7f">{w.code}</text>
          {w.pump_kw ? <text x={X(w.xy) + fs * 0.75} y={Y(w.xy) + fs * 0.6} fontSize={fs * 0.6} fill="#134c7f">⚡ {w.pump_kw} kW</text> : null}
        </g>
      ))}
      {entrance && (
        <g>
          <path d={`M${X(entrance)},${Y(entrance) - fs * 0.6} l${fs * 0.5},${fs} l${-fs},0 Z`} fill="#16201a" />
          {entranceLabel && <text x={X(entrance) + fs * 0.7} y={Y(entrance) + fs * 0.3} fontSize={fs * 0.62} fill="#16201a">{entranceLabel}</text>}
        </g>
      )}
      {/* north arrow and scale bar */}
      <g transform={`translate(${W + pad * 0.45} ${-pad * 0.35})`}>
        <path d={`M0,${fs * 0.2} l${fs * 0.45},${fs * 1.2} l${-fs * 0.45},${-fs * 0.35} l${-fs * 0.45},${fs * 0.35} Z`} fill="#16201a" />
        <text x={0} y={fs * 2.2} fontSize={fs * 0.7} textAnchor="middle" fill="#16201a">N</text>
      </g>
      <g transform={`translate(0 ${H + pad * 0.55})`}>
        {[0, 1].map((i) => <rect key={i} x={(i * step) / 2} y={0} width={step / 2} height={fs / 3} fill={i ? "#fff" : "#16201a"} stroke="#16201a" strokeWidth={fs / 20} />)}
        <text x={0} y={fs * 1.1} fontSize={fs * 0.55} fill="#16201a">0</text>
        <text x={step} y={fs * 1.1} fontSize={fs * 0.55} textAnchor="end" fill="#16201a">{`${step.toLocaleString()} m`}</text>
      </g>
    </svg>
  );
}
