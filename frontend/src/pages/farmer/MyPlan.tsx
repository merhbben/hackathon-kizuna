import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import { useFarm } from "../../lib/farm";
import { area, date, mass, num } from "../../lib/format";
import { useNames } from "../../lib/reference";
import { FarmMap } from "../../components/Maps";
import { Badge, Card, Empty, ErrorBox, Loader, Note, Quality, Stat } from "../../components/ui";

export default function MyPlan() {
  const { t } = useTranslation();
  const { farm, plan, setPlan, reloadFarms, loading } = useFarm();
  const { crop, color, crops } = useNames();
  const [sel, setSel] = useState<any>(null);
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  const legend = useMemo(() => {
    const m: Record<string, { area: number; prod: number; water: number }> = {};
    for (const p of plan?.parcels || []) {
      const x = (m[p.crop] ||= { area: 0, prod: 0, water: 0 });
      x.area += p.area_m2; x.prod += p.metrics.production_kg; x.water += p.metrics.water_m3_season;
    }
    return Object.entries(m).sort((a, b) => b[1].area - a[1].area);
  }, [plan]);
  if (loading) return <Loader />;
  if (!farm) return <Empty title={t("plan.noFarm")}><Link className="btn-primary mt-2" to="/farm">{t("nav.terrain")}</Link></Empty>;

  const generate = async () => {
    setBusy(true); setErr(null);
    try { const p = await api(`/api/farms/${farm.id}/plans`, { method: "POST" }); setPlan(p); setSel(null); setEdits({}); reloadFarms(); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const replan = async () => {
    setBusy(true); setErr(null);
    try {
      const p = await api(`/api/farms/${farm.id}/plans/${plan.id}/replan`, { method: "POST", json: { edits: Object.entries(edits).map(([id, c]) => ({ parcel_id: Number(id), crop_code: c })) } });
      setPlan(p); setSel(null); setEdits({}); reloadFarms();
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const accept = async () => { await api(`/api/farms/${farm.id}/plans/${plan.id}/accept`, { method: "POST" }); setPlan({ ...plan, status: "accepted" }); };
  const s = plan?.summary;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">{t("plan.title")}</h1>
          <p className="text-sm text-ink-500">{farm.name} · {plan ? t("plan.version", { v: plan.version, date: date(plan.created_at) }) : t("plan.none")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {plan && plan.status !== "accepted" && <button className="btn-ghost" onClick={accept}>✓ {t("plan.accept")}</button>}
          {plan?.status === "accepted" && <Badge>{t("status.accepted")}</Badge>}
          <button className="btn-primary" onClick={generate} disabled={busy || !farm.area_validated}>{busy ? t("plan.computing") : plan ? t("plan.regenerate") : t("plan.generate")}</button>
        </div>
      </div>
      {!farm.area_validated && <Note tone="sun">{t("terrain.needValidation")} <Link to="/farm" className="font-semibold underline">{t("nav.terrain")}</Link></Note>}
      <ErrorBox error={err} />
      {busy && <Loader label={t("plan.computingLong")} />}
      {!plan && !busy && <Empty icon="🧩" title={t("plan.emptyTitle")}>{t("plan.emptyText")}</Empty>}
      {plan && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label={t("plan.productive")} value={num(s.productive_area_ha, 2)} unit="ha" hint={`${t("plan.infrastructure")} ${num(s.infrastructure_area_ha, 2)} ha${s.unused_area_ha > 0.001 ? ` · ${t("plan.unused")} ${num(s.unused_area_ha, 2)} ha` : ""}`} />
            <Stat label={t("plan.production")} value={num(Object.values<number>(s.production_t).reduce((a, b) => a + b, 0), 1)} unit="t" badge={<Quality q="estimated" />} />
            <Stat label={t("plan.water")} value={num(s.water_m3)} unit="m³" tone="water" />
            <Stat label={t("plan.energy")} value={num(s.energy_kwh)} unit="kWh" tone="sun" />
          </div>
          {s.rainfed_only ? <Note tone="sun">{t("plan.rainfedOnly")} <Link to="/farm" className="font-semibold underline">{t("nav.terrain")}</Link></Note>
            : s.optimizer.binding.some((b: string) => b.startsWith("water")) && <Note>{t("plan.waterLimited")}</Note>}
          <div className="grid gap-5 lg:grid-cols-3">
            <Card className="lg:col-span-2" title={t("plan.map")} subtitle={t("plan.mapSub")}>
              <FarmMap boundary={farm.boundary} parcels={plan.parcels} infrastructure={plan.infrastructure} sources={farm.water_sources} selected={sel?.id} onSelectParcel={setSel}
                cropOf={(p) => edits[p.id] || p.crop} height={540} />
              <div className="mt-3 flex flex-wrap gap-2">
                {legend.map(([c, v]) => <span key={c} className="chip bg-white !px-2.5 !py-1 !text-xs shadow-sm ring-1 ring-brand-100"><span className="h-3 w-3 rounded-sm" style={{ background: color(c) }} />{crop(c)} · {area(v.area)}</span>)}
                <span className="chip bg-sun-100 !px-2.5 !py-1 !text-xs text-sun-600"><span className="h-3 w-3 rounded-sm bg-sun-400" />{t("plan.infrastructure")}</span>
              </div>
            </Card>
            <Card title={sel ? `${sel.label} · ${crop(edits[sel.id] || sel.crop)}` : t("plan.parcel")} subtitle={sel ? undefined : t("plan.clickParcel")}>
              {sel ? <ParcelDetail p={sel} edit={edits[sel.id]} onEdit={(c) => setEdits({ ...edits, [sel.id]: c })} cropsList={Object.keys(crops)} /> : <Empty icon="👆" title={t("plan.clickParcel")} />}
              {Object.keys(edits).length > 0 && (
                <div className="mt-4 rounded-xl bg-brand-50 p-3">
                  <p className="text-sm">{t("plan.pendingEdits", { n: Object.keys(edits).length })}</p>
                  <div className="mt-2 flex gap-2"><button className="btn-primary flex-1" onClick={replan} disabled={busy}>{t("plan.recompute")}</button><button className="btn-ghost" onClick={() => setEdits({})}>{t("common.cancel")}</button></div>
                </div>
              )}
            </Card>
          </div>
          <Card title={t("plan.calendar")} subtitle={t("plan.calendarSub")}><Calendar parcels={plan.parcels} /></Card>
          <Card title={t("plan.why")} subtitle={t("plan.whySub")}>
            <div className="overflow-x-auto">
              <table className="table min-w-[640px]"><thead><tr><th>{t("common.crop")}</th><th>{t("common.area")}</th><th>{t("common.production")}</th><th>{t("plan.waterProd")}</th><th>{t("plan.national")}</th><th>{t("plan.score")}</th></tr></thead>
                <tbody>{Object.entries<any>(s.optimizer.scores).sort((a, b) => b[1].score - a[1].score).map(([c, v]) => (
                  <tr key={c} className={s.optimizer.areas_ha[c] ? "" : "opacity-50"}><td className="font-semibold"><span className="me-2 inline-block h-3 w-3 rounded-sm align-middle" style={{ background: color(c) }} />{crop(c)}</td>
                    <td>{s.optimizer.areas_ha[c] ? `${num(s.optimizer.areas_ha[c], 2)} ha` : "—"}</td><td>{s.production_t[c] ? `${num(s.production_t[c], 1)} t` : "—"}</td>
                    <td>{num(v.water_productivity_kg_m3, 1)} kg/m³</td><td>{num(v.national_priority * 100)} %</td><td>{num(v.score, 3)}</td></tr>))}</tbody></table>
            </div>
            <p className="mt-2 text-xs text-ink-500">{t("plan.sources")} : {s.sources.join(" · ")}</p>
          </Card>
        </>
      )}
    </div>
  );
}

function ParcelDetail({ p, edit, onEdit, cropsList }: { p: any; edit?: string; onEdit: (c: string) => void; cropsList: string[] }) {
  const { t } = useTranslation();
  const { crop } = useNames();
  const m = p.metrics;
  const rows: [string, React.ReactNode][] = [
    [t("common.area"), `${area(p.area_m2)} (${num(m.area_ha, 3)} ha)`],
    [t("plan.estimatedProd"), <span key="p">{mass(m.production_kg)} <span className="text-xs text-ink-500">({num(m.yield_kg_ha)} kg/ha)</span> <Quality q={m.yield_quality} /></span>],
    [t("plan.waterNeed"), `${num(m.water_m3_season)} m³ (${num(m.water_litres_season)} L)`],
    [t("plan.energyNeed"), `${num(m.energy_kwh_season)} kWh`],
    [t("plan.planting"), date(m.planting)], [t("plan.harvest"), date(m.harvest)],
    [t("plan.irrigationRule"), m.irrigation.interval_days === 1 ? t("plan.everyDay", { min: m.irrigation.peak_duration_min ?? "—", m3: num(m.irrigation.peak_volume_m3, 1) }) : t("plan.everyNDays", { n: m.irrigation.interval_days, min: m.irrigation.peak_duration_min ?? "—", m3: num(m.irrigation.peak_volume_m3, 1) })],
    [t("plan.pipe"), m.pumping ? `${num(m.pumping.pipe_length_m)} m · Ø ${m.pumping.diameter_mm} mm · ${num(m.pumping.total_head_m, 1)} m` : "—"],
    [t("plan.cost"), m.cost_tnd !== null ? `${num(m.cost_tnd)} TND` : <span key="c" className="text-xs text-ink-400">{t("plan.toFill")}</span>],
    [t("plan.revenue"), m.revenue_tnd !== null ? `${num(m.revenue_tnd)} TND` : <span key="r" className="text-xs text-ink-400">{t("plan.toFill")}</span>],
  ];
  return (
    <div className="space-y-3">
      {p.locked && <Badge tone="water">🔒 {t("plan.locked")}</Badge>}
      <dl className="divide-y divide-brand-50 text-sm">
        {rows.map(([k, v]) => <div key={k} className="flex justify-between gap-3 py-1.5"><dt className="text-ink-500">{k}</dt><dd className="text-end font-semibold">{v}</dd></div>)}
      </dl>
      {m.suitability_reasons?.length > 0 && <div className="flex flex-wrap gap-1">{m.suitability_reasons.map((r: string) => <Badge key={r} tone="sun">{t(`reasons.${r}`)}</Badge>)}</div>}
      <label className="block">
        <span className="label">{t("plan.changeCrop")}</span>
        <select className="input" value={edit || p.crop} onChange={(e) => onEdit(e.target.value)}>
          {cropsList.map((c) => <option key={c} value={c}>{crop(c)}</option>)}
        </select>
      </label>
    </div>
  );
}

function Calendar({ parcels }: { parcels: any[] }) {
  const { crop, color } = useNames();
  const byCrop: Record<string, { start: number; end: number }> = {};
  for (const p of parcels) {
    const s = new Date(p.metrics.planting).getTime(), e = new Date(p.metrics.harvest).getTime();
    const c = (byCrop[p.crop] ||= { start: s, end: e });
    c.start = Math.min(c.start, s); c.end = Math.max(c.end, e);
  }
  const entries = Object.entries(byCrop);
  if (!entries.length) return null;
  const min = Math.min(...entries.map(([, v]) => v.start)), max = Math.max(...entries.map(([, v]) => v.end));
  const months: Date[] = [];
  const d = new Date(min); d.setDate(1);
  while (d.getTime() <= max) { months.push(new Date(d)); d.setMonth(d.getMonth() + 1); }
  const span = max - min || 1;
  return (
    <div className="overflow-x-auto">
      <div className="min-w-[640px]">
        <div className="relative ms-36 flex border-b border-brand-100 pb-1 text-[11px] text-ink-500">
          {months.map((m, i) => <div key={i} className="flex-1 text-center">{date(m.toISOString(), { month: "short" })}</div>)}
        </div>
        {entries.map(([c, v]) => (
          <div key={c} className="flex items-center py-1.5">
            <div className="w-36 truncate text-sm font-semibold">{crop(c)}</div>
            <div className="relative h-6 flex-1 rounded-lg bg-slate-50">
              <div className="absolute inset-y-0 flex items-center rounded-lg px-2 text-[11px] font-semibold text-white" style={{ background: color(c), insetInlineStart: `${((v.start - min) / span) * 100}%`, width: `${((v.end - v.start) / span) * 100}%` }}>
                {date(new Date(v.start).toISOString(), { day: "numeric", month: "short" })} → {date(new Date(v.end).toISOString(), { day: "numeric", month: "short" })}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
