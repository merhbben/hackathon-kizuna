import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";
import { FarmMap } from "../../components/Maps";
import { api, download } from "../../lib/api";
import { useFarm } from "../../lib/farm";
import { area, date, mass, num } from "../../lib/format";
import { useNames } from "../../lib/reference";
import { parseScene, serialize, ZONE_COLORS, type Scene, type XY } from "../../lib/scene";
import { FarmEditor2D, type EditorHandle } from "../../components/FarmEditor2D";
import { InputPlan } from "../../components/InputPlan";
import { Pipeline } from "../../components/Pipeline";
import { AllocationTable, CalendarTable, ClimateCard, ColdBuildingCard, EnergyTable, IrrigationTable, ResultsTable } from "../../components/PlanTables";
import { Badge, Card, ErrorBox, Field, Loader, Note, Quality } from "../../components/ui";

const ZONE_KINDS = ["reservoir", "solar", "building", "cold_storage", "orchard", "exclusion", "obstacle", "path", "slope"];

/** Mon plan agricole — model input (left) → AgroBrain → optimised plan (right), tables A–E below. */
export default function MyPlan() {
  const { farm, plan, loading, setFarm, setPlan, reloadFarms, select } = useFarm();
  const loc = useLocation();
  const [starting, setStarting] = useState(!!(loc.state as any)?.newFarm);
  if (loading && !farm) return <Loader />;
  if (!farm || starting || !farm.boundary) {
    return <StartPlan onCancel={farm?.boundary ? () => setStarting(false) : undefined}
      onDone={async (f, p) => { setFarm(f); setPlan(p); setStarting(false); await reloadFarms(); select(f.id); }} />;
  }
  return <Workspace key={`${farm.id}`} onNew={() => setStarting(true)} hasPlan={!!plan} />;
}

// ------------------------------------------------------------------ start
function StartPlan({ onDone, onCancel }: { onDone: (farm: any, plan: any | null) => void; onCancel?: () => void }) {
  const { t } = useTranslation();
  const { govs, lang } = useNames();
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  const [need, setNeed] = useState<any>(null);
  const [corr, setCorr] = useState<any>({ governorate_code: "", latitude: "", longitude: "", edge_index: 0, edge_length_m: "" });
  const [drawing, setDrawing] = useState(false);
  const send = async (f: File, c: any = {}) => {
    setBusy(true); setErr(null);
    try {
      const form = new FormData(); form.append("file", f); form.append("corrections", JSON.stringify(c));
      const r = await api("/api/farms/import", { method: "POST", form });
      if (r.status === "needs_input" && !r.farm) { setNeed(r); return; }
      onDone(r.farm, r.plan || null);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const resend = () => {
    if (!file) return;
    const c: any = {};
    if (corr.governorate_code) c.governorate_code = corr.governorate_code;
    if (corr.latitude !== "" && corr.longitude !== "") { c.latitude = Number(corr.latitude); c.longitude = Number(corr.longitude); }
    if (corr.edge_length_m !== "") { c.edge_index = Number(corr.edge_index); c.edge_length_m = Number(corr.edge_length_m); }
    send(file, c);
  };
  const pick = (f?: File) => { if (f) { setFile(f); setNeed(null); send(f); } };
  const missing: string[] = need?.missing || [];
  const nEdges = need?.boundary_units?.length || 0;
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div className="text-center">
        <h1 className="text-2xl font-bold">{t("p2.startTitle")}</h1>
        <p className="mt-1 text-sm text-ink-500">{t("p2.startSub")}</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <label className={`flex h-full cursor-pointer flex-col items-center justify-center gap-2 rounded-xl2 border-2 border-dashed p-8 text-center transition ${file ? "border-brand-500 bg-brand-50" : "border-brand-200 hover:bg-brand-50/60"}`}
            onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); pick(e.dataTransfer.files?.[0]); }}>
            <span className="text-4xl" aria-hidden>📐</span>
            <span className="font-semibold">{file ? file.name : t("p2.importPlan")}</span>
            <span className="text-xs text-ink-500">PNG · JPG · PDF · SVG</span>
            <input type="file" className="sr-only" accept=".png,.jpg,.jpeg,.pdf,.svg,.tif,.tiff,.webp" disabled={busy} onChange={(e) => pick(e.target.files?.[0])} />
          </label>
        </Card>
        <Card>
          <button type="button" onClick={() => setDrawing(true)} className={`flex h-full w-full flex-col items-center justify-center gap-2 rounded-xl2 border-2 border-dashed p-8 text-center transition ${drawing ? "border-water-500 bg-water-50" : "border-water-300 hover:bg-water-50"}`}>
            <span className="text-4xl" aria-hidden>🗺️</span>
            <span className="font-semibold">{t("p2.drawOnMap")}</span>
            <span className="text-xs text-ink-500">{t("p2.drawOnMapSub")}</span>
          </button>
        </Card>
      </div>
      {drawing && <DrawOnMap onDone={(f) => onDone(f, null)} onCancel={() => setDrawing(false)} />}
      {busy && <Card><Loader label={t("imp.working")} /><ol className="ms-10 list-decimal text-xs text-ink-500">{["read", "understand", "verify", "optimise", "compute"].map((k) => <li key={k}>{t(`imp.step_${k}`)}</li>)}</ol></Card>}
      <ErrorBox error={err} />
      {need && (
        <Card title={t("p2.needTitle")} subtitle={t("p2.needSub")}>
          <div className="grid gap-3 sm:grid-cols-2">
            {missing.includes("location") && <>
              <Field label={t("farm.governorate")}><select className="input" value={corr.governorate_code} onChange={(e) => setCorr({ ...corr, governorate_code: e.target.value })}><option value="">—</option>{Object.entries(govs).map(([k, v]) => <option key={k} value={k}>{v[lang]}</option>)}</select></Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label={t("imp.lat")} hint={t("p2.optional")}><input className="input" type="number" step="any" value={corr.latitude} onChange={(e) => setCorr({ ...corr, latitude: e.target.value })} /></Field>
                <Field label={t("imp.lon")} hint={t("p2.optional")}><input className="input" type="number" step="any" value={corr.longitude} onChange={(e) => setCorr({ ...corr, longitude: e.target.value })} /></Field>
              </div>
            </>}
            {missing.includes("edge_length") && <>
              <p className="text-sm sm:col-span-2">{t("p2.needEdge")}</p>
              <Field label={t("p2.side")}><select className="input" value={corr.edge_index} onChange={(e) => setCorr({ ...corr, edge_index: e.target.value })}>
                {Array.from({ length: nEdges }, (_, i) => { const L = need.vertex_labels || []; return <option key={i} value={i}>{L[i] && L[(i + 1) % nEdges] ? `${L[i]} → ${L[(i + 1) % nEdges]}` : `${t("p2.side")} ${i + 1}`}</option>; })}
              </select></Field>
              <Field label={t("p2.sideLength")}><input className="input" type="number" min="0" step="any" value={corr.edge_length_m} onChange={(e) => setCorr({ ...corr, edge_length_m: e.target.value })} /></Field>
              {nEdges > 0 && <div className="sm:col-span-2"><EdgePreview pts={need.boundary_units} sel={Number(corr.edge_index)} /></div>}
            </>}
          </div>
          <button className="btn-primary mt-3" disabled={busy || (missing.includes("location") && !corr.governorate_code && corr.latitude === "") || (missing.includes("edge_length") && corr.edge_length_m === "")} onClick={resend}>{t("imp.continue")}</button>
        </Card>
      )}
      <Note>{t("p2.noWeatherInput")}</Note>
      {onCancel && <button className="btn-ghost" onClick={onCancel}>{t("common.cancel")}</button>}
    </div>
  );
}

/** Outline drawn on the satellite map: governorate, GPS and area come from the geometry (nothing typed). */
function DrawOnMap({ onDone, onCancel }: { onDone: (farm: any) => void; onCancel: () => void }) {
  const { t } = useTranslation();
  const { govs, lang } = useNames();
  const [zoomGov, setZoomGov] = useState("");
  const [shape, setShape] = useState<any>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  const save = async () => {
    setBusy(true); setErr(null);
    try { const r = await api("/api/farms/from-map", { method: "POST", json: { boundary: shape, name: name || null } }); onDone(r.farm); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <Card title={t("p2.drawTitle")} subtitle={t("p2.drawSub")}>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <Field label={t("p2.goTo")} hint={t("p2.goToHint")}>
          <select className="input !w-56" value={zoomGov} onChange={(e) => setZoomGov(e.target.value)}><option value="">—</option>{Object.entries(govs).map(([k, v]) => <option key={k} value={k}>{v[lang]}</option>)}</select>
        </Field>
        <Field label={t("p2.farmName")} hint={t("p2.optional")}><input className="input !w-64" value={name} onChange={(e) => setName(e.target.value)} /></Field>
      </div>
      <FarmMap key={zoomGov} governorate={zoomGov || undefined} drawMode="boundary" onBoundaryChange={setShape} height={480} />
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button className="btn-primary" disabled={!shape || busy} onClick={save}>{busy ? t("plan.computing") : `✓ ${t("p2.validateOutline")}`}</button>
        <button className="btn-ghost" onClick={onCancel}>{t("common.cancel")}</button>
        <span className="text-xs text-ink-500">{shape ? t("p2.outlineReady") : t("p2.drawHelp")}</span>
      </div>
      <div className="mt-2"><ErrorBox error={err} /></div>
    </Card>
  );
}

function EdgePreview({ pts, sel }: { pts: number[][]; sel: number }) {
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs), y0 = Math.min(...ys), w = Math.max(...xs) - x0 || 1, h = Math.max(...ys) - y0 || 1;
  const P = (p: number[]) => `${p[0] - x0},${p[1] - y0}`;
  const a = pts[sel % pts.length], b = pts[(sel + 1) % pts.length];
  return (
    <svg viewBox={`${-w * 0.05} ${-h * 0.05} ${w * 1.1} ${h * 1.1}`} className="h-40 w-full rounded-xl bg-brand-50" style={{ direction: "ltr" }}>
      <polygon points={pts.map(P).join(" ")} fill="#eef6ec" stroke="#1f7a3d" strokeWidth={Math.max(w, h) / 200} />
      {a && b && <line x1={a[0] - x0} y1={a[1] - y0} x2={b[0] - x0} y2={b[1] - y0} stroke="#1c6fb8" strokeWidth={Math.max(w, h) / 60} strokeLinecap="round" />}
    </svg>
  );
}

// -------------------------------------------------------------- workspace
type Draft = {
  latitude: string; longitude: string; governorate_code: string; delegation: string;
  edge_index: number; edge_length_m: string;
  entrance: XY | null;
  sources: { kind: string; name: string; xy: XY | null; flow_m3h: string; depth_m: string; daily_volume_m3: string; annual_quota_m3: string; pump_kw: string; authorized: boolean }[];
  grid: string; grid_tariff_tnd_kwh: string; pv_kwc: string; battery_kwh: string; irrigation_method: string;
  cold_rooms: { volume_m3: string; floor_m2: string; label?: string }[];
};
const s0 = (v: any) => (v === null || v === undefined ? "" : String(v));

function draftFrom(inputs: any, scene: Scene | null): Draft {
  const T = inputs.terrain, E = inputs.energy;
  return {
    latitude: T.location_quality === "user" || T.location_quality === "plan_gps" ? s0(T.latitude) : "", longitude: T.location_quality === "user" || T.location_quality === "plan_gps" ? s0(T.longitude) : "",
    governorate_code: T.governorate_code || "", delegation: T.delegation || "", edge_index: 0, edge_length_m: "",
    entrance: scene?.entrance || null,
    sources: inputs.water.map((w: any) => ({ kind: w.kind, name: w.name || w.code, xy: scene?.sources.find((s) => s.id === w.id)?.xy || null,
      flow_m3h: s0(w.flow_m3h), depth_m: s0(w.depth_m), daily_volume_m3: s0(w.daily_volume_m3), annual_quota_m3: s0(w.annual_quota_m3), pump_kw: s0(w.pump_kw), authorized: w.authorized })),
    grid: E.grid, grid_tariff_tnd_kwh: s0(E.grid_tariff_tnd_kwh), pv_kwc: s0(E.pv_kwc), battery_kwh: s0(E.battery_kwh), irrigation_method: E.irrigation_method || "drip",
    cold_rooms: E.cold_rooms.map((c: any) => ({ volume_m3: s0(c.volume_m3), floor_m2: s0(c.floor_m2), label: c.label })),
  };
}

function bodyFrom(d: Draft, edgeChanged: boolean) {
  const num_ = (v: string) => (v === "" ? null : Number(v));
  const b: any = {
    delegation: d.delegation, grid: d.grid, grid_tariff_tnd_kwh: num_(d.grid_tariff_tnd_kwh), pv_kwc: num_(d.pv_kwc), battery_kwh: num_(d.battery_kwh),
    irrigation_method: d.irrigation_method, confirm_area: true,
    sources: d.sources.filter((s) => s.xy).map((s) => ({ kind: s.kind, name: s.name || null, x_m: s.xy![0], y_m: s.xy![1], flow_m3h: num_(s.flow_m3h), depth_m: num_(s.depth_m),
      daily_volume_m3: num_(s.daily_volume_m3), annual_quota_m3: num_(s.annual_quota_m3), pump_kw: num_(s.pump_kw), authorized: s.authorized })),
    cold_rooms: d.cold_rooms.filter((c) => c.volume_m3 !== "" || c.floor_m2 !== "").map((c) => ({ volume_m3: num_(c.volume_m3), floor_m2: num_(c.floor_m2), label: c.label })),
  };
  if (d.governorate_code) b.governorate_code = d.governorate_code;
  if (d.latitude !== "" && d.longitude !== "") { b.latitude = Number(d.latitude); b.longitude = Number(d.longitude); }
  if (edgeChanged && d.edge_length_m !== "") { b.edge_index = d.edge_index; b.edge_length_m = Number(d.edge_length_m); }
  if (d.entrance) b.entrance = { x_m: d.entrance[0], y_m: d.entrance[1] };
  return b;
}

function Workspace({ onNew, hasPlan }: { onNew: () => void; hasPlan: boolean }) {
  const { t, i18n } = useTranslation();
  const { farm, plan, setFarm, setPlan, reloadFarms } = useFarm();
  const { crop, color, crops, gov } = useNames();
  const [inputs, setInputs] = useState<any>(null);
  const [terrain, setTerrain] = useState<Scene | null>(null);
  const [scene, setScene] = useState<Scene | null>(null);
  const [opened, setOpened] = useState<Scene | null>(null);
  const [rep, setRep] = useState<any>(null);
  const [clim, setClim] = useState<any>(null);
  const [climErr, setClimErr] = useState<any>(null);
  const [editing, setEditing] = useState(!hasPlan && !farm.plans?.length);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [pick, setPick] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  const [planErr, setPlanErr] = useState<any>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [pipes, setPipes] = useState(true);
  const [recomputing, setRecomputing] = useState(false);
  const tried = useRef<number | null>(null);
  const editor = useRef<EditorHandle>(null);
  const lang = i18n.language === "ar" ? "ar" : "fr";

  const loadInputs = useCallback(async () => {
    const [inp, sc] = await Promise.all([api(`/api/farms/${farm.id}/inputs`), api<Scene>(`/api/farms/${farm.id}/scene`)]);
    setInputs(inp); setTerrain(sc); setDraft(draftFrom(inp, sc));
  }, [farm.id]);
  useEffect(() => { loadInputs().catch(setErr); }, [loadInputs, farm]);
  useEffect(() => {
    if (!plan) { setScene(null); setRep(null); return; }
    Promise.all([api<Scene>(`/api/farms/${farm.id}/plans/${plan.id}/scene`), api(`/api/farms/${farm.id}/plans/${plan.id}/report`)])
      .then(([sc, r]) => { setScene(sc); setRep(r); }).catch(setErr);
  }, [farm.id, plan?.id]);
  useEffect(() => { setClim(null); setClimErr(null); api(`/api/farms/${farm.id}/climate`).then(setClim).catch(setClimErr); }, [farm.id, farm.latitude, farm.longitude]);

  // the terrain or its resources changed since this plan was computed: recompute it automatically
  useEffect(() => {
    if (!plan?.stale || tried.current === plan.id) return;
    tried.current = plan.id; setRecomputing(true); setErr(null);
    api(`/api/farms/${farm.id}/plans`, { method: "POST" })
      .then((p) => { setPlan(p); reloadFarms(); })
      .catch((e) => setErr(e))
      .finally(() => setRecomputing(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan?.id, plan?.stale]);
  // placing an entrance or a borehole: bring the input plan into view so the click target is visible
  useEffect(() => { if (pick) document.getElementById("input-plan")?.scrollIntoView({ behavior: "smooth", block: "center" }); }, [pick]);
  const colors = useMemo(() => Object.fromEntries(Object.keys(crops).map((c) => [c, color(c)])), [crops, color]);
  const labels = useMemo(() => Object.fromEntries(Object.keys(crops).map((c) => [c, crop(c)])), [crops, crop]);
  const zoneLabels = useMemo(() => Object.fromEntries(ZONE_KINDS.map((k) => [k, t(`zone.${k}`)])), [t]);
  const shown = opened || scene;
  const viewScene = useMemo(() => shown && ({ ...shown, parcels: shown.parcels.map((p) => ({ ...p, crop: edits[p.id] || p.crop })) }), [shown, edits]);
  const selParcel = plan?.parcels.find((p: any) => p.id === sel);
  const selZone: string | undefined = selParcel ? (selParcel.metrics?.zone || selParcel.label) : undefined;

  const submit = async () => {
    if (!draft) return;
    setBusy(true); setErr(null); setPlanErr(null);
    try {
      const r = await api(`/api/farms/${farm.id}/inputs`, { method: "PUT", json: bodyFrom(draft, draft.edge_length_m !== "") });
      setFarm(r.farm); setInputs(r.inputs);
      if (r.plan) { setPlan(r.plan); setEditing(false); setSel(null); setEdits({}); }
      setPlanErr(r.plan_error);
      await reloadFarms();
    } catch (e) { setErr(e); } finally { setBusy(false); setPick(null); }
  };
  const replan = async () => {
    setBusy(true); setErr(null);
    try {
      const p = await api(`/api/farms/${farm.id}/plans/${plan.id}/replan`, { method: "POST", json: { edits: Object.entries(edits).map(([id, c]) => ({ parcel_id: Number(id), crop_code: c })) } });
      setPlan(p); setEdits({}); setSel(null); reloadFarms();
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const exportPNG = async () => {
    const url = await editor.current?.snapshot(); if (!url) return;
    const a = document.createElement("a"); a.href = url; a.download = `plan_${plan.id}.png`; a.click();
  };
  const onPick = (xy: XY) => {
    if (!draft || !pick) return;
    if (pick === "entrance") setDraft({ ...draft, entrance: xy });
    else { const i = Number(pick); const sources = draft.sources.map((s, k) => (k === i ? { ...s, xy } : s)); setDraft({ ...draft, sources }); }
    setPick(null);
  };
  const missing: string[] = inputs?.missing || [];
  const T = inputs?.terrain;
  const s = plan?.summary;

  return (
    <div className="space-y-5">
      {/* header */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">{t("plan.title")}</h1>
          <p className="text-sm text-ink-500">{farm.name}{plan ? ` · ${t("plan.version", { v: plan.version, date: date(plan.created_at) })}` : ""}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className={editing ? "btn-primary" : "btn-ghost"} onClick={() => setEditing(!editing)}>✏️ {t("p2.editData")}</button>
          <button className="btn-ghost" onClick={onNew}>📐 {t("imp.newPlan")}</button>
        </div>
      </div>
      {missing.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl2 border border-sun-300/60 bg-sun-100/60 px-4 py-2 text-sm">
          <span className="font-semibold text-sun-600">⚠ {t("p2.missingTitle")} :</span>
          {missing.map((m) => { const [k, code] = m.split(":"); return <Badge key={m} tone="sun">{t(`p2.miss_${k}`, { code })}</Badge>; })}
          {!editing && <button className="ms-auto text-xs font-semibold underline" onClick={() => setEditing(true)}>{t("p2.complete")}</button>}
        </div>
      )}
      {(inputs?.warnings || []).map((w: any, i: number) => <Note key={i} tone="danger">{String(t(`p2.warn_${w.code}`, { ...w, declared: w.declared_kw, needed: w.needed_kw }))}</Note>)}
      {recomputing && <Note>{t("pl.recomputing")}</Note>}
      {plan?.stale && !recomputing && <Note tone="sun">{t("pl.stale")}</Note>}
      <ErrorBox error={err} />
      {plan?.summary?.pipeline && !plan.stale && <Pipeline pl={plan.summary.pipeline} summary={plan.summary} />}
      {planErr && <Note tone="sun">{t(`errors.${planErr.code}`, { defaultValue: t("imp.planBlocked") })}</Note>}

      {/* two panels: model input | model output */}
      <div className="grid gap-5 xl:grid-cols-2 [&>*]:min-w-0">
        <Card title={<span className="flex items-center gap-2"><Badge tone="slate">{t("p2.input")}</Badge>{t("p2.inputTitle")}</span>} subtitle={pick ? t(pick === "entrance" ? "p2.clickEntrance" : "p2.clickSource", { code: `F${Number(pick) + 1}` }) : t("p2.inputSub")}>
          {terrain && draft ? (<div id="input-plan">
            <InputPlan scene={terrain} zoneLabels={zoneLabels} entranceLabel={t("p2.entrance")} pick={pick} onPick={onPick}
              sourcesOverride={draft.sources.map((w, i) => ({ code: `F${i + 1}`, xy: w.xy, pump_kw: w.pump_kw ? Number(w.pump_kw) : null }))}
              entranceOverride={draft.entrance} /></div>
          ) : <Loader />}
          {T && (
            <dl className="mt-3 grid grid-cols-2 gap-x-5 gap-y-1 text-sm sm:grid-cols-3">
              <Fact k={t("p2.area")} v={`${num(T.area_ha, 3)} ha`} q={T.area_validated ? "measured" : "missing"} />
              <Fact k={t("p2.perimeter")} v={terrain?.edges ? `${num(terrain.edges.reduce((a, b) => a + b, 0))} m · ${terrain.edges.length} ${t("p2.sides")}` : "—"} />
              <Fact k={t("p2.location")} v={`${gov(farm.governorate_code)}${farm.delegation ? ` · ${farm.delegation}` : ""}`} q={T.location_quality === "governorate_centroid" ? "estimated" : undefined} />
              <Fact k="GPS" v={T.location_quality === "governorate_centroid" || T.latitude == null ? t("p2.approx") : `${num(T.latitude, 4)}, ${num(T.longitude, 4)}`} q={T.location_quality === "governorate_centroid" ? "missing" : "measured"} />
              <Fact k={t("p2.water")} v={(inputs.water || []).map((w: any) => `${w.code} ${w.flow_m3h ? `${w.flow_m3h} m³/h` : w.daily_volume_m3 ? `${num(w.daily_volume_m3, 1)} m³/${t("units.day")}` : "?"}`).join(" · ") || "—"} />
              <Fact k={t("p2.pumps")} v={(inputs.water || []).filter((w: any) => w.pump_kw).map((w: any) => `${w.code} ${w.pump_kw} kW`).join(" · ") || "—"} />
              <Fact k={t("p2.energyRes")} v={[inputs.energy.grid === "yes" ? t("p2.gridYes") : inputs.energy.grid === "no" ? t("p2.gridNo") : null, inputs.energy.pv_kwc ? `PV ${inputs.energy.pv_kwc} kWc` : null, inputs.energy.battery_kwh ? `${t("p2.battery")} ${inputs.energy.battery_kwh} kWh` : null].filter(Boolean).join(" · ") || "—"} />
              <Fact k={t("p2.irrigTech")} v={t(`method.${inputs.energy.irrigation_method}`)} />
              <Fact k={t("p2.soil")} v={farm.soil?.sand_pct != null ? `${t("p2.sand")} ${num(farm.soil.sand_pct)} % · ${t("p2.clay")} ${num(farm.soil.clay_pct)} %` : farm.soil?.texture ? t(`texture.${farm.soil.texture}`) : "—"} q={farm.soil?.quality === "estimated" ? "estimated" : undefined} />
            </dl>
          )}
          {editing && draft && inputs && <InputsForm draft={draft} setDraft={setDraft} inputs={inputs} pick={pick} setPick={setPick} busy={busy} onSubmit={submit} edges={T?.edges} />}
        </Card>

        <Card title={<span className="flex items-center gap-2"><Badge tone="brand">{t("p2.output")}</Badge>{opened ? t("plan.opened") : t("p2.outputTitle")}</span>} subtitle={t("p2.outputSub")}
          action={viewScene ? <div className="flex flex-wrap gap-1">
            <button className="btn-ghost !px-3 !py-1.5" onClick={() => editor.current?.zoom(1.25)} aria-label="zoom +">＋</button>
            <button className="btn-ghost !px-3 !py-1.5" onClick={() => editor.current?.zoom(0.8)} aria-label="zoom −">－</button>
            <button className="btn-ghost !px-3 !py-1.5" onClick={() => editor.current?.fit()}>{t("plan.fit")}</button>
            <button className={`btn-ghost !px-3 !py-1.5 ${pipes ? "!bg-water-50" : ""}`} onClick={() => setPipes(!pipes)}>{t("plan.pipes")}</button>
          </div> : undefined}>
          {recomputing ? <div className="grid h-[460px] place-items-center"><Loader label={t("pl.recomputing")} /></div> : !plan ? (
            <div className="grid h-[460px] place-items-center rounded-xl2 border border-dashed border-brand-200 text-center text-sm text-ink-500">
              <div><div className="text-4xl">🧠</div><p className="mt-2 max-w-xs">{t("p2.noPlanYet")}</p></div>
            </div>
          ) : viewScene ? (<div id="output-plan">
            <FarmEditor2D ref={editor} scene={viewScene} colors={colors} labels={labels} selected={sel} onSelect={setSel} showPipes={pipes} height={460}
              zoneLabels={zoneLabels} entranceLabel={t("p2.entrance")} rainfedLabel={t("method.rainfed")} fallowLabel={viewScene.meta?.rainfed_only ? t("plan.fallow") : t("plan.fallowWater")} /></div>
          ) : <Loader />}
          {plan && viewScene && (
            <>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {zoneLegend(viewScene).map((z) => <button key={z.zone} onClick={() => setSel(z.first)} className={`chip bg-white !px-2.5 !py-1 !text-xs shadow-sm ring-1 ${selZone === z.zone ? "ring-ink-700" : "ring-brand-100"}`}><span className="h-3 w-3 rounded-sm" style={{ background: color(z.crop) }} /><b>{z.zone}</b> {crop(z.crop)}{z.rainfed ? ` (${t("method.rainfed")})` : ""} · {num(z.m2 / 1e4, z.m2 > 1e5 ? 1 : 2)} ha{z.sectors > 1 ? <span className="text-ink-500">· {t("p2.nSectors", { n: z.sectors })}</span> : null}</button>)}
                <span className="chip bg-water-50 !px-2.5 !py-1 !text-xs text-water-700">● {t("p2.boreholes")}</span>
                <span className="chip bg-water-50 !px-2.5 !py-1 !text-xs text-water-700">- - {t("plan.pipes")}</span>
                {(viewScene.infrastructure.length > 0) && <span className="chip bg-sun-100 !px-2.5 !py-1 !text-xs text-sun-600">▮ {t("plan.infrastructure")}</span>}
                {viewScene.zones.some((z) => z.kind === "cold_storage") && <span className="chip bg-white !px-2.5 !py-1 !text-xs shadow-sm ring-1 ring-brand-100"><span className="h-3 w-3 rounded-sm" style={{ background: ZONE_COLORS.cold_storage }} />❄ {t("cb.legendBuilding")}</span>}
                {viewScene.zones.some((z) => z.kind === "solar") && <span className="chip bg-white !px-2.5 !py-1 !text-xs shadow-sm ring-1 ring-brand-100"><span className="h-3 w-3 rounded-sm" style={{ background: ZONE_COLORS.solar }} />☀ {t("cb.legendPv")}</span>}
              </div>
              {selParcel && !opened && <ParcelDetail p={selParcel} edit={edits[selParcel.id]} onEdit={(c) => setEdits({ ...edits, [selParcel.id]: c })} cropsList={Object.keys(crops)} onClose={() => setSel(null)} />}
              {Object.keys(edits).length > 0 && (
                <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-brand-50 p-3 text-sm">
                  <span>{t("plan.pendingEdits", { n: Object.keys(edits).length })}</span>
                  <button className="btn-primary ms-auto" onClick={replan} disabled={busy}>{busy ? t("plan.computing") : t("plan.recompute")}</button>
                  <button className="btn-ghost" onClick={() => setEdits({})}>{t("common.cancel")}</button>
                </div>
              )}
              <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-brand-50 pt-3">
                <span className="text-xs font-semibold text-ink-500">{t("plan.export")} :</span>
                <button className="btn-ghost !py-1.5" onClick={exportPNG}>PNG</button>
                <button className="btn-ghost !py-1.5" onClick={() => download(`/api/farms/${farm.id}/plans/${plan.id}/export.pdf?lang=${lang}`, `plan_${plan.id}.pdf`)}>PDF</button>
                <button className="btn-ghost !py-1.5" onClick={() => download(`/api/farms/${farm.id}/plans/${plan.id}/export.svg?lang=${lang}`, `plan_${plan.id}.svg`)}>SVG</button>
                <button className="btn-ghost !py-1.5" onClick={() => download(`/api/farms/${farm.id}/plans/${plan.id}/geojson`, `plan_${plan.id}.geojson`)}>GeoJSON</button>
                <button className="btn-ghost !py-1.5" onClick={() => { if (!scene) return; const b = new Blob([serialize(scene)], { type: "application/json" }); const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = `plan_${plan.id}.agrosphere.json`; a.click(); }}>💾 {t("plan.save")}</button>
                <label className="btn-ghost !py-1.5 cursor-pointer">📂 {t("plan.reopen")}<input type="file" accept=".json" className="sr-only" onChange={async (e) => { const f = e.target.files?.[0]; if (!f) return; try { setOpened(parseScene(await f.text())); setSel(null); } catch (x: any) { setErr({ message: t(`errors.${x.message}`, { defaultValue: x.message }) }); } }} /></label>
                {opened && <button className="btn-ghost !py-1.5" onClick={() => setOpened(null)}>{t("plan.backToCurrent")}</button>}
              </div>
            </>
          )}
        </Card>
      </div>

      {/* key figures */}
      {s && rep && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <Kpi label={t("p2.cultivated")} value={`${num(rep.totals.area_ha, 2)} ha`} hint={`${t("p2.of")} ${num(rep.totals.field_ha, 2)} ha${s.unused_area_ha > 0.001 ? ` · ${t("plan.unused")} ${num(s.unused_area_ha, 2)} ha` : ""}`} />
          <Kpi label={t("plan.production")} value={`${num(rep.totals.production_t, 1)} t`} badge={<Quality q="estimated" />} />
          <Kpi label={t("plan.water")} value={`${num(s.water_m3)} m³`} tone="water" />
          <Kpi label={t("p2.pumpKwh")} value={`${num(rep.energy.pump_kwh_total)} kWh`} tone="sun" />
          <Kpi label={t("p2.zonesCount")} value={`${rep.allocation.length}`} hint={rep.totals.sectors > rep.allocation.length ? t("p2.nSectors", { n: rep.totals.sectors }) : `${new Set(rep.allocation.map((a: any) => a.crop)).size} ${t("p2.crops")}`} />
        </div>
      )}
      {s && (s.rainfed_only ? <Note tone="sun">{t("plan.rainfedOnly")}</Note> : s.optimizer.binding.some((b: string) => b.startsWith("water")) && <Note>{t("plan.waterLimited")}</Note>)}

      {rep && (
        <>
          <AllocationTable rep={rep} selected={selZone} onSelect={(z) => { setSel(plan.parcels.find((p: any) => (p.metrics?.zone || p.label) === z)?.id ?? null); document.getElementById("output-plan")?.scrollIntoView({ behavior: "smooth", block: "center" }); }} />
          <IrrigationTable rep={rep} />
          <CalendarTable rep={rep} />
          <div className="grid gap-5 2xl:grid-cols-2 [&>*]:min-w-0">
            <EnergyTable rep={rep} />
            <ResultsTable rep={rep} />
          </div>
          <ColdBuildingCard rep={rep} />
        </>
      )}
      {clim ? <ClimateCard clim={clim} /> : climErr ? <Note tone="sun">{t("p2.climateUnavailable")}</Note> : <Card><Loader label={t("p2.loadingClimate")} /></Card>}
      {s && <p className="text-xs text-ink-500">{t("plan.sources")} : {s.sources.join(" · ")}</p>}
    </div>
  );
}

function Fact({ k, v, q }: { k: string; v: React.ReactNode; q?: string }) {
  return (
    <div className="flex items-start justify-between gap-2 border-b border-brand-50 py-1">
      <dt className="text-ink-500">{k}</dt>
      <dd className="text-end font-semibold">{v} {q === "missing" ? <Badge tone="sun">!</Badge> : q ? <Quality q={q} /> : null}</dd>
    </div>
  );
}

function Kpi({ label, value, hint, badge, tone = "brand" }: { label: string; value: React.ReactNode; hint?: React.ReactNode; badge?: React.ReactNode; tone?: "brand" | "water" | "sun" }) {
  const c = tone === "water" ? "text-water-700" : tone === "sun" ? "text-sun-600" : "text-brand-700";
  return (
    <div className="rounded-xl2 border border-brand-100 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between text-xs text-ink-500">{label}{badge}</div>
      <div className={`mt-1 text-2xl font-bold tabular-nums ${c}`}>{value}</div>
      {hint && <div className="text-[11px] text-ink-500">{hint}</div>}
    </div>
  );
}

// ------------------------------------------------------------ inputs form
function InputsForm({ draft, setDraft, inputs, pick, setPick, busy, onSubmit, edges }: { draft: Draft; setDraft: (d: Draft) => void; inputs: any; pick: string | null; setPick: (p: string | null) => void; busy: boolean; onSubmit: () => void; edges?: any[] }) {
  const { t } = useTranslation();
  const { govs, lang } = useNames();
  const up = (k: keyof Draft, v: any) => setDraft({ ...draft, [k]: v });
  const upS = (i: number, k: string, v: any) => setDraft({ ...draft, sources: draft.sources.map((s, j) => (j === i ? { ...s, [k]: v } : s)) });
  const sec = "rounded-xl border border-brand-100 p-3";
  return (
    <div className="mt-4 space-y-3 border-t border-brand-100 pt-4">
      <p className="text-xs text-ink-500">{t("p2.formHint")}</p>
      {/* A. terrain */}
      <fieldset className={sec}>
        <legend className="px-1 text-sm font-bold">A · {t("p2.fTerrain")}</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          <Field label={t("farm.governorate")}><select className="input" value={draft.governorate_code} onChange={(e) => up("governorate_code", e.target.value)}>{Object.entries(govs).map(([k, v]) => <option key={k} value={k}>{v[lang]}</option>)}</select></Field>
          <Field label={t("p2.delegation")}><input className="input" value={draft.delegation} onChange={(e) => up("delegation", e.target.value)} /></Field>
          <Field label={`GPS — ${t("imp.lat")}`} hint="ex. 35.6781"><input className="input" type="number" step="any" value={draft.latitude} onChange={(e) => up("latitude", e.target.value)} /></Field>
          <Field label={`GPS — ${t("imp.lon")}`} hint="ex. 10.0963"><input className="input" type="number" step="any" value={draft.longitude} onChange={(e) => up("longitude", e.target.value)} /></Field>
          {inputs.terrain.has_plan_file && edges?.length ? <>
            <Field label={t("p2.side")} hint={t("p2.sideHint")}><select className="input" value={draft.edge_index} onChange={(e) => up("edge_index", Number(e.target.value))}>{edges.map((e: any, i: number) => <option key={i} value={i}>{e.from} → {e.to} ({num(e.length_m, 1)} m)</option>)}</select></Field>
            <Field label={t("p2.sideLength")} hint={t("p2.optional")}><input className="input" type="number" min="0" step="any" value={draft.edge_length_m} onChange={(e) => up("edge_length_m", e.target.value)} /></Field>
          </> : null}
          <div className="flex items-center gap-2 sm:col-span-2">
            <button type="button" className={`btn-ghost !py-1.5 ${pick === "entrance" ? "!bg-water-50 ring-1 ring-water-500" : ""}`} onClick={() => setPick(pick === "entrance" ? null : "entrance")}>📍 {t("p2.placeEntrance")}</button>
            {draft.entrance && <span className="text-xs text-ink-500">{num(draft.entrance[0], 1)} m, {num(draft.entrance[1], 1)} m</span>}
          </div>
        </div>
      </fieldset>
      {/* B. water */}
      <fieldset className={sec}>
        <legend className="px-1 text-sm font-bold">B · {t("p2.fWater")}</legend>
        <div className="space-y-2">
          {draft.sources.map((w, i) => (
            <div key={i} className="rounded-lg bg-water-50/60 p-2">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <b className="text-water-700">F{i + 1}</b>
                <select className="input !w-auto !py-1" value={w.kind} onChange={(e) => upS(i, "kind", e.target.value)}>{["borehole", "well", "reservoir", "dam_network", "canal"].map((k) => <option key={k} value={k}>{t(`source.${k}`)}</option>)}</select>
                <input className="input !w-32 !py-1" value={w.name} onChange={(e) => upS(i, "name", e.target.value)} aria-label={t("p2.name")} />
                <button type="button" className={`btn-ghost !px-2 !py-1 text-xs ${pick === String(i) ? "!bg-water-50 ring-1 ring-water-500" : ""}`} onClick={() => setPick(pick === String(i) ? null : String(i))}>📍 {w.xy ? t("p2.move") : t("p2.place")}</button>
                <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={w.authorized} onChange={(e) => upS(i, "authorized", e.target.checked)} />{t("p2.authorized")}</label>
                <button type="button" className="ms-auto text-xs text-danger-600" onClick={() => setDraft({ ...draft, sources: draft.sources.filter((_, j) => j !== i) })}>✕</button>
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                <Mini label={t("p2.flow")} unit="m³/h" v={w.flow_m3h} on={(v) => upS(i, "flow_m3h", v)} />
                <Mini label={t("p2.depth")} unit="m" v={w.depth_m} on={(v) => upS(i, "depth_m", v)} />
                <Mini label={t("p2.pumpPower")} unit="kW" v={w.pump_kw} on={(v) => upS(i, "pump_kw", v)} />
                <Mini label={t("p2.dailyVolume")} unit="m³/j" v={w.daily_volume_m3} on={(v) => upS(i, "daily_volume_m3", v)} />
                <Mini label={t("p2.quota")} unit="m³/an" v={w.annual_quota_m3} on={(v) => upS(i, "annual_quota_m3", v)} />
              </div>
            </div>
          ))}
          <button type="button" className="btn-ghost !py-1.5 text-sm" onClick={() => { setDraft({ ...draft, sources: [...draft.sources, { kind: "borehole", name: `F${draft.sources.length + 1}`, xy: null, flow_m3h: "", depth_m: "", daily_volume_m3: "", annual_quota_m3: "", pump_kw: "", authorized: true }] }); setPick(String(draft.sources.length)); }}>＋ {t("p2.addSource")}</button>
        </div>
      </fieldset>
      {/* C. energy */}
      <fieldset className={sec}>
        <legend className="px-1 text-sm font-bold">C · {t("p2.fEnergy")}</legend>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Field label={t("p2.gridAvail")}><select className="input" value={draft.grid} onChange={(e) => up("grid", e.target.value)}><option value="unknown">{t("p2.unknown")}</option><option value="yes">{t("p2.yes")}</option><option value="no">{t("p2.no")}</option></select></Field>
          <Mini label={t("p2.tariffIn")} unit="TND/kWh" v={draft.grid_tariff_tnd_kwh} on={(v) => up("grid_tariff_tnd_kwh", v)} step="0.001"
            warn={tariffWarn(draft.grid_tariff_tnd_kwh, t)} hint={t("p2.tariffHint")} />
          <Field label={t("p2.irrigTech")}><select className="input" value={draft.irrigation_method} onChange={(e) => up("irrigation_method", e.target.value)}>{["drip", "sprinkler", "surface"].map((m) => <option key={m} value={m}>{t(`method.${m}`)}</option>)}</select></Field>
          <Mini label={t("p2.pvExisting")} unit="kWc" v={draft.pv_kwc} on={(v) => up("pv_kwc", v)} />
          <Mini label={t("p2.batteryExisting")} unit="kWh" v={draft.battery_kwh} on={(v) => up("battery_kwh", v)} />
          <Mini label={t("p2.coldRoom")} unit="m³" v={draft.cold_rooms[0]?.volume_m3 ?? ""} on={(v) => up("cold_rooms", v === "" && !draft.cold_rooms[0]?.floor_m2 ? draft.cold_rooms.slice(1) : [{ ...(draft.cold_rooms[0] || { floor_m2: "" }), volume_m3: v }, ...draft.cold_rooms.slice(1)])} />
        </div>
      </fieldset>
      <div className="flex flex-wrap items-center gap-3">
        <button className="btn-primary" disabled={busy || !!tariffWarn(draft.grid_tariff_tnd_kwh, t)} onClick={onSubmit}>{busy ? t("plan.computing") : `🧠 ${t("p2.compute")}`}</button>
        <span className="text-xs text-ink-500">{t("p2.computeHint")}</span>
      </div>
    </div>
  );
}

function Mini({ label, unit, v, on, step = "any", warn, hint }: { label: string; unit: string; v: string; on: (v: string) => void; step?: string; warn?: string | null; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-0.5 block text-[11px] font-semibold text-ink-500">{label}</span>
      <div className="relative">
        <input className={`input !py-1.5 pe-14 ${warn ? "!border-danger-500" : ""}`} type="number" min="0" step={step} value={v} placeholder={hint ? "0,250" : "?"} onChange={(e) => on(e.target.value)} aria-invalid={!!warn} />
        <span className="pointer-events-none absolute inset-y-0 end-2 flex items-center text-[11px] text-ink-400">{unit}</span>
      </div>
      {warn ? <span className="mt-0.5 block text-[11px] text-danger-700">{warn}</span> : hint ? <span className="mt-0.5 block text-[11px] text-ink-400">{hint}</span> : null}
    </label>
  );
}

/** STEG tariffs are a fraction of a dinar per kWh; a value above 10 is almost certainly in millimes. */
function tariffWarn(v: string, t: (k: string, o?: any) => string): string | null {
  if (v === "") return null;
  const x = Number(v);
  if (!(x > 0)) return t("p2.tariffPositive");
  if (x > 10) return t("p2.tariffMillimes", { v: x, tnd: (x / 1000).toLocaleString(undefined, { maximumFractionDigits: 3 }) });
  return null;
}

// ---------------------------------------------------------- parcel detail
/** One legend entry per zone (crop group): total area, number of sectors, first sector (to select it). */
function zoneLegend(sc: Scene) {
  const m = new Map<string, { zone: string; crop: string; rainfed?: boolean; m2: number; ids: Set<number>; first: number; sectors: number }>();
  for (const p of sc.parcels) {
    const z = p.zone || p.label;
    const e = m.get(z) || { zone: z, crop: p.crop, rainfed: p.rainfed, m2: 0, ids: new Set<number>(), first: p.id, sectors: 0 };
    if (!e.ids.has(p.id)) { e.ids.add(p.id); e.m2 += p.area_m2; e.sectors += 1; }
    m.set(z, e);
  }
  return Array.from(m.values()).sort((a, b) => a.zone.length - b.zone.length || a.zone.localeCompare(b.zone));
}

function ParcelDetail({ p, edit, onEdit, cropsList, onClose }: { p: any; edit?: string; onEdit: (c: string) => void; cropsList: string[]; onClose: () => void }) {
  const { t } = useTranslation();
  const { crop, color } = useNames();
  const m = p.metrics;
  const rows: [string, React.ReactNode][] = [
    [t("common.area"), `${area(p.area_m2)} (${num(m.area_ha, 3)} ha)`],
    [t("plan.estimatedProd"), <span key="p">{mass(m.production_kg)} <span className="text-xs text-ink-500">({num(m.yield_kg_ha)} kg/ha)</span></span>],
    [t("plan.waterNeed"), `${num(m.water_m3_season)} m³`],
    [t("plan.energyNeed"), `${num(m.energy_kwh_season)} kWh`],
    [t("p2.distance"), m.distance_m != null ? `${num(m.distance_m)} m${m.source_name ? ` · ${m.source_name}` : ""}` : "—"],
    [t("plan.planting"), date(m.planting)], [t("plan.harvest"), date(m.harvest)],
  ];
  return (
    <div className="mt-3 rounded-xl border border-brand-100 p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="h-4 w-4 rounded" style={{ background: color(edit || p.crop) }} />
        <b>{t("p2.zone")} {p.label} · {crop(edit || p.crop)}</b>
        {p.locked && <Badge tone="water">🔒 {t("plan.locked")}</Badge>}
        <button className="ms-auto text-ink-400" onClick={onClose} aria-label="close">✕</button>
      </div>
      <dl className="grid gap-x-5 text-sm sm:grid-cols-2">
        {rows.map(([k, v]) => <div key={k} className="flex justify-between gap-3 border-b border-brand-50 py-1"><dt className="text-ink-500">{k}</dt><dd className="text-end font-semibold">{v}</dd></div>)}
      </dl>
      {m.why?.length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 ps-4 text-xs text-ink-700">{m.why.map((w: any, i: number) => <li key={i}>{String(t(`why.${w.key}`, { ...w.data, quality: w.data?.quality ? t(`quality.${String(w.data.quality).startsWith("official") ? "official" : String(w.data.quality).startsWith("estimated") ? "estimated" : w.data.quality}`, { defaultValue: w.data.quality }) : "" }))}</li>)}</ul>
      )}
      <label className="mt-2 block">
        <span className="label">{t("plan.changeCrop")}</span>
        <select className="input" value={edit || p.crop} onChange={(e) => onEdit(e.target.value)}>{cropsList.map((c) => <option key={c} value={c}>{crop(c)}</option>)}</select>
      </label>
    </div>
  );
}
