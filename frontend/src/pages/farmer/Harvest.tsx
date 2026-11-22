import { Fragment, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import { useFarm } from "../../lib/farm";
import { date, num } from "../../lib/format";
import { useNames } from "../../lib/reference";
import { Badge, Card, Empty, ErrorBox, Loader, Note, Stat } from "../../components/ui";

export default function Harvest() {
  const { t } = useTranslation();
  const { farm, plan, setFarm, loading } = useFarm();
  const { crop, color } = useNames();
  if (loading) return <Loader />;
  if (!plan) return <Empty icon="🧺" title={t("water.noPlan")}><Link className="btn-primary mt-2" to="/farm/plan">{t("nav.myplan")}</Link></Empty>;
  const s = plan.summary;
  const harvests: Record<string, { t: number; from: string; to: string }> = {};
  for (const p of plan.parcels) {
    const h = (harvests[p.crop] ||= { t: 0, from: p.metrics.harvest, to: p.metrics.harvest });
    h.t += p.metrics.production_kg / 1000;
    if (p.metrics.harvest < h.from) h.from = p.metrics.harvest;
    if (p.metrics.harvest > h.to) h.to = p.metrics.harvest;
  }
  const c = plan.contribution;
  const rooms = plan.storage.rooms || [];
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold">{t("harvest.title")}</h1>
        <p className="text-sm text-ink-500">{farm.name} · {s.large_farm ? t("farm.large") : t("farm.small")}</p>
      </div>
      <Card title={t("harvest.forecast")} subtitle={t("harvest.forecastSub")}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Object.entries(harvests).map(([k, v]) => (
            <div key={k} className="rounded-xl border border-brand-100 p-3">
              <div className="flex items-center gap-2"><span className="h-3 w-3 rounded-sm" style={{ background: color(k) }} /><span className="font-semibold">{crop(k)}</span></div>
              <div className="mt-1 text-2xl font-bold tabular-nums text-brand-700">{num(v.t, 1)} t</div>
              <div className="text-xs text-ink-500">{t("harvest.around")} {date(v.from, { day: "numeric", month: "long" })}{v.to !== v.from ? ` → ${date(v.to, { day: "numeric", month: "long" })}` : ""}</div>
            </div>
          ))}
        </div>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title={t("harvest.reserve")} subtitle={t("harvest.reserveSub")}>
          {c.status === "not_large_farm" ? <Note>{t("harvest.notLarge")}</Note> : !Object.keys(c.items || {}).length ? <Note tone="sun">{t("harvest.noTargets")}</Note> : (
            <>
              <table className="table"><thead><tr><th>{t("common.crop")}</th><th>%</th><th>t</th><th>{t("harvest.storage")}</th></tr></thead>
                <tbody>{Object.entries<any>(c.items).map(([k, v]) => <tr key={k}><td>{crop(k)}</td><td className="font-semibold">{num(v.proposed_pct, 1)} %</td><td>{num(v.proposed_t, 1)}</td><td>{t(`storage.${v.storage}`)}</td></tr>)}</tbody></table>
              <div className="mt-3"><Note tone="sun">{t("harvest.proposalNote", { cap: c.cap_pct })}</Note></div>
            </>
          )}
        </Card>
        <Card title={t("harvest.coldRooms")} subtitle={t("harvest.coldRoomsSub")}>
          {farm.equipment.filter((e: any) => e.kind === "cold_room").map((e: any) => (
            <div key={e.id} className="mb-3 rounded-xl border border-water-300/50 p-3 text-sm">
              <div className="flex items-center justify-between"><b>{t("harvest.existingRoom")}</b>{e.specs.source === "plan" && <Badge tone="water">{t("harvest.fromPlan")}</Badge>}</div>
              <p className="mt-1">{e.specs.floor_m2 ? `${num(e.specs.floor_m2)} m² ${t("harvest.floorArea")}` : ""} {e.specs.label ? `· ${e.specs.label}` : ""}</p>
              <p className="mt-1 text-xs text-ink-500">{t("harvest.roomVolumeUnknown")}</p>
            </div>
          ))}
          {!rooms.length ? <Note>{t("harvest.noColdRoom")}</Note> : rooms.map((r: any) => (
            <div key={r.crop} className="mb-3 rounded-xl bg-water-50 p-3 text-sm">
              <div className="flex items-center justify-between"><b>{crop(r.crop)}</b><Badge tone="water">{r.temperature_c} °C · {r.humidity_pct} %</Badge></div>
              <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
                <span className="text-ink-500">{t("harvest.capacity")}</span><span className="text-end font-semibold">{num(r.mass_t, 1)} t · {num(r.volume_m3)} m³</span>
                <span className="text-ink-500">{t("harvest.floor")}</span><span className="text-end font-semibold">{num(r.floor_m2)} m² × {r.height_m} m</span>
                <span className="text-ink-500">{t("harvest.cooling")}</span><span className="text-end font-semibold">{num(r.refrigeration_capacity_kw, 1)} kW</span>
                <span className="text-ink-500">{t("harvest.electric")}</span><span className="text-end font-semibold">{num(r.compressor_electric_kw, 1)} kW · {num(r.annual_kwh)} kWh/an</span>
                <span className="text-ink-500">{t("harvest.keep")}</span><span className="text-end font-semibold">{r.max_storage_weeks} {t("units.weeks")}</span>
                <span className="text-ink-500">{t("plan.cost")}</span><span className="text-end font-semibold">{r.cost_tnd ? `${num(r.cost_tnd)} TND` : t("plan.toFill")}</span>
              </div>
            </div>
          ))}
        </Card>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label={t("energy.pv")} value={num(plan.energy.kwp_needed, 1)} unit="kWc" tone="sun" hint={t("energy.panels", { n: plan.energy.panels ?? 0, wp: plan.energy.panel_wp ?? 550, area: num(plan.energy.pv_area_m2) })} />
        <Stat label={t("energy.battery")} value={num(plan.energy.battery_kwh_needed)} unit="kWh" tone="sun" />
        <Stat label={t("plan.cost")} value={s.cost_tnd !== null ? num(s.cost_tnd) : "—"} unit="TND" hint={s.cost_tnd !== null ? t(s.cost_quality === "official" ? "costs.officialHint" : "costs.autoHint") : t("costs.recompute")} />
        <Stat label={t("plan.revenue")} value={s.revenue_tnd !== null ? num(s.revenue_tnd) : "—"} unit="TND" hint={s.revenue_tnd === null ? t("harvest.fillPrices") : undefined} />
      </div>
      <CostsCard plan={plan} />
      <PricesForm farm={farm} crops={Object.keys(s.production_t)} onSaved={setFarm} />
    </div>
  );
}

function PricesForm({ farm, crops, onSaved }: { farm: any; crops: string[]; onSaved: (f: any) => void }) {
  const { t } = useTranslation();
  const { crop } = useNames();
  const prefs = farm.preferences || {};
  const [prices, setPrices] = useState<Record<string, string>>(Object.fromEntries(crops.map((c) => [c, prefs.prices_tnd_kg?.[c] ?? ""])));
  const [err, setErr] = useState<any>(null);
  const [ok, setOk] = useState(false);
  const save = async () => {
    setErr(null); setOk(false);
    const clean = (o: Record<string, string>) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== "").map(([k, v]) => [k, Number(v)]));
    try { onSaved(await api(`/api/farms/${farm.id}`, { method: "PATCH", json: { preferences: { ...prefs, prices_tnd_kg: clean(prices) } } })); setOk(true); }
    catch (e) { setErr(e); }
  };
  return (
    <Card title={t("costs.pricesTitle")} subtitle={t("costs.pricesSub")}>
      <div className="overflow-x-auto">
        <table className="table min-w-[480px]"><thead><tr><th>{t("common.crop")}</th><th>{t("harvest.price")} (TND/kg)</th></tr></thead>
          <tbody>{crops.map((c) => <tr key={c}><td>{crop(c)}</td>
            <td><input className="input !py-1.5" type="number" step="0.01" min="0" value={prices[c]} onChange={(e) => setPrices({ ...prices, [c]: e.target.value })} /></td>
</tr>)}</tbody></table>
      </div>
      <div className="mt-3 flex items-center gap-3"><button className="btn-primary" onClick={save}>{t("common.save")}</button>{ok && <span className="text-sm text-brand-700">{t("harvest.savedRegen")}</span>}</div>
      <ErrorBox error={err} />
    </Card>
  );
}

const ITEMS = ["labour", "seed", "ammonitrate", "dap", "potash", "treatments", "mechanisation", "energy", "water", "drip"];

/** Production cost computed automatically for each crop of the plan (engines/costs.py). */
function CostsCard({ plan }: { plan: any }) {
  const { t } = useTranslation();
  const { crop, color } = useNames();
  const [open, setOpen] = useState<string | null>(null);
  const costs: Record<string, any> = plan.summary.costs || {};
  const area: Record<string, number> = {};
  for (const p of plan.parcels) area[p.crop] = (area[p.crop] || 0) + p.area_m2 / 1e4;
  const codes = Object.keys(costs).filter((c) => area[c]);
  if (!codes.length) return <Card title={t("costs.title")}><Note tone="sun">{t("costs.recompute")}</Note></Card>;
  const q = (x: string) => <Badge tone={x === "official" ? "brand" : x === "measured" ? "water" : x === "missing" ? "sun" : "slate"}>{t(`costs.q_${x}`)}</Badge>;
  const total = codes.reduce((a, c) => a + (costs[c].total_tnd_ha || 0) * area[c], 0);
  return (
    <Card title={t("costs.title")} subtitle={t("costs.sub")}>
      <div className="overflow-x-auto">
        <table className="table min-w-[720px]">
          <thead><tr><th>{t("common.crop")}</th><th>{t("costs.perHa")}</th><th>{t("costs.area")}</th><th>{t("costs.total")}</th><th>{t("costs.main")}</th><th /></tr></thead>
          <tbody>{codes.map((c) => {
            const b = costs[c];
            const items = Object.entries<any>(b.items || {}).filter(([, it]) => it.tnd != null).sort((x, y) => y[1].tnd - x[1].tnd);
            return (<Fragment key={c}>
              <tr className="cursor-pointer hover:bg-brand-50/50" onClick={() => setOpen(open === c ? null : c)}>
                <td className="font-semibold"><span className="me-2 inline-block h-3 w-3 rounded-sm align-middle" style={{ background: color(c) }} />{crop(c)}</td>
                <td className="tabular-nums font-semibold">{b.total_tnd_ha != null ? `${num(b.total_tnd_ha)} TND` : "—"} {q(b.quality)}</td>
                <td className="tabular-nums">{num(area[c], 2)} ha</td>
                <td className="tabular-nums">{b.total_tnd_ha != null ? `${num(b.total_tnd_ha * area[c])} TND` : "—"}</td>
                <td className="text-xs text-ink-500">{items.slice(0, 3).map(([k, it]) => `${t(`costs.i_${k}`)} ${num((100 * it.tnd) / Math.max(1, b.total_tnd_ha))} %`).join(" · ")}</td>
                <td className="text-xs text-brand-700">{open === c ? "▾" : "▸"} {t("costs.detail")}</td>
              </tr>
              {open === c && (
                <tr><td colSpan={6} className="bg-brand-50/40">
                  {b.basis === "ministry_reference" ? <p className="text-sm">{t("costs.ministryRef")}</p> : (
                    <>
                      <table className="table text-xs">
                        <thead><tr><th>{t("costs.item")}</th><th>{t("costs.qty")}</th><th>{t("costs.unitPrice")}</th><th>TND/ha</th><th>{t("costs.quality")}</th></tr></thead>
                        <tbody>{ITEMS.filter((k) => b.items[k]).map((k) => { const it = b.items[k]; return (
                          <tr key={k}><td>{t(`costs.i_${k}`)}</td><td className="tabular-nums">{num(it.qty, it.qty < 10 ? 2 : 0)} {t(`costs.u_${it.unit}`)}</td>
                            <td className="tabular-nums">{it.price != null ? `${num(it.price, it.price < 1 ? 3 : 2)} TND` : <span className="text-sun-600">{t("costs.priceMissing")}</span>}</td>
                            <td className="tabular-nums font-semibold">{it.tnd != null ? num(it.tnd) : "—"}</td><td>{q(it.quality)}</td></tr>); })}</tbody>
                      </table>
                      <p className="mt-2 text-xs text-ink-500">{t("costs.basisLine", { y: num(b.yield_t_ha, 1), w: num(b.water_m3_ha), d: num(b.labour_days_ha), n: num(b.nutrients_kg_ha?.N), p: num(b.nutrients_kg_ha?.P2O5), k: num(b.nutrients_kg_ha?.K2O) })}</p>
                      {b.missing?.includes("grid_tariff") && <p className="mt-1 text-xs text-sun-600">{t("costs.tariffMissing")}</p>}
                    </>
                  )}
                </td></tr>
              )}
            </Fragment>);
          })}</tbody>
          <tfoot><tr className="font-bold"><td colSpan={3}>{t("p2.total")}</td><td>{num(total)} TND</td><td colSpan={2} /></tr></tfoot>
        </table>
      </div>
      <p className="mt-2 text-xs text-ink-500">{t("costs.method")}</p>
    </Card>
  );
}
