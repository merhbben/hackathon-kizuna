import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";

/** Shows the uploaded 2D plan with the outline detected by OpenCV. The farmer drags vertices to correct it,
 *  double-clicks an edge to add a vertex, right-clicks a vertex to remove it, and places control points. */
export function PlanEditor({ farmId, detection, outline, setOutline, controlPx, onPickControl, pendingIndex, allowControl = true }: {
  farmId: number; detection: any; outline: number[][]; setOutline: (o: number[][]) => void; allowControl?: boolean;
  controlPx: number[][]; onPickControl: (px: number[]) => void; pendingIndex: number | null;
}) {
  const { t } = useTranslation();
  const [src, setSrc] = useState<string | null>(null);
  const [drag, setDrag] = useState<number | null>(null);
  const [mode, setMode] = useState<"edit" | "control">("edit");
  useEffect(() => { if (!allowControl) setMode("edit"); }, [allowControl]);
  const svgRef = useRef<SVGSVGElement>(null);
  const [w, h] = detection.image_size;

  useEffect(() => {
    let url: string | null = null;
    api<Blob>(`/api/farms/${farmId}/plan-upload/image`).then((b) => { url = URL.createObjectURL(b); setSrc(url); }).catch(() => setSrc(null));
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [farmId, detection]);

  const toPx = (e: React.MouseEvent | MouseEvent) => {
    const r = svgRef.current!.getBoundingClientRect();
    return [((e.clientX - r.left) / r.width) * w, ((e.clientY - r.top) / r.height) * h];
  };
  const onMove = (e: React.MouseEvent) => {
    if (drag === null) return;
    const p = toPx(e);
    setOutline(outline.map((q, i) => (i === drag ? p : q)));
  };
  const onClick = (e: React.MouseEvent) => { if (mode === "control") onPickControl(toPx(e).map((v) => Math.round(v))); };
  const addVertex = (e: React.MouseEvent) => {
    const p = toPx(e);
    let best = 0, bd = Infinity;
    outline.forEach((a, i) => {
      const b = outline[(i + 1) % outline.length];
      const d = distToSeg(p, a, b);
      if (d < bd) { bd = d; best = i; }
    });
    const n = [...outline]; n.splice(best + 1, 0, p); setOutline(n);
  };
  const r = Math.max(w, h) / 120;
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <button className={mode === "edit" ? "btn-primary !py-1.5" : "btn-ghost !py-1.5"} onClick={() => setMode("edit")}>{t("terrain.editOutline")}</button>
        {allowControl && <button className={mode === "control" ? "btn-water !py-1.5" : "btn-ghost !py-1.5"} onClick={() => setMode("control")}>{t("terrain.placeControl")}</button>}
        <span className="text-xs text-ink-500">{t("terrain.confidence")} : {Math.round(detection.confidence * 100)} %</span>
      </div>
      <div className="relative overflow-hidden rounded-xl border border-brand-100 bg-slate-50" dir="ltr">
        {src ? <img src={src} alt={t("terrain.planAlt")} className="block w-full select-none" draggable={false} /> : <div style={{ aspectRatio: `${w}/${h}` }} />}
        <svg ref={svgRef} viewBox={`0 0 ${w} ${h}`} className={`absolute inset-0 h-full w-full ${mode === "control" ? "cursor-crosshair" : ""}`}
          onMouseMove={onMove} onMouseUp={() => setDrag(null)} onMouseLeave={() => setDrag(null)} onClick={onClick} onDoubleClick={mode === "edit" ? addVertex : undefined}>
          <polygon points={outline.map((p) => p.join(",")).join(" ")} fill="rgba(47,158,68,.18)" stroke="#1f7a3d" strokeWidth={r / 2} />
          {detection.features.filter((f: any) => f.type === "path").map((f: any, i: number) => <line key={i} x1={f.line[0][0]} y1={f.line[0][1]} x2={f.line[1][0]} y2={f.line[1][1]} stroke="#c98a06" strokeWidth={r / 3} strokeDasharray={`${r} ${r}`} />)}
          {detection.features.filter((f: any) => f.type === "well").map((f: any, i: number) => <circle key={i} cx={f.point[0]} cy={f.point[1]} r={r} fill="#1c6fb8" stroke="#fff" strokeWidth={r / 4} />)}
          {detection.features.filter((f: any) => f.type === "building" || f.type === "water").map((f: any, i: number) => <polygon key={i} points={f.polygon.map((p: number[]) => p.join(",")).join(" ")} fill={f.type === "water" ? "rgba(28,111,184,.35)" : "rgba(91,107,97,.45)"} />)}
          {mode === "edit" && outline.map((p, i) => (
            <circle key={i} cx={p[0]} cy={p[1]} r={r} fill="#fff" stroke="#1f7a3d" strokeWidth={r / 3} className="cursor-move"
              onMouseDown={(e) => { e.stopPropagation(); setDrag(i); }}
              onContextMenu={(e) => { e.preventDefault(); if (outline.length > 3) setOutline(outline.filter((_, k) => k !== i)); }} />
          ))}
          {controlPx.map((p, i) => (
            <g key={i}><circle cx={p[0]} cy={p[1]} r={r * 1.2} fill={pendingIndex === i ? "#f6b93b" : "#1c6fb8"} stroke="#fff" strokeWidth={r / 3} />
              <text x={p[0] + r * 1.6} y={p[1] + r / 2} fontSize={r * 2} fontWeight={700} fill="#134c7f">{i + 1}</text></g>
          ))}
        </svg>
      </div>
      <p className="mt-2 text-xs text-ink-500">{mode === "edit" ? t("terrain.editHelp") : t("terrain.controlHelp")}</p>
    </div>
  );
}

function distToSeg(p: number[], a: number[], b: number[]) {
  const [x, y] = p, [x1, y1] = a, [x2, y2] = b;
  const dx = x2 - x1, dy = y2 - y1;
  const tt = Math.max(0, Math.min(1, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(x - (x1 + tt * dx), y - (y1 + tt * dy));
}
