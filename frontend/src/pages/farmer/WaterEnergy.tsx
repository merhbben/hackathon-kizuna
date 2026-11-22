import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useFarm } from "../../lib/farm";
import { date, MONTHS, num } from "../../lib/format";
import { useNames } from "../../lib/reference";
import { Badge, Card, Empty, Loader, Note, Quality, Stat, Tabs } from "../../components/ui";

export default function WaterEnergy() {
  const { t } = useTranslation();
  const { farm, plan, loading } = useFarm();
  const { crop } = useNames();
  const [week, setWeek] = useState<"next_7_days" | "peak_week">("next_7_days");
  const [month, setMonth] = useState(6);
  const seasonal = useMemo(() => Object.entries<any>(plan?.irrigation?.seasonal || {}).map(([m, v]) => ({ m: date(`${m}-01`, { month: "short", year: "2-digit" }), m3: v.m3, kwh: v.kwh })), [plan]);
  if (loading) return <Loader />;
  if (!plan) return <Empty icon="💧" title={t("water.noPlan")}><Link className="btn-primary mt-2" to="/farm/plan">{t("nav.myplan")}</Link></Empty>;
  const w = plan.irrigation.weeks[week] || plan.irrigation.weeks.next_7_days;
  const e = plan.energy;
  const sim = e.simulation;
  const hourly = sim ? (sim.hourly_typical_day[month] || []).map((h: any) => ({ h: `${h.h}h`, pv: h.pv, load: h.load, soc: h.soc_pct })) : [];
  const byDay: Record<string, any[]> = {};
  for (const ev of w.events) (byDay[ev.date] ||= []).push(ev);
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold">{t("water.title")}</h1>
        <p className="text-sm text-ink-500">{farm.name} · {t(`method.${plan.irrigation.method}`)} · {t("water.soil")} {t(`texture.${plan.irrigation.soil.texture}`)}</p>
      </div>
      <Card title={t("water.program")} subtitle={t("water.programSub")}
        action={<Tabs value={week} onChange={setWeek} items={[{ id: "next_7_days", label: t("water.next7") }, { id: "peak_week", label: t("water.peakWeek") }]} />}>
        <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
          <Quality q={w.quality} />
          <span className="text-ink-500">{w.quality === "forecast" ? t("water.fromForecast") : t("water.fromClimate")}</span>
          <span className="ms-auto font-semibold">{num(w.total_m3)} m³ · {num(w.total_kwh)} kWh</span>
          {w.conflicts > 0 && <Badge tone="danger">{t("water.conflicts", { n: w.conflicts })}</Badge>}
        </div>
        {w.events.some((e: any) => e.duration_unknown) && <div className="mb-3"><Note tone="sun">{t("water.flowUnknown")}</Note></div>}
        {!w.events.length ? <Empty icon="🌱" title={t("water.nothing")}>{t("water.nothingText")}</Empty> : (
          <div className="space-y-4">
            {Object.entries(byDay).map(([d, evs]) => (
              <div key={d}>
                <h3 className="mb-1 text-sm font-bold text-brand-700">{date(d, { weekday: "long", day: "numeric", month: "long" })}</h3>
                <div className="overflow-x-auto">
                  <table className="table min-w-[560px]"><thead><tr><th>{t("water.time")}</th><th>{t("water.parcel")}</th><th>{t("water.duration")}</th><th>{t("water.volume")}</th><th>{t("water.energy")}</th></tr></thead>
                    <tbody>{evs.map((ev, i) => (
                      <tr key={i}><td className="font-semibold tabular-nums">{ev.start ?? "—"} → {ev.end ?? "—"} {ev.solar_share !== undefined && ev.solar_share >= 0.99 && <span title={t("water.solar")}>☀️</span>}</td>
                        <td>{ev.parcel} · {crop(ev.crop)}</td><td className="tabular-nums">{ev.duration_min != null ? `${ev.duration_min} min` : "—"}</td><td className="tabular-nums">{num(ev.volume_m3, 1)} m³</td><td className="tabular-nums">{num(ev.energy_kwh, 1)} kWh</td></tr>))}</tbody></table>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title={t("water.seasonal")} subtitle={t("water.seasonalSub")}>
          <div className="h-64" dir="ltr">
            <ResponsiveContainer>
              <BarChart data={seasonal}><CartesianGrid strokeDasharray="3 3" stroke="#e7efe9" /><XAxis dataKey="m" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v: any, n: any) => [`${num(v)} ${n === "m3" ? "m³" : "kWh"}`, n === "m3" ? t("plan.water") : t("plan.energy")]} />
                <Bar dataKey="m3" fill="#1c6fb8" radius={[4, 4, 0, 0]} /></BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title={t("water.pumping")} subtitle={t("water.pumpingSub")}>
          <ul className="space-y-2 text-sm">
            {plan.parcels.slice(0, 8).map((p: any) => p.metrics.pumping && (
              <li key={p.id} className="flex justify-between gap-2 border-b border-brand-50 pb-1.5"><span>{p.label} · {crop(p.crop)}</span>
                <span className="tabular-nums text-ink-700">{p.metrics.pumping.flow_unknown ? `≥ ${num(p.metrics.specific_energy_kwh_m3, 2)} kWh/m³ (${t("water.minimum")})` : `${num(p.metrics.pumping.power_kw, 1)} kW · ${num(p.metrics.pumping.total_head_m)} m · ${num(p.metrics.specific_energy_kwh_m3, 2)} kWh/m³`}</span></li>))}
          </ul>
          {e.pump_rated_kw && <p className="mt-2 text-xs text-ink-500">{t("water.installedPump")} : {num(e.pump_rated_kw, 1)} kW</p>}
        </Card>
      </div>

      {e.status === "pvgis_unavailable" ? <Note tone="sun">{t("energy.pvgisDown")}</Note> : sim && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label={t("energy.pv")} value={num(e.kwp_needed, 1)} unit="kWc" tone="sun" hint={t("energy.panels", { n: e.panels, wp: e.panel_wp, area: num(e.pv_area_m2) })} />
            <Stat label={t("energy.battery")} value={num(e.battery_kwh_needed)} unit="kWh" tone="sun" hint={e.critical_load_kw ? t("energy.critical", { kw: num(e.critical_load_kw, 1) }) : t("energy.noCritical")} />
            <Stat label={t("energy.autonomy")} value={e.autonomy_hours ? num(e.autonomy_hours, 1) : "—"} unit="h" tone="water" />
            <Stat label={t("energy.selfSufficiency")} value={num(sim.self_sufficiency_pct)} unit="%" />
          </div>
          <div className="grid gap-5 lg:grid-cols-3">
            <Card className="lg:col-span-2" title={t("energy.typicalDay")} subtitle={`PVGIS ${e.pv_source?.radiation_db || ""} ${e.pv_source?.years || ""}`}
              action={<select className="input !w-32" value={month} onChange={(ev) => setMonth(Number(ev.target.value))}>{Array.from({ length: 12 }, (_, i) => <option key={i} value={i}>{MONTHS(i)}</option>)}</select>}>
              <div className="h-72" dir="ltr">
                <ResponsiveContainer>
                  <ComposedChart data={hourly}><CartesianGrid strokeDasharray="3 3" stroke="#e7efe9" /><XAxis dataKey="h" tick={{ fontSize: 11 }} /><YAxis yAxisId="kw" tick={{ fontSize: 11 }} /><YAxis yAxisId="soc" orientation="right" domain={[0, 100]} tick={{ fontSize: 11 }} />
                    <Tooltip /><Legend />
                    <Area yAxisId="kw" dataKey="pv" name={t("energy.solarProd")} fill="#fff4d6" stroke="#f6b93b" />
                    <Line yAxisId="kw" dataKey="load" name={t("energy.consumption")} stroke="#1c6fb8" dot={false} strokeWidth={2} />
                    <Line yAxisId="soc" dataKey="soc" name={t("energy.soc")} stroke="#1f7a3d" dot={false} strokeDasharray="4 3" />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card title={t("energy.strategy")}>
              <dl className="space-y-2 text-sm">
                <Row k={t("energy.annualPv")} v={`${num(sim.annual.pv)} kWh`} />
                <Row k={t("energy.reserved", { pct: Math.round(e.policy.reserve_share * 100) })} v={`${num(sim.annual.to_reserve)} kWh`} />
                <Row k={t("energy.crisisLevel")} v={`${Math.round(e.policy.crisis_min_soc * 100)} %`} />
                <Row k={t("energy.consumption")} v={`${num(sim.annual.load)} kWh`} />
                <Row k={t("energy.fromGrid")} v={`${num(sim.annual.grid)} kWh`} />
                <Row k={t("energy.surplus")} v={`${num(sim.export.potential_kwh)} kWh`} />
                <Row k={t("energy.exportCap", { pct: Math.round((sim.export.regulatory_cap_pct || 0) * 100) })} v={sim.export.within_cap_kwh !== null ? `${num(sim.export.within_cap_kwh)} kWh` : "—"} />
              </dl>
              <div className="mt-3 space-y-2">
                <Note tone="sun">{t("energy.legal", { status: t(`status.${sim.export.regulatory_cap_status}`) })}</Note>
                <Note tone="danger">{t("energy.hypothesis", { kwh: num(sim.export.hypothesis_80pct_kwh) })}</Note>
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="flex justify-between gap-2 border-b border-brand-50 pb-1"><dt className="text-ink-500">{k}</dt><dd className="font-semibold tabular-nums">{v}</dd></div>;
}
