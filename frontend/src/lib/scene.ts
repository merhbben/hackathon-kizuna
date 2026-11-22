/** Scene model shared with the backend (app/engines/scene.py): local metres, x east, y north. */
export type XY = [number, number];
export type SceneParcel = { id: number; label: string; zone?: string; crop: string; polygon: XY[]; area_m2: number; locked: boolean; rainfed?: boolean; production_kg?: number | null; water_m3?: number | null; planting?: string; harvest?: string };
export type Scene = {
  format: "agrosphere.scene"; version: number; units: "m";
  origin: { utm_zone: string; easting: number; northing: number; location_quality: string };
  boundary: XY[];
  zones: { kind: string; label: string; polygon: XY[] }[];
  lines: { kind: string; label: string; line: XY[] }[];
  sources: { id: number; kind: string; name: string; code?: string; xy: XY; flow_m3h: number | null; daily_volume_m3: number | null; depth_m?: number | null; pump_kw?: number | null }[];
  entrance?: XY;
  edges?: number[];
  parcels: SceneParcel[];
  pipes: { parcel_id: number; line: XY[] }[];
  infrastructure: XY[][];
  fallow?: XY[][];
  meta: Record<string, any>;
};

export const ZONE_COLORS: Record<string, string> = {
  reservoir: "#7cc4ff", solar: "#7b8fd1", building: "#7a8a80", cold_storage: "#5b6b61", orchard: "#6b8e23",
  exclusion: "#e8b4a8", obstacle: "#9aa5a0", path: "#c9c3b5", slope: "#b4675a",
};

export function bounds(s: Scene) {
  const xs = s.boundary.map((p) => p[0]), ys = s.boundary.map((p) => p[1]);
  return { minX: Math.min(...xs), minY: Math.min(...ys), maxX: Math.max(...xs), maxY: Math.max(...ys) };
}

export function polygonArea(pts: XY[]): number {
  let a = 0;
  for (let i = 0; i < pts.length; i++) { const [x1, y1] = pts[i], [x2, y2] = pts[(i + 1) % pts.length]; a += x1 * y2 - x2 * y1; }
  return Math.abs(a) / 2;
}

export function pointInPolygon([x, y]: XY, pts: XY[]): boolean {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i], [xj, yj] = pts[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export function parcelAt(s: Scene, p: XY): SceneParcel | null {
  return s.parcels.find((q) => pointInPolygon(p, q.polygon)) || null;
}

/** Serialise for "Enregistrer" (.agrosphere.json) — stable key order so files diff cleanly. */
export function serialize(s: Scene): string {
  return JSON.stringify(s, null, 1);
}

/** Re-open a saved plan file; throws a translated error code on invalid input. */
export function parseScene(text: string): Scene {
  let s: any;
  try { s = JSON.parse(text); } catch { throw new Error("scene_not_json"); }
  if (!s || s.format !== "agrosphere.scene") throw new Error("not_a_scene");
  if (typeof s.version !== "number" || s.version > 1) throw new Error("scene_version_unsupported");
  if (!Array.isArray(s.boundary) || s.boundary.length < 3) throw new Error("scene_boundary_invalid");
  for (const p of s.parcels || []) if (!Array.isArray(p.polygon) || p.polygon.length < 3) throw new Error("scene_parcel_invalid");
  return { zones: [], lines: [], sources: [], parcels: [], pipes: [], infrastructure: [], meta: {}, ...s } as Scene;
}

/** Sum of parcel areas computed from geometry (used to check area conservation). */
export function parcelsArea(s: Scene): number {
  return s.parcels.reduce((a, p) => a + polygonArea(p.polygon), 0);
}
