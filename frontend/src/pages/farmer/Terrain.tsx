import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../../lib/api";
import { useFarm } from "../../lib/farm";
import { num } from "../../lib/format";
import { useNames } from "../../lib/reference";
import { FarmMap } from "../../components/Maps";
import { PlanEditor } from "../../components/PlanEditor";
import { Badge, Card, ErrorBox, Field, Loader, Note, Quality, Tabs } from "../../components/ui";


export default function Terrain() {
  const { t } = useTranslation();
  const { farms, farm, loading, select, setFarm } = useFarm();
  const nav = useNavigate();
  if (loading && !farm) return <Loader />;
  // a farm is created from its outline (map or plan) in "Mon plan agricole": no surface or place typed by hand
  if (!farm) return <Navigate to="/farm/plan" replace />;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">{t("terrain.title")}</h1>
          <p className="text-sm text-ink-500">{t("terrain.subtitle")}</p>
        </div>
        <div className="flex items-center gap-2">
          {farms.length > 1 && <select className="input !w-56" value={farm.id} onChange={(e) => select(Number(e.target.value))}>{farms.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select>}
          <button className="btn-ghost" onClick={() => nav("/farm/plan", { state: { newFarm: true } })}>+ {t("terrain.newFarm")}</button>
        </div>
      </div>
      <Checklist />
      <BoundaryStep />
      <p className="text-sm font-semibold text-ink-500">{t("terrain.optionalSteps")}</p>
      <div className="grid gap-5 lg:grid-cols-2">
        <WaterStep />
        <EquipmentStep />
      </div>
      <Note>{t("terrain.autoClimateSoil")}</Note>
    </div>
  );
}

function Checklist() {
  const { t } = useTranslation();
  const { farm, setPlan, reloadFarms } = useFarm();
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  const items = [
    { ok: !!farm.boundary, label: t("terrain.ckBoundary"), required: true },
    { ok: farm.area_validated, label: t("terrain.ckArea"), required: true },
    { ok: farm.water_sources.length > 0, label: t("terrain.ckWater"), required: false },
  ];
  const ready = farm.boundary && farm.area_validated;
  const run = async () => {
    setBusy(true); setErr(null);
    try { const p = await api(`/api/farms/${farm.id}/plans`, { method: "POST" }); setPlan(p); await reloadFarms(); nav("/farm/plan"); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3">
        <ul className="flex flex-1 flex-wrap gap-2">
          {items.map((i) => (
            <li key={i.label} className={`chip !px-3 !py-1.5 !text-xs ${i.ok ? "bg-brand-100 text-brand-800" : i.required ? "bg-danger-50 text-danger-700" : "bg-slate-100 text-slate-600"}`}>
              {i.ok ? "✓" : i.required ? "•" : "○"} {i.label}{!i.required && !i.ok ? ` (${t("terrain.optional")})` : ""}
            </li>
          ))}
        </ul>
        <button className="btn-primary" disabled={!ready || busy} onClick={run}>{busy ? t("plan.computing") : `${t("terrain.goPlan")} →`}</button>
      </div>
      {!ready && <p className="mt-2 text-xs text-ink-500">{t("terrain.needValidation")}</p>}
      {ready && !farm.water_sources.length && <div className="mt-2"><Note tone="sun">{t("terrain.noWaterHint")}</Note></div>}
      {busy && <Loader label={t("plan.computingLong")} />}
      <div className="mt-2"><ErrorBox error={err} /></div>
    </Card>
  );
}

function BoundaryStep() {
  const { t } = useTranslation();
  const { gov } = useNames();
  const { farm, setFarm } = useFarm();
  const [how, setHow] = useState<"draw" | "upload">(farm.plan_upload?.kind === "raster" ? "upload" : "draw");
  const [draft, setDraft] = useState<any>(farm.boundary);
  const [check, setCheck] = useState<any>(null);
  const [err, setErr] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [outline, setOutline] = useState<number[][]>(farm.plan_upload?.boundary_px || farm.plan_upload?.detection?.boundary_px || []);
  const [areaHa, setAreaHa] = useState<string>(farm.declared_area_ha ? String(farm.declared_area_ha) : "");
  const [rotation, setRotation] = useState("0");
  const [placing, setPlacing] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [controls, setControls] = useState<{ px: number[]; lat?: number; lon?: number }[]>([]);
  useEffect(() => { setDraft(farm.boundary); setCheck(null); }, [farm.id]);
  const pending = controls.findIndex((c) => c.lat === undefined);

  const upload = async (file: File) => {
    setErr(null); setBusy(true);
    try {
      const form = new FormData(); form.append("file", file);
      const r = await api(`/api/farms/${farm.id}/plan-upload`, { method: "POST", form });
      setFarm({ ...farm, plan_upload: r });
      if (r.kind === "geo") { setDraft(r.boundary); setCheck(r.area_check); }
      else { setOutline(r.detection.boundary_px); setControls([]); setPlacing(true); }
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const georef = async (body: any) => {
    setErr(null); setBusy(true);
    try {
      const r = await api(`/api/farms/${farm.id}/georeference`, { method: "POST", json: { boundary_px: outline, ...body } });
      setFarm({ ...farm, plan_upload: r }); setDraft(r.boundary); setCheck(r.area_check); setPlacing(false);
      await save(false, r.boundary);   // immediate area + governorate check, without confirming yet
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const placeAt = (lat: number, lon: number) => {
    if (!areaHa || Number(areaHa) <= 0) { setErr({ message: "area_required" }); return; }
    georef({ area_ha: Number(areaHa), anchor_lat: lat, anchor_lon: lon, rotation_deg: Number(rotation) || 0 });
  };
  const georefControls = () => georef({ control_points: controls.filter((c) => c.lat !== undefined).map((c) => ({ px: c.px, lat: c.lat, lon: c.lon })) });
  const save = async (confirm: boolean, boundary?: any) => {
    setErr(null); setBusy(true);
    try {
      const excl = farm.plan_upload?.exclusions?.length ? { type: "GeometryCollection", geometries: farm.plan_upload.exclusions } : farm.exclusions;
      const r = await api(`/api/farms/${farm.id}/boundary`, { method: "PUT", json: { boundary: boundary || draft, exclusions: excl || null, confirm_area: confirm } });
      setFarm(r.farm); setCheck(r.area_check);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const switchGov = async () => {
    setBusy(true); setErr(null);
    try {
      const f2 = await api(`/api/farms/${farm.id}`, { method: "PATCH", json: { governorate_code: check.governorate_detected } });
      setFarm(f2);
      const r = await api(`/api/farms/${farm.id}/boundary`, { method: "PUT", json: { boundary: draft, exclusions: f2.exclusions || null, confirm_area: false } });
      setFarm(r.farm); setCheck(r.area_check);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const det = farm.plan_upload?.kind === "raster" ? farm.plan_upload.detection : null;
  const mapMode = how === "draw" ? "boundary" : (placing && !advanced) || (advanced && pending >= 0) ? "point" : "none";
  const measured = check?.measured_ha ?? farm.measured_area_ha;
  return (
    <Card title={<span>1 · {t("terrain.stepBoundary")}</span>} subtitle={t("terrain.stepBoundarySub")}
      action={<Tabs value={how} onChange={setHow} items={[{ id: "draw", label: t("terrain.draw") }, { id: "upload", label: t("terrain.upload") }]} />}>
      <div className={`grid gap-4 ${how === "upload" && det ? "lg:grid-cols-2" : ""}`}>
        {how === "upload" && (
          <div className="space-y-3">
            <Field label={t("terrain.uploadLabel")} hint={t("terrain.uploadHint")}>
              <input type="file" className="input" accept=".png,.jpg,.jpeg,.tif,.tiff,.webp,.pdf,.geojson,.json,.kml,.gpkg,.zip" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} disabled={busy} />
            </Field>
            {busy && <Loader label={t("terrain.analysing")} />}
            {det && (
              <>
                <PlanEditor farmId={farm.id} detection={det} outline={outline} setOutline={setOutline} allowControl={advanced}
                  controlPx={controls.map((c) => c.px)} pendingIndex={pending >= 0 ? pending : null}
                  onPickControl={(px) => { if (pending >= 0) return; setControls([...controls, { px }]); }} />
                {!advanced ? (
                  <div className="rounded-xl bg-water-50 p-3 text-sm">
                    <p className="font-semibold text-water-700">{t("terrain.simpleTitle")}</p>
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      <Field label={t("terrain.realArea")} hint={t("terrain.realAreaHint")}><input className="input" type="number" step="any" min="0" value={areaHa} onChange={(e) => setAreaHa(e.target.value)} /></Field>
                      <Field label={t("terrain.rotation")} hint={t("terrain.rotationHint")}><input className="input" type="number" value={rotation} onChange={(e) => setRotation(e.target.value)} /></Field>
                    </div>
                    <button className={`mt-2 w-full ${placing ? "btn-water" : "btn-ghost"}`} onClick={() => setPlacing(true)} disabled={busy}>
                      {placing ? `👉 ${t("terrain.clickCenter")}` : t("terrain.placeAgain")}
                    </button>
                    <button className="mt-2 text-xs font-semibold text-water-700 underline" onClick={() => { setAdvanced(true); setPlacing(false); }}>{t("terrain.advanced")}</button>
                  </div>
                ) : (
                  <div className="rounded-xl bg-water-50 p-3 text-sm">
                    <p className="font-semibold text-water-700">{t("terrain.georefTitle")}</p>
                    <p className="mt-1 text-xs text-water-700">{pending >= 0 ? t("terrain.clickMapFor", { n: pending + 1 }) : t("terrain.georefHelp")}</p>
                    <ul className="mt-2 space-y-1 text-xs">{controls.map((c, i) => <li key={i} className="flex items-center gap-2"><Badge tone="water">{i + 1}</Badge>px {c.px.join(", ")} → {c.lat !== undefined ? `${c.lat.toFixed(6)}, ${c.lon!.toFixed(6)}` : "…"}<button className="ms-auto text-danger-700" onClick={() => setControls(controls.filter((_, k) => k !== i))}>✕</button></li>)}</ul>
                    <button className="btn-water mt-2 w-full" disabled={busy || controls.filter((c) => c.lat !== undefined).length < 2} onClick={georefControls}>{t("terrain.georef")}</button>
                    {farm.plan_upload?.residuals_m?.length > 0 && <p className="mt-1 text-[11px] text-water-700">{t("terrain.residuals")} : {farm.plan_upload.residuals_m.join(" / ")} m</p>}
                    <button className="mt-2 text-xs font-semibold text-water-700 underline" onClick={() => { setAdvanced(false); setControls([]); }}>{t("terrain.simpleMode")}</button>
                  </div>
                )}
              </>
            )}
          </div>
        )}
        <div>
          <FarmMap boundary={draft} sources={farm.water_sources} height={how === "upload" && det ? 520 : 460}
            center={farm.latitude ? [farm.latitude, farm.longitude] : undefined} governorate={farm.governorate_code}
            drawMode={mapMode} onBoundaryChange={(g) => { setDraft(g); setCheck(null); }}
            onPoint={(lat, lon) => {
              if (advanced) { if (pending >= 0) setControls(controls.map((c, i) => (i === pending ? { ...c, lat, lon } : c))); }
              else if (placing) placeAt(lat, lon);
            }} />
          {how === "draw" && <p className="mt-2 text-xs text-ink-500">{t("terrain.drawHelp")}</p>}
        </div>
      </div>
      {draft && (
        <div className="mt-4 rounded-xl border border-brand-100 bg-brand-50/50 p-3">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              {measured ? <span>{t("terrain.measured")} : <b>{num(measured, 3)} ha</b></span> : <span>{t("terrain.notChecked")}</span>}
              {farm.declared_area_ha && <span className="text-ink-500">/ {t("terrain.declared")} {num(farm.declared_area_ha, 2)} ha</span>}
              {check?.deviation_pct !== null && check?.deviation_pct !== undefined && <Badge tone={check.ok ? "brand" : "sun"}>{check.deviation_pct > 0 ? "+" : ""}{check.deviation_pct} %</Badge>}
              {farm.area_validated && <Badge>✓ {t("terrain.validated")}</Badge>}
            </div>
            <div className="ms-auto flex gap-2">
              {!check && <button className="btn-ghost" disabled={busy} onClick={() => save(false)}>{t("terrain.checkArea")}</button>}
              <button className="btn-primary" disabled={busy || check?.governorate_matches === false} onClick={() => save(true)}>
                {check && !check.ok && !farm.area_validated ? t("terrain.confirmMeasured", { ha: num(check.measured_ha, 2) }) : t("terrain.confirmArea")}
              </button>
            </div>
          </div>
          {check && check.governorate_matches === false && (
            <div className="mt-2 flex flex-wrap items-center gap-2 rounded-xl border border-danger-500/30 bg-danger-50 p-3 text-sm text-danger-700">
              <span>{check.governorate_detected ? t("terrain.inOtherGov", { chosen: gov(farm.governorate_code), found: gov(check.governorate_detected) }) : t("terrain.outsideTunisia")}</span>
              {check.governorate_detected && <button className="btn-ghost !py-1.5 ms-auto" disabled={busy} onClick={switchGov}>{t("terrain.useGov", { gov: gov(check.governorate_detected) })}</button>}
            </div>
          )}
          {check && !check.ok && !farm.area_validated && check.governorate_matches !== false && <div className="mt-2"><Note tone="sun">{t("terrain.areaMismatch")}</Note></div>}
          {check?.declared_updated && <div className="mt-2"><Note>{t("terrain.declaredUpdated")}</Note></div>}
          {check?.soil_autofilled && <div className="mt-2"><Note>{t("terrain.soilAutofilled")}</Note></div>}
        </div>
      )}
      <ErrorBox error={err} />
    </Card>
  );
}

function WaterStep() {
  const { t } = useTranslation();
  const { farm, setFarm } = useFarm();
  const empty = { kind: "borehole", name: "", flow_m3h: "", max_hours_per_day: "12", pumping_depth_m: "", salinity_ds_m: "", annual_quota_m3: "", latitude: null as number | null, longitude: null as number | null, authorized: true };
  const [s, setS] = useState<any>(empty);
  const [picking, setPicking] = useState(false);
  const [err, setErr] = useState<any>(null);
  const add = async () => {
    setErr(null);
    try {
      const body = { ...s, flow_m3h: Number(s.flow_m3h), max_hours_per_day: Number(s.max_hours_per_day), pumping_depth_m: Number(s.pumping_depth_m || 0),
        salinity_ds_m: s.salinity_ds_m ? Number(s.salinity_ds_m) : null, annual_quota_m3: s.annual_quota_m3 ? Number(s.annual_quota_m3) : null, name: s.name || null };
      setFarm(await api(`/api/farms/${farm.id}/water-sources`, { method: "POST", json: body })); setS(empty);
    } catch (e) { setErr(e); }
  };
  const del = async (id: number) => { await api(`/api/farms/${farm.id}/water-sources/${id}`, { method: "DELETE" }); setFarm(await api(`/api/farms/${farm.id}`)); };
  const wells = farm.plan_upload?.wells || [];
  return (
    <Card title={<span>2 · {t("terrain.stepWater")}</span>} subtitle={t("terrain.stepWaterSub")}>
      {farm.water_sources.length > 0 && (
        <ul className="mb-4 space-y-2">{farm.water_sources.map((w: any) => (
          <li key={w.id} className="flex items-center gap-3 rounded-xl bg-water-50 p-3 text-sm">
            <span className="text-lg" aria-hidden>💧</span>
            <div className="flex-1"><b>{t(`source.${w.kind}`)}</b> {w.name} · {w.flow_m3h} m³/h · {w.max_hours_per_day} h/{t("units.day")}{w.pumping_depth_m ? ` · ${w.pumping_depth_m} m` : ""}{w.salinity_ds_m ? ` · ${w.salinity_ds_m} dS/m` : ""}
              {!w.authorized && <Badge tone="danger">{t("terrain.notAuthorized")}</Badge>}</div>
            <button className="text-danger-700" onClick={() => del(w.id)} aria-label={t("common.delete")}>✕</button>
          </li>))}</ul>
      )}
      {wells.length > 0 && !farm.water_sources.length && <Note>{t("terrain.wellsDetected", { n: wells.length })}</Note>}
      <div className="grid grid-cols-2 gap-3">
        <Field label={t("terrain.sourceKind")}><select className="input" value={s.kind} onChange={(e) => setS({ ...s, kind: e.target.value })}>{["borehole", "well", "reservoir", "dam_network", "canal"].map((k) => <option key={k} value={k}>{t(`source.${k}`)}</option>)}</select></Field>
        <Field label={t("terrain.flow")}><input className="input" type="number" min="0" step="any" value={s.flow_m3h} onChange={(e) => setS({ ...s, flow_m3h: e.target.value })} /></Field>
        <Field label={t("terrain.hours")}><input className="input" type="number" min="1" max="24" value={s.max_hours_per_day} onChange={(e) => setS({ ...s, max_hours_per_day: e.target.value })} /></Field>
        <Field label={t("terrain.depth")}><input className="input" type="number" min="0" value={s.pumping_depth_m} onChange={(e) => setS({ ...s, pumping_depth_m: e.target.value })} /></Field>
        <Field label={t("terrain.salinity")} hint="dS/m"><input className="input" type="number" min="0" step="0.1" value={s.salinity_ds_m} onChange={(e) => setS({ ...s, salinity_ds_m: e.target.value })} /></Field>
        <Field label={t("terrain.quota")} hint="m³/an"><input className="input" type="number" min="0" value={s.annual_quota_m3} onChange={(e) => setS({ ...s, annual_quota_m3: e.target.value })} /></Field>
        <label className="col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={s.authorized} onChange={(e) => setS({ ...s, authorized: e.target.checked })} className="accent-brand-600" />{t("terrain.authorized")}</label>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button className="btn-ghost" onClick={() => setPicking(!picking)}>{s.latitude ? `📍 ${s.latitude.toFixed(5)}, ${s.longitude.toFixed(5)}` : t("terrain.pickOnMap")}</button>
        {wells.map((w: any, i: number) => <button key={i} className="btn-ghost !py-1.5 text-xs" onClick={() => setS({ ...s, kind: w.kind === "well" ? "well" : s.kind, latitude: w.latitude, longitude: w.longitude })}>{t("terrain.useDetected")} {i + 1}</button>)}
        <button className="btn-water ms-auto" disabled={!s.flow_m3h || s.latitude === null} onClick={add}>{t("common.add")}</button>
      </div>
      {picking && <div className="mt-3"><FarmMap boundary={farm.boundary} sources={farm.water_sources} height={300} drawMode="point" onPoint={(lat, lng) => { setS({ ...s, latitude: lat, longitude: lng }); setPicking(false); }} /></div>}
      <ErrorBox error={err} />
    </Card>
  );
}

function EquipmentStep() {
  const { t } = useTranslation();
  const { farm, setFarm } = useFarm();
  const [kind, setKind] = useState("pump");
  const [specs, setSpecs] = useState<Record<string, string>>({});
  const FIELDS: Record<string, [string, string][]> = {
    pump: [["power_kw", "kW"], ["efficiency", "0–1"]], pv: [["kwp", "kWc"]], battery: [["kwh", "kWh"]],
    grid: [["voltage", "BT / MT"], ["contract_kva", "kVA"]], cold_room: [["volume_m3", "m³"], ["temperature_c", "°C"]],
  };
  const add = async () => {
    const s = Object.fromEntries(Object.entries(specs).filter(([, v]) => v !== "").map(([k, v]) => [k, isNaN(Number(v)) ? v : Number(v)]));
    setFarm(await api(`/api/farms/${farm.id}/equipment`, { method: "POST", json: { kind, specs: s } })); setSpecs({});
  };
  const del = async (id: number) => { await api(`/api/farms/${farm.id}/equipment/${id}`, { method: "DELETE" }); setFarm(await api(`/api/farms/${farm.id}`)); };
  return (
    <Card title={<span>3 · {t("terrain.stepEquipment")}</span>} subtitle={t("terrain.stepEquipmentSub")}>
      {farm.equipment.length > 0 && <ul className="mb-3 flex flex-wrap gap-2">{farm.equipment.map((e: any) => <li key={e.id} className="chip bg-sun-100 text-sun-600 !text-xs">{t(`equipment.${e.kind}`)} · {Object.entries(e.specs).map(([k, v]) => `${v}`).join(" · ")}<button onClick={() => del(e.id)} className="ms-1">✕</button></li>)}</ul>}
      <div className="grid grid-cols-3 gap-3">
        <Field label={t("terrain.equipmentKind")}><select className="input" value={kind} onChange={(e) => { setKind(e.target.value); setSpecs({}); }}>{Object.keys(FIELDS).map((k) => <option key={k} value={k}>{t(`equipment.${k}`)}</option>)}</select></Field>
        {FIELDS[kind].map(([k, hint]) => <Field key={k} label={t(`equipmentField.${k}`)} hint={hint}><input className="input" value={specs[k] || ""} onChange={(e) => setSpecs({ ...specs, [k]: e.target.value })} /></Field>)}
      </div>
      <button className="btn-ghost mt-3" onClick={add}>{t("common.add")}</button>
    </Card>
  );
}
