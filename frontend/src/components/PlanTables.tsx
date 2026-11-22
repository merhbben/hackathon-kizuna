/** Tables under the 2D plan: A allocation · B irrigation · C calendar · D energy · E results & storage,
 *  plus the automatic climate card. Data come from /report and /climate (nothing computed here). */
import { Fragment, useState } from "react";
import { useTranslation } from "react-i18next";
import { date, num } from "../lib/format";
import { useNames } from "../lib/reference";
import { Badge, Card, Note, Quality } from "./ui";

const Dash = () => <span className="text-ink-400">—</span>;
const n = (v: any, d = 0) => (v === null || v === undefined ? <Dash /> : num(v, d));

function Section({ letter, title, subtitle, children }: { letter: string; title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <Card title={<span className="flex items-center gap-2"><span className="grid h-7 w-7 place-items-center rounded-lg bg-brand-600 text-sm font-bold text-white">{letter}</span>{title}</span>} subtitle={subtitle}>
      {children}
    </Card>
  );
}

function Swatch({ c }: { c: string }) {
  const { color } = useNames();
  return <span className="me-2 inline-block h-3 w-3 rounded-sm align-middle" style={{ background: color(c) }} />;
}

/** Zone cell: letter + "n secteurs" toggle that unfolds the sector rows. */
function ZoneCell({ r, open, toggle }: { r: any; open: boolean; toggle: () => void }) {
  const { t } = useTranslation();
  const n = r.sectors?.length || 1;
  return (
    <td className="whitespace-nowrap">
      <b>{r.zone}</b>
      {n > 1 && <button type="button" onClick={(e) => { e.stopPropagation(); toggle(); }} className="ms-2 rounded-md bg-brand-50 px-1.5 py-0.5 text-[11px] font-semibold text-brand-700 hover:bg-brand-100">{open ? "▾" : "▸"} {t("p2.nSectors", { n })}</button>}
    </td>
  );
}

const distance = (a: any) => a.distance_m == null ? null : a.distance_max_m != null && a.distance_max_m !== a.distance_m ? `${num(a.distance_m)}–${num(a.distance_max_m)} m` : `${num(a.distance_m)} m`;

export function AllocationTable({ rep, onSelect, selected }: { rep: any; onSelect?: (zone: string) => void; selected?: string | null }) {
  const { t } = useTranslation();
  const { crop } = useNames();
  const [open, setOpen] = useState<Record<string, boolean>>({});
  return (
    <Section letter="A" title={t("p2.tA")} subtitle={t("p2.tAsub")}>
      <div className="overflow-x-auto">
        <table className="table min-w-[760px]">
          <thead><tr><th>{t("p2.zone")}</th><th>{t("common.crop")}</th><th>{t("p2.areaHa")}</th><th>%</th><th>{t("p2.waterM3")}</th><th>{t("p2.prodT")}</th><th>{t("p2.irrigTech")}</th><th>{t("p2.distance")}</th></tr></thead>
          <tbody>
            {rep.allocation.map((a: any) => (<Fragment key={a.zone}>
              <tr onClick={() => onSelect?.(a.zone)} className={`cursor-pointer ${selected === a.zone ? "bg-brand-50" : "hover:bg-brand-50/50"}`}>
                <ZoneCell r={a} open={!!open[a.zone]} toggle={() => setOpen({ ...open, [a.zone]: !open[a.zone] })} />
                <td className="font-semibold"><Swatch c={a.crop} />{crop(a.crop)}</td>
                <td className="tabular-nums">{num(a.area_ha, 3)}</td>
                <td className="tabular-nums">{num(a.pct, 1)}</td>
                <td className="tabular-nums">{n(a.water_m3)}</td>
                <td className="tabular-nums">{num(a.production_t, 2)} <Quality q={String(a.yield_quality || "").startsWith("official") ? "official" : a.yield_quality === "measured" ? "measured" : "estimated"} /></td>
                <td>{t(`method.${a.irrigation}`)}{a.rainfed && a.ya_ym != null ? <span className="ms-1 text-[11px] text-ink-500">({t("p2.rainCover", { pct: Math.round(a.rain_cover * 100), y: Math.round(a.ya_ym * 100) })})</span> : null}</td>
                <td className="tabular-nums">{a.distance_m != null ? `${distance(a)}${a.sources?.length ? ` · ${a.sources.join(", ")}` : ""}` : <Dash />}</td>
              </tr>
              {open[a.zone] && a.sectors.map((x: any) => (
                <tr key={x.zone} className="bg-brand-50/40 text-xs text-ink-500">
                  <td className="ps-6">{x.zone}</td><td /><td className="tabular-nums">{num(x.area_ha, 3)}</td><td className="tabular-nums">{num(x.pct, 1)}</td>
                  <td className="tabular-nums">{n(x.water_m3)}</td><td className="tabular-nums">{num(x.production_t, 2)}</td><td />
                  <td className="tabular-nums">{x.distance_m != null ? `${num(x.distance_m)} m${x.source ? ` · ${x.source}` : ""}` : <Dash />}</td>
                </tr>))}
            </Fragment>))}
          </tbody>
          <tfoot><tr className="font-bold"><td colSpan={2}>{t("p2.total")}</td><td>{num(rep.totals.area_ha, 3)}</td><td>{num(rep.allocation.reduce((s: number, a: any) => s + a.pct, 0), 1)}</td><td>{n(rep.totals.water_m3)}</td><td>{num(rep.totals.production_t, 2)}</td><td colSpan={2} /></tr></tfoot>
        </table>
      </div>
    </Section>
  );
}

export function IrrigationTable({ rep }: { rep: any }) {
  const { t } = useTranslation();
  const { crop } = useNames();
  const T = rep.irrigation_totals;
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const row = (r: any, sub = false) => (<>
    {sub ? <td className="ps-6">{r.zone}</td> : <ZoneCell r={r} open={!!open[r.zone]} toggle={() => setOpen({ ...open, [r.zone]: !open[r.zone] })} />}
    <td>{(sub ? r.source : r.sources?.join(", ")) || <Dash />}</td>
    <td>{sub ? null : <><Swatch c={r.crop} />{crop(r.crop)}</>}</td>
    <td className="tabular-nums">{r.events_per_week ? `${num(r.volume_m3_event, 1)} m³` : <span className="text-xs text-ink-500">{t("p2.noIrrigation")}</span>}</td>
    <td>{r.rainfed ? <span className="text-xs text-brand-700">{t("p2.rainfedNoIrr")}</span> : r.events_per_week ? t("p2.perWeek", { n: r.events_per_week }) : <Dash />}</td>
    <td className="text-xs">{r.days.length ? <>{r.days.map((d: string) => t(`p2.d_${d}`)).join(", ")}{r.start ? <b className="ms-1">· {r.start}{!sub && r.starts?.length > 1 ? ` → ${r.starts[r.starts.length - 1]}` : ""}</b> : null}</> : <Dash />}</td>
    <td className="tabular-nums">{r.duration_min != null ? `${num(r.duration_min)} min` : r.duration_unknown ? <Badge tone="sun">{t("p2.needFlow")}</Badge> : <Dash />}</td>
    <td className="tabular-nums">{r.events_per_week ? `${num(r.kwh_event, 2)} kWh` : <Dash />}{r.solar_share != null && r.events_per_week ? <span className="ms-1 text-[11px] text-sun-600">☀ {num(r.solar_share * 100)} %</span> : null}</td>
    <td className="tabular-nums">{num(r.week_m3, 1)} m³ · {num(r.week_kwh, 1)} kWh</td>
    <td className="tabular-nums">{n(r.season_m3)} m³ · {n(r.season_kwh)} kWh</td>
  </>);
  return (
    <Section letter="B" title={t("p2.tB")} subtitle={t(T.week === "peak_week" ? "p2.tBsubPeak" : "p2.tBsubNext", { start: date(T.week_start) })}>
      {rep.missing.includes("flow") && <div className="mb-3"><Note tone="sun">{t("p2.flowMissing")}</Note></div>}
      {T.conflicts > 0 && <div className="mb-3"><Note tone="danger">{t("p2.pumpConflict", { n: T.conflicts })}</Note></div>}
      <div className="overflow-x-auto">
        <table className="table min-w-[900px]">
          <thead><tr><th>{t("p2.zone")}</th><th>{t("p2.source")}</th><th>{t("common.crop")}</th><th>{t("p2.volEvent")}</th><th>{t("p2.frequency")}</th><th>{t("p2.dayHour")}</th><th>{t("p2.duration")}</th><th>{t("p2.energyEvent")}</th><th>{t("p2.week")}</th><th>{t("p2.season")}</th></tr></thead>
          <tbody>
            {rep.irrigation.map((r: any) => (<Fragment key={r.zone}>
              <tr>{row(r)}</tr>
              {open[r.zone] && r.sectors.map((x: any) => <tr key={x.zone} className="bg-brand-50/40 text-xs text-ink-500">{row(x, true)}</tr>)}
            </Fragment>))}
          </tbody>
          <tfoot><tr className="font-bold"><td colSpan={8}>{t("p2.total")}</td><td>{num(T.week_m3, 1)} m³ · {num(T.week_kwh, 1)} kWh</td><td>{num(T.season_m3)} m³ · {num(T.season_kwh)} kWh</td></tr></tfoot>
        </table>
      </div>
      <p className="mt-2 text-xs text-ink-500">{t("p2.irrigMethod")} {rep.irrigation.some((r: any) => r.sectors?.length > 1) ? t("p2.sectorsNote") : ""}</p>
    </Section>
  );
}

const PHASE_COLOR: Record<string, string> = { soil_preparation: "#c9b79c", planting: "#1f7a3d", growth: "#7cc47f", harvest: "#e0a526", irrigation: "#1c6fb8" };

export function CalendarTable({ rep }: { rep: any }) {
  const { t } = useTranslation();
  const { crop } = useNames();
  const rows = rep.calendar as any[];
  if (!rows.length) return null;
  const all = rows.flatMap((r) => r.phases.flatMap((p: any) => [p.start, p.end]));
  const start = new Date(all.reduce((a, b) => (a < b ? a : b)).slice(0, 7) + "-01");
  const end = new Date(all.reduce((a, b) => (a > b ? a : b)));
  const months: Date[] = [];
  for (const d = new Date(start); d <= end; d.setMonth(d.getMonth() + 1)) months.push(new Date(d));
  const t0 = start.getTime(), span = new Date(end.getFullYear(), end.getMonth() + 1, 1).getTime() - t0;
  const pos = (iso: string) => Math.max(0, Math.min(100, ((new Date(iso).getTime() - t0) / span) * 100));
  return (
    <Section letter="C" title={t("p2.tC")} subtitle={t("p2.tCsub")}>
      <div className="mb-3 flex flex-wrap gap-3 text-xs">
        {Object.entries(PHASE_COLOR).map(([k, c]) => <span key={k} className="flex items-center gap-1.5"><span className="h-3 w-5 rounded" style={{ background: c, opacity: k === "irrigation" ? 0.5 : 1 }} />{t(`p2.ph_${k}`)}</span>)}
      </div>
      <div className="overflow-x-auto">
        <div style={{ minWidth: Math.max(680, months.length * 54) }}>
          <div className="ms-40 flex border-b border-brand-100 pb-1 text-[11px] text-ink-500">
            {months.map((m, i) => <div key={i} className="flex-1 text-center">{date(m.toISOString(), { month: "short" })}{m.getMonth() === 0 || i === 0 ? ` ${String(m.getFullYear()).slice(2)}` : ""}</div>)}
          </div>
          {rows.map((r) => (
            <div key={r.crop} className="flex items-start border-b border-brand-50 py-2">
              <div className="w-40 pe-2">
                <div className="truncate text-sm font-semibold"><Swatch c={r.crop} />{crop(r.crop)}</div>
                <div className="text-[11px] text-ink-500">{t("p2.zones")} {r.zones.join(", ")}</div>
                {r.rotation?.crop && <div className="text-[11px] text-brand-700">↻ {t("p2.then")} {crop(r.rotation.crop)}</div>}
              </div>
              <div className="relative h-12 flex-1">
                {r.phases.filter((p: any) => p.phase === "irrigation").map((p: any, i: number) => (
                  <div key={`i${i}`} className="absolute bottom-0 h-2 rounded" title={t("p2.ph_irrigation")} style={{ background: PHASE_COLOR.irrigation, opacity: 0.5, insetInlineStart: `${pos(p.start)}%`, width: `${Math.max(0.8, pos(p.end) - pos(p.start))}%` }} />
                ))}
                {r.phases.filter((p: any) => p.phase !== "irrigation").map((p: any, i: number) => (
                  <div key={i} className="absolute top-1 flex h-7 items-center overflow-hidden rounded px-1 text-[10px] font-semibold text-white" title={`${t(`p2.ph_${p.phase}`)} : ${date(p.start)} → ${date(p.end)}${p.indicative ? ` (${t("p2.indicative")})` : ""}`}
                    style={{ background: PHASE_COLOR[p.phase], insetInlineStart: `${pos(p.start)}%`, width: `${Math.max(0.8, pos(p.end) - pos(p.start))}%`, opacity: p.indicative ? 0.75 : 1 }}>
                    {pos(p.end) - pos(p.start) > 7 ? t(`p2.ph_${p.phase}`) : ""}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
      <ul className="mt-2 space-y-0.5 text-xs text-ink-500">
        {rows.map((r) => <li key={r.crop}><b>{crop(r.crop)}</b> : {t("plan.planting")} {date(r.planting)} · {t("plan.harvest")} {date(r.harvest)} — {t(`p2.rule_${r.planting_rule?.rule || "window_middle"}`, { months: (r.planting_rule?.frost_months || []).map((m: number) => date(new Date(2026, m - 1, 1).toISOString(), { month: "short" })).join(", ") })}{r.rotation?.crop ? ` · ${t(`p2.rot_${r.rotation.reason}`, { crop: crop(r.rotation.crop) })}` : ""}</li>)}
      </ul>
    </Section>
  );
}

export function EnergyTable({ rep }: { rep: any }) {
  const { t } = useTranslation();
  const { crop } = useNames();
  const E = rep.energy;
  const sp = E.split;
  const tot = sp ? sp.solar_kwh + sp.battery_kwh + sp.grid_kwh : 0;
  return (
    <Section letter="D" title={t("p2.tD")} subtitle={t("p2.tDsub")}>
      {rep.missing.includes("pump_flow_or_depth") && <div className="mb-3"><Note tone="sun">{t("p2.energyMinimum")}</Note></div>}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label={t("p2.pumpKwh")} value={`${num(E.pump_kwh_total)} kWh`} />
        <Kpi label={t("p2.peakPower")} value={E.peak_power_kw != null ? `${num(E.peak_power_kw, 1)} kW` : "—"} hint={E.pumps.map((p: any) => `${p.source} ${num(p.kw, 1)} kW`).join(" · ")} />
        <Kpi label={t("p2.solarPlanned")} value={sp ? `${num(sp.pv_production_kwh)} kWh` : "—"} hint={sp ? t(sp.basis === "existing_pv" ? "p2.existingPv" : "p2.recommendedPv", { kwc: num(E.pv_kwc_existing ?? E.pv_kwc_recommended, 1) }) : undefined} />
        <Kpi label={t("p2.batteryAvail")} value={E.battery_kwh_existing != null ? `${num(E.battery_kwh_existing)} kWh` : E.battery_kwh_recommended ? `${num(E.battery_kwh_recommended)} kWh` : "—"} hint={E.battery_kwh_existing != null ? t("p2.existing") : E.battery_kwh_recommended ? t("p2.recommended") : t("p2.noCriticalLoad")} />
      </div>
      {sp && tot > 0 && (
        <div className="mt-4">
          <div className="mb-1 text-xs font-semibold text-ink-500">{t("p2.split")}</div>
          <div className="flex h-6 overflow-hidden rounded-lg text-[11px] font-semibold text-white">
            {[["solar", sp.solar_kwh, "#e0a526"], ["battery", sp.battery_kwh, "#7b8fd1"], ["grid", sp.grid_kwh, "#5b6b61"]].map(([k, v, c]: any) => v > 0 && (
              <div key={k} className="flex items-center justify-center" style={{ width: `${(100 * v) / tot}%`, background: c }}>{(100 * v) / tot > 9 ? `${num((100 * v) / tot)} %` : ""}</div>
            ))}
          </div>
          <div className="mt-1 flex flex-wrap gap-3 text-xs text-ink-500">
            <span>☀ {t("p2.solar")} {num(sp.solar_kwh)} kWh</span><span>🔋 {t("p2.battery")} {num(sp.battery_kwh)} kWh</span><span>🔌 {t("p2.grid")} {num(sp.grid_kwh)} kWh</span>
          </div>
        </div>
      )}
      <div className="mt-4 overflow-x-auto">
        <table className="table min-w-[420px]"><thead><tr><th>{t("p2.zone")}</th><th>{t("common.crop")}</th><th>{t("p2.energySeason")}</th><th>kWh/m³</th></tr></thead>
          <tbody>{E.per_zone.map((z: any) => <tr key={z.zone}><td className="font-bold">{z.zone}{z.sectors > 1 ? <span className="ms-1 text-[11px] font-normal text-ink-500">({t("p2.nSectors", { n: z.sectors })})</span> : null}</td><td>{z.crop ? <><Swatch c={z.crop} />{crop(z.crop)}</> : <Dash />}</td><td className="tabular-nums">{n(z.kwh)} kWh {z.minimum_only && <Badge tone="sun">{t("p2.minimum")}</Badge>}</td><td className="tabular-nums">{n(z.kwh_m3, 3)}</td></tr>)}</tbody></table>
      </div>
      <div className="mt-3 text-sm">
        {E.cost_tnd != null ? <p><b>{t("p2.energyCost")} :</b> {num(E.cost_tnd)} TND/{t("p2.year")} ({t("p2.tariff", { v: E.grid_tariff_tnd_kwh })}){E.cost_grid_only_tnd != null && E.cost_grid_only_tnd !== E.cost_tnd ? ` · ${t("p2.gridOnly", { v: num(E.cost_grid_only_tnd) })}` : ""}</p>
          : <Note tone="sun">{t("p2.tariffMissing")}</Note>}
      </div>
    </Section>
  );
}

export function ResultsTable({ rep }: { rep: any }) {
  const { t } = useTranslation();
  const { crop } = useNames();
  const R = rep.results;
  return (
    <Section letter="E" title={t("p2.tE")} subtitle={t("p2.tEsub")}>
      <div className="overflow-x-auto">
        <table className="table min-w-[860px]">
          <thead><tr><th>{t("common.crop")}</th><th>{t("p2.prodT")}</th><th>{t("p2.harvestPeriod")}</th><th>{t("p2.storage")}</th><th>{t("p2.volume")}</th><th>{t("p2.cooling")}</th><th>{t("p2.coldElectric")}</th></tr></thead>
          <tbody>{R.production.map((r: any) => (
            <tr key={r.crop}>
              <td className="font-semibold"><Swatch c={r.crop} />{crop(r.crop)}</td>
              <td className="tabular-nums font-semibold">{num(r.production_t, 2)} t</td>
              <td className="text-xs">{date(r.harvest_from, { day: "numeric", month: "short" })}{r.harvest_to !== r.harvest_from ? ` → ${date(r.harvest_to, { day: "numeric", month: "short" })}` : ""}</td>
              <td className="text-xs">{r.storable ? t("p2.coldAt", { t: r.storage_temp_c, rh: r.storage_rh_pct, w: r.max_storage_weeks }) : t("p2.dryStorage")}</td>
              <td className="tabular-nums">{r.volume_m3 != null ? `${num(r.volume_m3)} m³` : <Dash />}</td>
              <td className="tabular-nums">{r.refrigeration_kw != null ? `${num(r.refrigeration_kw, 1)} kW` : <Dash />}</td>
              <td className="tabular-nums">{r.electric_kw != null ? `${num(r.electric_kw, 1)} kW · ${num(r.annual_kwh)} kWh/${t("p2.year")}` : <Dash />}</td>
            </tr>))}</tbody>
          <tfoot><tr className="font-bold"><td>{t("p2.total")}</td><td>{num(R.total_t, 2)} t</td><td colSpan={5} /></tr></tfoot>
        </table>
      </div>
      {!R.cold_rooms.length && R.production.some((r: any) => r.storable) && <p className="mt-2 text-xs text-ink-500">{t("p2.coldNotSized")}</p>}
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label={t("p2.panels")} value={R.panels ? `${R.panels} × ${rep.energy.panel_wp} Wc` : "—"} hint={R.pv_kwc ? `${num(R.pv_kwc, 1)} kWc${rep.cold_building?.energy?.kwp ? ` · ${t("cb.pumpOnly")}` : ""}` : undefined} />
        <Kpi label={t("p2.batteries")} value={R.battery_kwh ? `${num(R.battery_kwh)} kWh` : "—"} hint={!R.battery_kwh ? t("p2.noCriticalLoad") : undefined} />
        <Kpi label={t("plan.cost")} value={R.cost_tnd != null ? `${num(R.cost_tnd)} TND` : "—"} hint={R.cost_tnd == null ? t("p2.fillPrices") : undefined} />
        <Kpi label={t("p2.margin")} value={R.margin_tnd != null ? `${num(R.margin_tnd)} TND` : "—"} hint={R.margin_tnd == null ? t("p2.fillPrices") : R.revenue_tnd != null ? `${t("plan.revenue")} ${num(R.revenue_tnd)} TND` : undefined} />
      </div>
    </Section>
  );
}

/** F · cold-storage building of large farms: why these crops, rooms, dedicated solar sizing. */
export function ColdBuildingCard({ rep }: { rep: any }) {
  const { t } = useTranslation();
  const { crop } = useNames();
  const C = rep.cold_building;
  if (!C?.required) return null;
  const E = C.energy || {};
  const mName = (m: number) => date(new Date(2026, m - 1, 1).toISOString(), { month: "short" });
  const months = (ms: number[]) => ms.map(mName).join(", ");
  const rooms = (rep.results?.cold_rooms || []).filter((r: any) => r.purpose === "offseason");
  const max = Math.max(1, ...(E.load_kwh_month || []), ...(E.pv_kwh_month || []));
  return (
    <Section letter="F" title={t("cb.title")} subtitle={t("cb.sub", { ha: num(C.threshold_ha) })}>
      {!C.chosen.length ? <Note tone="sun">{t(`cb.reason_${C.reason}`)}</Note> : (
        <div className="space-y-4">
          {C.forced && <Note>{t("cb.forced", { crop: crop(C.forced.crop), ha: num(C.forced.min_ha, 1) })}</Note>}
          <div>
            <h4 className="mb-2 text-sm font-bold">{t("cb.why")}</h4>
            <div className="grid gap-3 md:grid-cols-2">
              {C.offseason.map((o: any) => (
                <div key={o.crop} className="rounded-xl border border-water-300/60 bg-water-50 p-3 text-sm">
                  <div className="mb-1 flex flex-wrap items-center gap-2 font-semibold"><Swatch c={o.crop} />{crop(o.crop)}
                    {C.stored_t?.[o.crop] != null && <Badge tone="water">{t("cb.stored", { t: num(C.stored_t[o.crop], 1), pct: num(C.share_pct) })}</Badge>}
                    <span className="ms-auto text-[11px] font-normal text-ink-500">{t("cb.score", { s: num(o.score, 2) })}</span></div>
                  <ul className="space-y-0.5 text-[13px] text-ink-700">
                    <li>{t("cb.chosenLine", { harvest: date(o.farm_harvest, { day: "numeric", month: "short" }), until: date(o.sell_until, { day: "numeric", month: "short" }), weeks: num(o.storage_weeks) })}</li>
                    <li className="text-xs text-ink-500">{t(`cb.stop_${o.stops_at}`)} · {t("cb.efficiency", { pct: num((o.efficiency || 0) * 100) })}</li>
                    <li>{t("cb.national", { months: months(o.national_harvest_months) })}</li>
                    <li className="font-semibold text-water-700">{t("cb.offseason", { months: months(o.offseason_months) })}</li>
                    <li className="text-xs text-ink-500">{o.national_data ? t("cb.need", { deficit: num(o.national_deficit_share * 100, 1), imp: num(o.import_dependency * 100, 1) }) : t("cb.noNational")}</li>
                  </ul>
                </div>
              ))}
            </div>
            {C.ranked.length > C.chosen.length && <p className="mt-2 text-xs text-ink-500">{t("cb.others")} : {C.ranked.filter((r: any) => !C.chosen.includes(r.crop)).map((r: any) => `${crop(r.crop)} (${months(r.offseason_months)} · ${t("cb.score", { s: num(r.score, 2) })})`).join(" · ")}</p>}
          </div>

          <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
            <div className="rounded-xl border border-brand-100 p-3 text-sm">
              <h4 className="mb-1 font-bold">🏭 {t("cb.building")}</h4>
              {C.site ? <p>{t("cb.dims", { l: num(C.site.building_dims_m[0], 1), w: num(C.site.building_dims_m[1], 1), m2: num(C.site.building_m2) })}</p> : C.site_error && <Note tone="sun">{t("cb.site_error")}</Note>}
              <p className="text-ink-700">{t("cb.volume", { v: num(C.volume_m3), f: num(C.rooms_floor_m2) })}</p>
              <ul className="mt-2 space-y-1 text-xs text-ink-700">
                {rooms.map((r: any) => <li key={r.crop}>• <b>{t("cb.roomN", { n: r.room_id })}</b> {t("cb.room", { crop: crop(r.crop), t: num(r.mass_t, 1), v: num(r.volume_m3), temp: num(r.temperature_c, 1), rh: num(r.humidity_pct), kw: num(r.refrigeration_capacity_kw, 1), ekw: num(r.compressor_electric_kw, 1) })}
                  {r.operating && <span className="text-ink-500"> · {date(r.operating.from, { day: "numeric", month: "short" })} → {date(r.operating.to, { day: "numeric", month: "short" })} · {num(r.annual_kwh)} kWh</span>}
                  {r.shared_with?.length ? <span className="text-brand-700"> · {t("cb.shared", { crops: r.shared_with.map((c: string) => crop(c)).join(", ") })}</span> : null}</li>)}
              </ul>
              {rooms.length > 1 && C.physical_rooms === rooms.length && <p className="mt-1 text-[11px] text-ink-500">{t("cb.notShared")}</p>}
              <p className="mt-2 text-xs text-ink-500">{t("cb.onPlan")}</p>
            </div>
            <div className="rounded-xl border border-sun-400/60 bg-sun-100/40 p-3 text-sm">
              <h4 className="mb-2 font-bold">☀ {t("cb.energy")}</h4>
              {E.status !== "ok" && <div className="mb-2"><Note tone="sun">{t("cb.pvUnavailable")}</Note></div>}
              <div className="grid grid-cols-2 gap-2">
                <Kpi label={t("cb.annual")} value={`${num(E.annual_kwh)} kWh`} hint={`${t("cb.peak")} ${num(E.peak_kw, 1)} kW${E.kwh_per_t ? ` · ${num(E.kwh_per_t)} kWh/t` : ""}`} />
                <Kpi label={t("cb.pv")} value={E.kwp != null ? `${num(E.kwp, 1)} kWc` : "—"} hint={E.panels ? t("cb.panels", { n: E.panels, wp: num(E.panel_wp), m2: num(E.pv_area_m2) }) : undefined} />
                <Kpi label={t("cb.battery")} value={E.battery_kwh != null ? `${num(E.battery_kwh)} kWh` : "—"} hint={E.backup_hours != null ? t(E.recommended === "grid_tied" ? "cb.batteryHintBackup" : "cb.batteryHint", { h: num(E.backup_hours, 1) }) : undefined} />
                <Kpi label={t("cb.coverage")} value={E.solar_coverage_pct != null ? `${num(E.solar_coverage_pct, 1)} %` : "—"} hint={E.grid_kwh != null ? <>{t("cb.gridHint", { g: num(E.grid_kwh), s: num(E.surplus_kwh) })}{E.recommended === "grid_tied" && E.net_coverage_pct != null ? <><br />{t("cb.netCoverage", { pct: num(E.net_coverage_pct) })}</> : null}</> : undefined} />
              </div>
              {E.recommended && <p className="mt-2 rounded-lg bg-white/70 px-2 py-1.5 text-xs"><b>{t("cb.recommended", { s: t(`cb.sc_${E.recommended}`) })}</b> — {t(`cb.why_${E.recommendation_reason}`)}</p>}
              {E.pumps_from_surplus_kwh > 0 && <p className="mt-1 text-xs text-brand-700">💧 {t("cb.pumpsFromSurplus", { kwh: num(E.pumps_from_surplus_kwh) })}</p>}
              <p className="mt-2 text-xs text-ink-500">{E.pv_cost_tnd != null ? t("cb.costs", { pv: num(E.pv_cost_tnd), bat: num(E.battery_cost_tnd ?? 0) }) : t("cb.costsMissing")}</p>
            </div>
          </div>

          {E.scenarios && (
            <div className="overflow-x-auto">
              <h4 className="mb-1 text-sm font-bold">{t("cb.compare")}</h4>
              <table className="table min-w-[640px] text-sm">
                <thead><tr><th />{(["grid_tied", "off_grid"] as const).map((k) => <th key={k} className={E.recommended === k ? "text-brand-700" : ""}>{t(`cb.sc_${k}`)}{E.recommended === k ? " ✓" : ""}</th>)}</tr></thead>
                <tbody>
                  {([
                    ["cb.rowPv", (x: any) => `${num(x.kwp, 1)} kWc · ${x.panels} × ${num(x.panel_wp)} Wc · ${num(x.pv_area_m2)} m²`],
                    ["cb.rowBattery", (x: any) => `${num(x.battery_kwh)} kWh · ${num(x.backup_hours, 1)} h`],
                    ["cb.rowDirect", (x: any) => `${num(x.solar_coverage_pct, 1)} %`],
                    ["cb.rowNet", (x: any) => `${num(x.net_coverage_pct)} %`],
                    ["cb.rowGrid", (x: any) => `${num(x.grid_kwh)} kWh`],
                    ["cb.rowSurplus", (x: any) => `${num(x.surplus_kwh)} kWh${x.export_within_cap_kwh != null ? ` (${t("cb.withinCap", { kwh: num(x.export_within_cap_kwh), pct: num((x.injection_cap_pct || 0) * 100) })})` : ""}`],
                    ["cb.rowCost", (x: any) => x.pv_cost_tnd != null ? `${num(x.pv_cost_tnd + (x.battery_cost_tnd || 0))} TND` : "—"],
                  ] as [string, (x: any) => string][]).map(([k, f]) => (
                    <tr key={k}><td className="text-xs font-semibold text-ink-500">{t(k)}</td>{(["grid_tied", "off_grid"] as const).map((s) => <td key={s} className={`tabular-nums ${E.recommended === s ? "font-semibold" : ""}`}>{f(E.scenarios[s])}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {E.load_kwh_month && (
            <div>
              <div className="mb-1 flex flex-wrap items-center gap-3 text-xs"><b className="text-ink-700">{t("cb.chartTitle")}</b>
                <span className="flex items-center gap-1"><span className="h-3 w-3 rounded-sm bg-water-500" />{t("cb.load")}</span>
                {E.pv_kwh_month && <span className="flex items-center gap-1"><span className="h-3 w-3 rounded-sm bg-sun-400" />{t("cb.prod")}</span>}</div>
              <div className="flex h-36 items-end gap-1 rounded-xl border border-brand-50 p-2" dir="ltr">
                {E.load_kwh_month.map((v: number, i: number) => (
                  <div key={i} className="flex h-full flex-1 flex-col justify-end" title={`${mName(i + 1)} : ${num(v)} kWh${E.pv_kwh_month ? ` · PV ${num(E.pv_kwh_month[i])} kWh` : ""}`}>
                    <div className="flex flex-1 items-end gap-[2px]">
                      <div className="flex-1 rounded-t bg-water-500" style={{ height: `${(100 * v) / max}%` }} />
                      {E.pv_kwh_month && <div className="flex-1 rounded-t bg-sun-400" style={{ height: `${(100 * E.pv_kwh_month[i]) / max}%` }} />}
                    </div>
                    <div className={`mt-1 text-center text-[10px] ${E.worst_month === i + 1 ? "font-bold text-sun-600" : "text-ink-500"}`}>{mName(i + 1)}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
          <p className="text-xs text-ink-500">{t("cb.method")}</p>
        </div>
      )}
    </Section>
  );
}

function Kpi({ label, value, hint }: { label: string; value: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-brand-100 bg-white p-3">
      <div className="text-xs text-ink-500">{label}</div>
      <div className="mt-0.5 text-lg font-bold tabular-nums text-ink-900">{value}</div>
      {hint && <div className="text-[11px] text-ink-500">{hint}</div>}
    </div>
  );
}

export function ClimateCard({ clim }: { clim: any }) {
  const { t } = useTranslation();
  if (!clim) return null;
  const N = clim.normals, S = clim.statistics, R = clim.recent, F = clim.forecast, Z = clim.seasonality;
  const months = Array.from({ length: 12 }, (_, i) => date(new Date(2026, i, 1).toISOString(), { month: "short" }));
  return (
    <Card title={`🌦 ${t("p2.climate")}`} subtitle={t("p2.climateSub")}>
      {clim.location?.quality === "governorate_centroid" && <div className="mb-3"><Note tone="sun">{t("p2.climateApprox")}</Note></div>}
      {Z && (
        <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
          <Badge tone="water">{t(`p2.z_${Z.zone}`)} · P/ET0 = {num(Z.aridity_index, 2)}</Badge>
          {Z.items.map((r: any) => <Badge key={r.code} tone="sun">{t(`p2.risk_${r.code}`, { months: (r.months || []).map((m: number) => months[m - 1]).join(", "), v: r.value })}</Badge>)}
        </div>
      )}
      {N ? (
        <div className="overflow-x-auto">
          <table className="table min-w-[760px] text-xs">
            <thead><tr><th />{months.map((m) => <th key={m} className="text-center">{m}</th>)}<th className="text-center">{t("p2.year")}</th></tr></thead>
            <tbody>
              <tr><td className="font-semibold">T min / max °C</td>{N.months.map((m: any) => <td key={m.month} className="text-center tabular-nums">{num(m.tmin_c)}/{num(m.tmax_c)}</td>)}<td className="text-center">{num(N.annual.tmean_c, 1)}</td></tr>
              <tr><td className="font-semibold">{t("p2.rain")} mm</td>{N.months.map((m: any) => <td key={m.month} className="text-center tabular-nums">{num(m.rain_mm)}</td>)}<td className="text-center font-semibold">{num(N.annual.rain_mm)}</td></tr>
              <tr><td className="font-semibold">ET0 mm</td>{N.months.map((m: any) => <td key={m.month} className="text-center tabular-nums">{num(m.et0_mm)}</td>)}<td className="text-center font-semibold">{num(N.annual.et0_mm)}</td></tr>
              <tr><td className="font-semibold">{t("p2.rh")} %</td>{N.months.map((m: any) => <td key={m.month} className="text-center tabular-nums">{num(m.rh_pct)}</td>)}<td /></tr>
              <tr><td className="font-semibold">{t("p2.wind")} m/s</td>{N.months.map((m: any) => <td key={m.month} className="text-center tabular-nums">{num(m.wind_ms, 1)}</td>)}<td /></tr>
              <tr><td className="font-semibold">{t("p2.radiation")} MJ/m²/j</td>{N.months.map((m: any) => <td key={m.month} className="text-center tabular-nums">{num(m.rs_mj_day, 1)}</td>)}<td /></tr>
              {S && <tr><td className="font-semibold">{t("p2.frostProb")}</td>{S.months.map((m: any) => <td key={m.month} className={`text-center tabular-nums ${m.frost_probability >= 0.2 ? "font-bold text-water-700" : ""}`}>{num(m.frost_probability * 100)}%</td>)}<td /></tr>}
              {S && <tr><td className="font-semibold">{t("p2.heatDays")}</td>{S.months.map((m: any) => <td key={m.month} className="text-center tabular-nums">{num(m.heat_days_mean, 1)}</td>)}<td /></tr>}
            </tbody>
          </table>
        </div>
      ) : <Note tone="sun">{t("p2.climateUnavailable")}</Note>}
      <div className="mt-3 grid gap-3 text-xs sm:grid-cols-3">
        <div className="rounded-xl bg-brand-50 p-3"><b>{t("p2.normals")}</b> <Quality q="estimated" /><br />{N ? `${N.source} · ${N.period} · ${N.resolution}` : "—"}</div>
        <div className="rounded-xl bg-brand-50 p-3"><b>{t("p2.stats")}</b> <Quality q="estimated" /><br />{S ? <>{S.source} · {S.period} · {S.resolution}<br />{t("p2.rainYears", { mean: num(S.annual.rain_mean_mm), min: num(S.annual.rain_min_mm), max: num(S.annual.rain_max_mm), dry: num(S.annual.rain_dry_year_mm) })}</> : "—"}</div>
        <div className="rounded-xl bg-water-50 p-3"><b>{t("p2.recent")}</b> <Quality q="measured" /><br />{R ? <>{R.period} : {num(R.rain_mm)} mm ({t("p2.normalWas", { v: num(R.normal_rain_mm) })}{R.rain_anomaly_pct != null ? `, ${R.rain_anomaly_pct > 0 ? "+" : ""}${R.rain_anomaly_pct} %` : ""}) · ET0 {num(R.et0_mm)} mm</> : "—"}
          <br /><b>{t("p2.forecast")}</b> <Quality q="forecast" /> {F ? `${F.period} : ${t("p2.rain")} ${num(F.days.reduce((a: number, d: any) => a + (d.rain || 0), 0), 1)} mm · ET0 ${num(F.days.reduce((a: number, d: any) => a + (d.et0 || 0), 0), 1)} mm` : "—"}</div>
      </div>
      <p className="mt-2 text-[11px] text-ink-500">{t("p2.climateUse")} {t("p2.inm")}{clim.soil?.source ? ` · ${t("p2.soil")} : ${clim.soil.source}${clim.soil.note ? ` (${t("p2.soilEstimated")})` : ""}` : ""}</p>
    </Card>
  );
}
