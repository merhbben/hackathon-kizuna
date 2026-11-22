import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useApi } from "../../lib/hooks";
import { num } from "../../lib/format";
import { useNames } from "../../lib/reference";
import { Badge, Card, ErrorBox, GapBar, Loader, Note, Quality, Tabs } from "../../components/ui";
import { TunisiaMap } from "../../components/Maps";

export default function PlanCrops() {
  const { t } = useTranslation();
  const { crop, gov } = useNames();
  const [year, setYear] = useState<number | null>(null);
  const { data, loading, error } = useApi<any>(`/api/ministry/plan${year ? `?year=${year}` : ""}`, [year]);
  const [season, setSeason] = useState<"all" | "autumn_winter" | "spring_summer" | "perennial">("all");
  const [focus, setFocus] = useState<string>("tomato");
  const guidanceValues = useMemo(() => {
    if (!data) return {};
    return Object.fromEntries(data.guidance.map((g: any) => {
      const c = g.crops.find((x: any) => x.crop === focus);
      return [g.governorate, c && c.suitable ? c.irrigation_m3_ha : null];
    }));
  }, [data, focus]);
  if (loading) return <Loader />;
  if (error) return <ErrorBox error={error} />;
  const b = data.balance;
  const items = (b.items || []).filter((i: any) => season === "all" || i.season === season);
  const maxGap = Math.max(1, ...items.map((i: any) => Math.abs(i.gap_kt || 0)));
  const thisYear = new Date().getFullYear();
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">{t("ministry.plan.title")}</h1>
          <p className="text-sm text-ink-500">{t("ministry.plan.subtitle")}</p>
        </div>
        <div className="flex items-center gap-2">
          <label className="label !mb-0">{t("common.year")}</label>
          <select className="input !w-28" value={b.year} onChange={(e) => setYear(Number(e.target.value))}>
            {[0, 1, 2, 3, 4].map((k) => <option key={k} value={thisYear + k}>{thisYear + k}</option>)}
          </select>
        </div>
      </div>

      <Card title={t("ministry.plan.targets", { year: b.year })} subtitle={t("ministry.plan.targetsSub", { margin: b.safety_margin_pct, days: b.reserve_days })}
        action={<Tabs value={season} onChange={setSeason} items={[{ id: "all", label: t("season.all") }, { id: "autumn_winter", label: t("season.autumn_winter") }, { id: "spring_summer", label: t("season.spring_summer") }, { id: "perennial", label: t("season.perennial") }]} />}>
        <div className="overflow-x-auto">
          <table className="table min-w-[980px]">
            <thead><tr>
              <th>{t("common.crop")}</th><th>{t("ministry.plan.demand")}</th><th>{t("ministry.plan.required")}</th><th>{t("ministry.plan.expected")}</th>
              <th>{t("ministry.plan.gap")}</th><th>{t("ministry.plan.hectares")}</th><th>{t("ministry.plan.water")}</th><th>{t("ministry.plan.reserve")}</th><th>{t("ministry.plan.market")}</th><th>{t("ministry.plan.model")}</th>
            </tr></thead>
            <tbody>
              {items.map((i: any) => (
                <tr key={i.crop}>
                  <td className="font-semibold">{crop(i.crop)}<div className="text-[11px] font-normal text-ink-400">{t(`season.${i.season}`)}</div></td>
                  <td className="tabular-nums">{num(i.demand_kt)} kt<div className="text-[11px] text-ink-400">{num(i.demand_low_kt)}–{num(i.demand_high_kt)}</div></td>
                  <td className="tabular-nums">{num(i.required_kt)} kt<div className="text-[11px] text-ink-400">{t("ministry.plan.imports")} {num(i.imports_kt)} · {t("ministry.plan.exports")} {num(i.exports_kt)}</div></td>
                  <td className="tabular-nums">{i.expected_production_kt === null ? <Badge tone="danger">{t("common.missing")}</Badge> : `${num(i.expected_production_kt)} kt`}</td>
                  <td><GapBar value={i.gap_kt} max={maxGap} /></td>
                  <td className="tabular-nums">{num(i.hectares_needed)} ha<div className="text-[11px] text-ink-400">{num(i.yield_kg_ha)} kg/ha</div></td>
                  <td className="tabular-nums">{i.water_mm3_if_irrigated === null ? "—" : `${num(i.water_mm3_if_irrigated, 1)} Mm³`}<div className="text-[11px] text-ink-400">{i.rainfed_possible ? t("ministry.plan.ifIrrigated") : t("ministry.plan.irrigated")}</div></td>
                  <td className="tabular-nums">{i.reserve_target_kt ? `${num(i.reserve_target_kt)} kt` : "—"}</td>
                  <td>{i.price_pressure ? <Badge tone={i.price_pressure.direction === "up" ? "danger" : i.price_pressure.direction === "down" ? "water" : "slate"}>{t(`pressure.${i.price_pressure.direction}`)}</Badge> : "—"}</td>
                  <td><div className="flex flex-col gap-1"><Quality q={i.per_capita_quality === "official" ? "forecast" : i.per_capita_quality} /><span className="text-[11px] text-ink-500">{i.demand_model} · MAPE {num(i.demand_mape_pct, 1)} %</span></div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <Note>{t("ministry.plan.method")}</Note>
          <Note tone="sun">{t("ministry.plan.priceNote")}</Note>
        </div>
      </Card>

      <div className="grid gap-5 lg:grid-cols-5">
        <Card className="lg:col-span-3" title={t("ministry.plan.regional")} subtitle={t("ministry.plan.regionalSub")}
          action={<select className="input !w-48" value={focus} onChange={(e) => setFocus(e.target.value)}>
            {data.guidance[0]?.crops.map((c: any) => <option key={c.crop} value={c.crop}>{crop(c.crop)}</option>)}
          </select>}>
          <TunisiaMap values={guidanceValues} scale="blue" format={(v) => v === null || v === undefined ? t("ministry.plan.notSuitable") : `${num(v)} m³/ha`} />
          <p className="mt-2 text-xs text-ink-500">{t("ministry.plan.regionalNote")}</p>
        </Card>
        <Card className="lg:col-span-2" title={t("ministry.plan.allocation")}>
          {data.allocation?.status === "ok" ? (
            <div className="max-h-[420px] overflow-auto">
              <table className="table"><thead><tr><th>{t("farm.governorate")}</th><th>{t("common.crop")}</th><th>ha</th><th>kt</th><th>Mm³</th></tr></thead>
                <tbody>{data.allocation.governorates.map((a: any, k: number) => <tr key={k}><td>{gov(a.governorate)}</td><td>{crop(a.crop)}</td><td>{num(a.hectares)}</td><td>{num(a.production_kt, 1)}</td><td>{num(a.water_mm3, 1)}</td></tr>)}</tbody></table>
            </div>
          ) : (
            <Note tone="sun">{t("ministry.plan.allocationMissing")}</Note>
          )}
        </Card>
      </div>
    </div>
  );
}
