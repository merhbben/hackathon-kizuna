/**
 * Interactive 2D farm plan editor (Phaser 3 embedded in React).
 * Real polygons in metres (scene model), not a coloured image: zoom (wheel / pinch / buttons),
 * pan (drag), click to select a parcel, proposed pipes, water points, zones; PNG snapshot export.
 * React -> Phaser: props (scene, colors, selected). Phaser -> React: onSelect callback.
 */
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import type { Scene, XY } from "../lib/scene";
import { bounds, ZONE_COLORS } from "../lib/scene";

export type EditorHandle = { fit: () => void; zoom: (f: number) => void; snapshot: () => Promise<string | null> };
type Props = { scene: Scene; colors: Record<string, string>; labels: Record<string, string>; zoneLabels?: Record<string, string>; fallowLabel?: string; rainfedLabel?: string; entranceLabel?: string; showDims?: boolean; selected: number | null; onSelect: (id: number | null) => void; height?: number; showPipes?: boolean };

const hex = (c: string) => parseInt(c.replace("#", ""), 16);

export const FarmEditor2D = forwardRef<EditorHandle, Props>(function FarmEditor2D(props, ref) {
  const host = useRef<HTMLDivElement>(null);
  const game = useRef<any>(null);
  const sceneRef = useRef<any>(null);
  const propsRef = useRef(props);
  propsRef.current = props;

  useEffect(() => {
    let destroyed = false;
    (async () => {
      const Phaser = (await import("phaser")).default;
      if (destroyed || !host.current) return;

      class FarmScene extends Phaser.Scene {
        k = 1; maxY = 0; minX = 0; layer!: Phaser.GameObjects.Container; dragging = false; downAt: { x: number; y: number } | null = null; pinch: number | null = null;
        constructor() { super("farm"); }
        create() {
          sceneRef.current = this;
          this.input.addPointer(1);
          this.input.on("wheel", (p: any, _o: any, _dx: number, dy: number) => this.zoomAt(dy > 0 ? 0.88 : 1.14, p.x, p.y));
          this.input.on("pointerdown", (p: any) => { this.downAt = { x: p.x, y: p.y }; this.dragging = false; });
          this.input.on("pointermove", (p: any) => {
            const ps = [this.input.pointer1, this.input.pointer2].filter((q) => q.isDown);
            if (ps.length === 2) {                                   // pinch zoom on mobile
              const d = Phaser.Math.Distance.Between(ps[0].x, ps[0].y, ps[1].x, ps[1].y);
              if (this.pinch) this.zoomAt(d / this.pinch, (ps[0].x + ps[1].x) / 2, (ps[0].y + ps[1].y) / 2);
              this.pinch = d; this.dragging = true; return;
            }
            if (!p.isDown || !this.downAt) return;
            if (Math.hypot(p.x - this.downAt.x, p.y - this.downAt.y) > 4) this.dragging = true;
            if (this.dragging) { const cam = this.cameras.main; cam.scrollX -= (p.x - p.prevPosition.x) / cam.zoom; cam.scrollY -= (p.y - p.prevPosition.y) / cam.zoom; }
          });
          this.input.on("pointerup", (p: any) => {
            this.pinch = null;
            if (!this.dragging) {
              const w = this.cameras.main.getWorldPoint(p.x, p.y);
              const m: XY = [w.x / this.k + this.minX, this.maxY - w.y / this.k];
              const hit = propsRef.current.scene.parcels.find((q) => inside(m, q.polygon));
              propsRef.current.onSelect(hit ? hit.id : null);
            }
            this.downAt = null; this.dragging = false;
          });
          this.redraw(true);
        }
        toPx = (p: XY) => [(p[0] - this.minX) * this.k, (this.maxY - p[1]) * this.k] as [number, number];
        poly(g: Phaser.GameObjects.Graphics, pts: XY[], fill: number, alpha: number, stroke: number, sw: number) {
          const P = pts.map((q) => { const [x, y] = this.toPx(q); return new Phaser.Math.Vector2(x, y); });
          g.fillStyle(fill, alpha); g.fillPoints(P, true); g.lineStyle(sw, stroke, 1); g.strokePoints(P, true, true);
        }
        dashed(g: Phaser.GameObjects.Graphics, pts: XY[], color: number, w: number) {
          g.lineStyle(w, color, 1);
          for (let i = 0; i + 1 < pts.length; i++) {
            const [x1, y1] = this.toPx(pts[i]), [x2, y2] = this.toPx(pts[i + 1]);
            const L = Math.hypot(x2 - x1, y2 - y1), n = Math.max(1, Math.floor(L / 9));
            for (let k = 0; k < n; k += 2) g.lineBetween(x1 + ((x2 - x1) * k) / n, y1 + ((y2 - y1) * k) / n, x1 + ((x2 - x1) * Math.min(k + 1, n)) / n, y1 + ((y2 - y1) * Math.min(k + 1, n)) / n);
          }
        }
        hatch(g: Phaser.GameObjects.Graphics, pts: XY[]) {
          const P = pts.map((q) => this.toPx(q)); const xs = P.map((q) => q[0]), ys = P.map((q) => q[1]);
          const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
          g.lineStyle(1, 0xd9ddd5, 1);
          for (let d = x0 - (y1 - y0); d < x1; d += 18) {
            // clip each diagonal against the polygon by sampling (cheap and robust for display)
            let prev: [number, number] | null = null;
            for (let t = 0; t <= 1.0001; t += 0.02) {
              const x = d + t * (y1 - y0), y = y1 - t * (y1 - y0);
              const m: XY = [x / this.k + this.minX, this.maxY - y / this.k];
              if (inside(m, pts)) { if (prev) g.lineBetween(prev[0], prev[1], x, y); prev = [x, y]; } else prev = null;
            }
          }
        }
        redraw(fit = false) {
          const { scene: s, colors, labels, selected, showPipes = true, zoneLabels = {}, fallowLabel = "", rainfedLabel = "", entranceLabel = "", showDims = true } = propsRef.current;
          const b = bounds(s);
          this.k = 1000 / Math.max(b.maxX - b.minX, b.maxY - b.minY, 1); this.minX = b.minX; this.maxY = b.maxY;
          this.layer?.destroy();
          this.layer = this.add.container(0, 0);
          const g = this.add.graphics(); this.layer.add(g);
          this.poly(g, s.boundary, 0xf3f8f2, 1, 0x1f7a3d, 4);
          for (const z of s.zones) this.poly(g, z.polygon, hex(ZONE_COLORS[z.kind] || "#9aa5a0"), 0.85, 0x5b6b61, 1);
          for (const r of s.fallow || []) { this.poly(g, r, 0xf1f3ef, 1, 0xdfe3dc, 1); this.hatch(g, r); }
          for (const r of s.infrastructure) this.poly(g, r, 0xead9b0, 0.55, 0xead9b0, 0.5);
          // parcels of the same crop form one zone (A, B ...): its sectors share the colour and get a fine
          // outline of that colour, the whole zone is highlighted when one of its sectors is selected
          const selZone = s.parcels.find((q) => q.id === selected)?.zone;
          const zoneOf = (p: { zone?: string; label: string }) => p.zone || p.label;
          for (const p of s.parcels) {
            const c = hex(colors[p.crop] || "#7a8a80");
            const inZone = selZone != null && zoneOf(p) === selZone;
            this.poly(g, p.polygon, c, p.id === selected ? 0.98 : inZone ? 0.92 : 0.8, p.id === selected ? 0x16201a : inZone ? 0x3b4a40 : darken(c), p.id === selected ? 3 : inZone ? 1.6 : 0.8);
          }
          for (const l of s.lines) if (l.kind === "path") { g.lineStyle(5, 0xc9c3b5, 1); const P = l.line.map((q) => this.toPx(q)); for (let i = 0; i + 1 < P.length; i++) g.lineBetween(P[i][0], P[i][1], P[i + 1][0], P[i + 1][1]); }
          if (showPipes) {
            // main pipe (source -> corridor -> along the corridor) drawn once per source, short laterals faint
            const trunks = new Set<string>();
            for (const pp of s.pipes) {
              const L = pp.line; if (L.length < 2) continue;
              const trunk = L.length > 2 ? L.slice(0, L.length - 1) : L;
              for (let i = 0; i + 1 < trunk.length; i++) {
                const key = [trunk[i], trunk[i + 1]].map((q) => q.map((v) => Math.round(v)).join(",")).join(";");
                if (trunks.has(key)) continue; trunks.add(key);
                const [x1, y1] = this.toPx(trunk[i]), [x2, y2] = this.toPx(trunk[i + 1]);
                g.lineStyle(2.5, 0x1c6fb8, 0.9); g.lineBetween(x1, y1, x2, y2);
              }
              if (L.length > 2) { const [x1, y1] = this.toPx(L[L.length - 2]), [x2, y2] = this.toPx(L[L.length - 1]); g.lineStyle(1, 0x1c6fb8, 0.45); g.lineBetween(x1, y1, x2, y2); }
            }
          }
          for (const w of s.sources) { const [x, y] = this.toPx(w.xy); g.fillStyle(0xffffff, 1); g.fillCircle(x, y, 11); g.fillStyle(0x1c6fb8, 1); g.fillCircle(x, y, 8); }
          const font = { fontFamily: "Inter, 'Noto Kufi Arabic', sans-serif", fontSize: "15px", color: "#16201a", backgroundColor: "rgba(255,255,255,0.9)", padding: { x: 6, y: 3 } } as any;
          // one label per zone (crop group), on its largest piece, with the zone's total area
          const zones = new Map<string, { crop: string; rainfed?: boolean; m2: number; ids: Set<number>; big: XY[]; bigA: number }>();
          for (const p of s.parcels) {
            const z = zoneOf(p); const a = polyArea(p.polygon);
            const e = zones.get(z) || { crop: p.crop, rainfed: p.rainfed, m2: 0, ids: new Set<number>(), big: p.polygon, bigA: -1 };
            if (!e.ids.has(p.id)) { e.ids.add(p.id); e.m2 += p.area_m2; }
            if (a > e.bigA) { e.big = p.polygon; e.bigA = a; }
            zones.set(z, e);
          }
          for (const [z, e] of zones) {
            const [x, y] = this.toPx(labelPoint(e.big));
            const P = e.big.map((q) => this.toPx(q)); const bw = Math.max(...P.map((q) => q[0])) - Math.min(...P.map((q) => q[0])), bh = Math.max(...P.map((q) => q[1])) - Math.min(...P.map((q) => q[1]));
            const ha = `${(e.m2 / 1e4).toLocaleString(undefined, { maximumFractionDigits: e.m2 > 1e5 ? 1 : 2 })} ha`;
            const name = (labels[e.crop] || e.crop) + (e.rainfed && rainfedLabel ? ` (${rainfedLabel})` : "");
            const fits = Math.min(bw, bh) > 40 && Math.max(bw, bh) > Math.max(name.length + 4, 9) * 7;
            const t = this.add.text(x, y, fits ? `${z} · ${name}\n${ha}` : z, { ...font, fontSize: fits ? "14px" : "13px", align: "center", fontStyle: "bold" }).setOrigin(0.5);
            this.layer.add(t);
          }
          // uncultivated land: one label, on its largest piece
          const fl = (s.fallow || []).reduce<XY[] | null>((b, r) => (!b || polyArea(r) > polyArea(b) ? r : b), null);
          if (fl && fallowLabel) { const [x, y] = this.toPx(labelPoint(fl)); this.layer.add(this.add.text(x, y, fallowLabel, { ...font, color: "#6b766e", fontSize: "12px", fontStyle: "italic", backgroundColor: "rgba(241,243,239,0.92)" }).setOrigin(0.5)); }
          for (const w of s.sources) {
            const [x, y] = this.toPx(w.xy);
            const nm = w.code && w.name && w.name !== w.code ? `${w.code} · ${w.name}` : (w.code || w.name || w.kind);
            this.layer.add(this.add.text(x + 14, y - 22, nm + (w.pump_kw ? `
⚡ ${w.pump_kw} kW` : ""), { ...font, color: "#134c7f", fontStyle: "bold" }));
          }
          if (s.entrance) {
            const [x, y] = this.toPx(s.entrance);
            g.fillStyle(0x16201a, 1); g.fillTriangle(x - 9, y + 8, x + 9, y + 8, x, y - 10);
            if (entranceLabel) this.layer.add(this.add.text(x + 12, y - 4, entranceLabel, { ...font, fontSize: "12px" }));
          }
          if (showDims && s.edges) {
            const n = s.boundary.length;
            for (let i = 0; i < n; i++) {
              const a = this.toPx(s.boundary[i]), b = this.toPx(s.boundary[(i + 1) % n]);
              const L = Math.hypot(b[0] - a[0], b[1] - a[1]); if (L < 60) continue;
              let ang = Math.atan2(b[1] - a[1], b[0] - a[0]); if (ang > Math.PI / 2) ang -= Math.PI; if (ang < -Math.PI / 2) ang += Math.PI;
              const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
              const t = this.add.text(mx, my, `${s.edges[i].toLocaleString(undefined, { maximumFractionDigits: 1 })} m`, { ...font, fontSize: "12px", color: "#1f7a3d", backgroundColor: "rgba(255,255,255,0.9)" }).setOrigin(0.5).setRotation(ang);
              this.layer.add(t);
            }
          }
          for (const z of s.zones) { const [x, y] = this.toPx(centroid(z.polygon)); this.layer.add(this.add.text(x, y, zoneLabels[z.kind] || z.label || z.kind, { ...font, fontSize: "12px" }).setOrigin(0.5)); }
          if (fit) this.fit();
        }
        fit() {
          const cam = this.cameras.main; const b = bounds(propsRef.current.scene);
          const w = (b.maxX - b.minX) * this.k, h = (b.maxY - b.minY) * this.k;
          const z = Math.min(cam.width / (w * 1.1), cam.height / (h * 1.1));
          cam.setZoom(z); cam.centerOn(w / 2, h / 2);
        }
        zoomAt(f: number, sx: number, sy: number) {
          const cam = this.cameras.main; const before = cam.getWorldPoint(sx, sy);
          cam.setZoom(Phaser.Math.Clamp(cam.zoom * f, 0.05, 40));
          const after = cam.getWorldPoint(sx, sy); cam.scrollX += before.x - after.x; cam.scrollY += before.y - after.y;
        }
      }

      game.current = new Phaser.Game({
        type: Phaser.AUTO, parent: host.current, backgroundColor: "#eef3ef", transparent: false,
        scale: { mode: Phaser.Scale.RESIZE, width: host.current.clientWidth, height: props.height || 560 },
        scene: FarmScene, render: { antialias: true, preserveDrawingBuffer: true }, banner: false,
      });
    })();
    return () => { destroyed = true; game.current?.destroy(true); game.current = null; sceneRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // React -> Phaser: redraw when data/selection changes (keep camera unless the plan changed)
  const lastPlan = useRef<any>(null);
  useEffect(() => {
    const sc = sceneRef.current; if (!sc) return;
    const planKey = `${props.scene.meta?.plan_id}-${props.scene.boundary.length}`;
    sc.redraw(lastPlan.current !== planKey); lastPlan.current = planKey;
  }, [props.scene, props.colors, props.labels, props.selected, props.showPipes, props.showDims, props.entranceLabel]);

  useImperativeHandle(ref, () => ({
    fit: () => sceneRef.current?.fit(),
    zoom: (f: number) => { const sc = sceneRef.current; if (sc) sc.zoomAt(f, sc.cameras.main.width / 2, sc.cameras.main.height / 2); },
    snapshot: () => new Promise((resolve) => {
      const g = game.current; if (!g) return resolve(null);
      g.renderer.snapshot((img: HTMLImageElement) => resolve(img?.src || null));
    }),
  }), []);

  return <div ref={host} style={{ height: props.height || 560 }} className="w-full touch-none overflow-hidden rounded-xl2 border border-brand-100" dir="ltr" aria-label="plan 2D" />;
});

/** Same hue, darker: fine outline between sectors of one zone. */
function darken(c: number, f = 0.72): number {
  const r = ((c >> 16) & 255) * f, g = ((c >> 8) & 255) * f, b = (c & 255) * f;
  return (Math.round(r) << 16) | (Math.round(g) << 8) | Math.round(b);
}

/** A point well inside the polygon (centroid when inside, else the middle of the widest horizontal chord). */
function labelPoint(pts: XY[]): XY {
  const c = centroid(pts);
  if (inside(c, pts)) return c;
  const ys = pts.map((q) => q[1]); const y0 = Math.min(...ys), y1 = Math.max(...ys);
  let best: XY = c, bestW = -1;
  for (let k = 1; k < 20; k++) {
    const y = y0 + ((y1 - y0) * k) / 20; const xs: number[] = [];
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      const [xi, yi] = pts[i], [xj, yj] = pts[j];
      if ((yi > y) !== (yj > y)) xs.push(xi + ((y - yi) * (xj - xi)) / (yj - yi));
    }
    xs.sort((a, b) => a - b);
    for (let i = 0; i + 1 < xs.length; i += 2) if (xs[i + 1] - xs[i] > bestW) { bestW = xs[i + 1] - xs[i]; best = [(xs[i] + xs[i + 1]) / 2, y]; }
  }
  return best;
}

function polyArea(pts: XY[]): number {
  let a = 0;
  for (let i = 0; i < pts.length; i++) { const [x1, y1] = pts[i], [x2, y2] = pts[(i + 1) % pts.length]; a += x1 * y2 - x2 * y1; }
  return Math.abs(a) / 2;
}

function centroid(pts: XY[]): XY {
  let a = 0, cx = 0, cy = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x1, y1] = pts[i], [x2, y2] = pts[(i + 1) % pts.length]; const c = x1 * y2 - x2 * y1;
    a += c; cx += (x1 + x2) * c; cy += (y1 + y2) * c;
  }
  if (Math.abs(a) < 1e-9) return pts[0];
  return [cx / (3 * a), cy / (3 * a)];
}

function inside([x, y]: XY, pts: XY[]) {
  let r = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i], [xj, yj] = pts[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) r = !r;
  }
  return r;
}
