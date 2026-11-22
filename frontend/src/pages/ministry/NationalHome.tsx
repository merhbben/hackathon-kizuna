import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApi } from "../../lib/hooks";
import { num } from "../../lib/format";
import { useNames } from "../../lib/reference";
import { Badge, Card, ErrorBox, Loader, Note, Quality, Stat, Tabs } from "../../components/ui";
import { TunisiaMap } from "../../components/Maps";
import { AlertList } from "./AlertsManagement";

export default function NationalHome() {
  const { t } = useTranslation();
  const { crop, gov } = useNames();
  const { data, loading, error } = useApi<any>("/api/ministry/overview");
  const [layer, setLayer] = useState<"alerts" | "farms" | "dams">("alerts");
  if (loading) return <Loader />;
  if (error) return <ErrorBox error={error} />;
  const b = data.balance;
  const items = b.items || [];
  const values: Record<string, number | null> = Object.fromEntries(data.governorates.map((g: any) => [g.code,
    layer === "alerts" ? g.alerts : layer === "farms" ? g.registered_area_ha : g.dam_fill_pct]));
  const chart = items.map((i: any) => ({ name: crop(i.crop), demand: Math.round(i.required_kt), production: i.expected_production_kt ? Math.round(i.expected_production_kt) : 0 }));
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">{t("ministry.home.title")}</h1>
          <p className="text-sm text-ink-500">{t("ministry.home.subtitle", { year: b.year })}</p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label={t("ministry.home.population")} value={num(b.population / 1e6, 2)} unit={t("units.million")} badge={<Quality q={b.population_quality} />} hint="World Bank (WDI / projections)" />
        <Stat label={t("ministry.home.kcal")} value={num(b.kcal_per_capita_day?.[0])} unit="kcal/j" badge={<Quality q="estimated" />} hint={`FAOSTAT FBS ${b.kcal_per_capita_day?.[1] ?? ""}`} />
        <Stat label={t("ministry.home.demand")} value={num(data.totals.demand_kt)} unit="kt" tone="water" badge={<Quality q="forecast" />} />
        <Stat label={t("ministry.home.expected")} value={num(data.totals.expected_kt)} unit="kt" badge={<Quality q="forecast" />} />
        <Stat label={t("ministry.home.deficits")} value={data.totals.deficit_crops} unit={`/ ${items.length}`} tone="danger" hint={t("ministry.home.deficitsHint")} />
      </div>

      <div className="grid gap-5 lg:grid-cols-5">
        <Card className="lg:col-span-3" title={t("ministry.home.map")} action={
          <Tabs value={layer} onChange={setLayer} items={[{ id: "alerts", label: t("ministry.home.layerAlerts") }, { id: "farms", label: t("ministry.home.layerFarms") }, { id: "dams", label: t("ministry.home.layerDams") }]} />}>
          <TunisiaMap values={values} scale={layer === "alerts" ? "red" : layer === "dams" ? "blue" : "green"}
            format={(v) => v === null || v === undefined ? t("common.noData") : layer === "alerts" ? `${v} ${t("nav.alerts").toLowerCase()}` : layer === "farms" ? `${num(v, 1)} ha` : `${num(v, 1)} %`} />
          {layer === "dams" && !data.dams.length && <div className="mt-3"><Note tone="sun">{t("ministry.home.damsMissing")}</Note></div>}
        </Card>
        <Card className="lg:col-span-2" title={t("ministry.home.alerts")} subtitle={t("ministry.home.alertsSub")}>
          <AlertList alerts={data.alerts} gov={gov} compact />
        </Card>
      </div>

      <Card title={t("ministry.home.balance")} subtitle={t("ministry.home.balanceSub", { margin: b.safety_margin_pct })}>
        <div className="h-72" dir="ltr">
          <ResponsiveContainer>
            <BarChart data={chart} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e7efe9" />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: any) => `${num(v)} kt`} />
              <Legend />
              <Bar dataKey="demand" name={t("ministry.home.required")} fill="#1c6fb8" radius={[6, 6, 0, 0]} />
              <Bar dataKey="production" name={t("ministry.home.expectedShort")} fill="#2f9e44" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-2 text-xs text-ink-500">{t("ministry.home.balanceNote")}</p>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title={t("ministry.home.platform")} subtitle={t("ministry.home.platformSub")}>
          {Object.keys(data.platform).length ? (
            <table className="table"><thead><tr><th>{t("common.crop")}</th><th>{t("common.area")}</th><th>{t("common.production")}</th><th>{t("common.water")}</th></tr></thead>
              <tbody>{Object.entries<any>(data.platform).map(([c, v]) => <tr key={c}><td>{crop(c)}</td><td>{num(v.area_ha, 1)} ha</td><td>{num(v.production_t, 1)} t</td><td>{num(v.water_m3)} m³</td></tr>)}</tbody></table>
          ) : <p className="text-sm text-ink-500">{t("ministry.home.noFarms")}</p>}
        </Card>
        <Card title={t("ministry.home.missing")} subtitle={t("ministry.home.missingSub")}>
          <ul className="space-y-2 text-sm">
            {data.missing_data.map((m: any) => (
              <li key={m.indicator} className="flex items-center justify-between gap-2">
                <span><span className="font-semibold">{t(`indicators.${m.indicator}`, { defaultValue: m.indicator })}</span> <span className="text-xs text-ink-500">— {m.source}</span></span>
                {m.status === "available" ? <Badge>{m.records}</Badge> : <Badge tone="danger">{t("common.missing")}</Badge>}
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}
