import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";
import { useApi } from "../../lib/hooks";
import { num } from "../../lib/format";
import { useNames } from "../../lib/reference";
import { Badge, Card, Empty, ErrorBox, Loader, Note, Stat } from "../../components/ui";

export default function Reserves() {
  const { t } = useTranslation();
  const { crop, gov } = useNames();
  const { data, loading, error, reload } = useApi<any>("/api/ministry/reserves-energy");
  const [note, setNote] = useState<Record<number, string>>({});
  if (loading) return <Loader />;
  if (error) return <ErrorBox error={error} />;
  const decide = async (id: number, decision: "approved" | "rejected") => {
    await api(`/api/ministry/contributions/${id}/decision`, { method: "POST", json: { decision, note: note[id] || null } });
    reload();
  };
  const stocks = Object.fromEntries(data.reserve_stocks.map((s: any) => [s.crop, s]));
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold">{t("ministry.reserves.title")}</h1>
        <p className="text-sm text-ink-500">{t("ministry.reserves.subtitle")}</p>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label={t("ministry.reserves.coldT")} value={num(data.totals.cold_storage_t)} unit="t" tone="water" />
        <Stat label={t("ministry.reserves.coldKw")} value={num(data.totals.cold_capacity_kw, 1)} unit="kW" tone="water" />
        <Stat label={t("ministry.reserves.pv")} value={num(data.totals.pv_kwp, 1)} unit="kWc" tone="sun" />
        <Stat label={t("ministry.reserves.battery")} value={num(data.totals.battery_kwh)} unit="kWh" tone="sun" />
      </div>

      <Card title={t("ministry.reserves.contributions")} subtitle={t("ministry.reserves.contributionsSub")}>
        {!data.contributions.length ? <Empty title={t("ministry.reserves.noContrib")} /> : (
          <div className="space-y-3">
            {data.contributions.map((c: any) => (
              <div key={c.id} className="rounded-xl border border-brand-100 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="font-semibold">{c.farm} <span className="text-xs text-ink-500">· {gov(c.governorate)}</span></div>
                  <Badge tone={c.status === "approved" ? "brand" : c.status === "rejected" ? "danger" : "sun"}>{t(`status.${c.status}`)}</Badge>
                </div>
                <div className="mt-2 flex flex-wrap gap-2 text-sm">
                  {Object.entries<any>(c.proposal.items || {}).map(([k, v]) => (
                    <span key={k} className="rounded-lg bg-brand-50 px-2 py-1">{crop(k)} : <b>{num(v.proposed_pct, 1)} %</b> = {num(v.proposed_t, 1)} t <span className="text-xs text-ink-500">({t(`storage.${v.storage}`)})</span></span>
                  ))}
                </div>
                {c.status === "pending" && (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <input className="input !w-auto flex-1" placeholder={t("ministry.reserves.decisionNote")} value={note[c.id] || ""} onChange={(e) => setNote({ ...note, [c.id]: e.target.value })} />
                    <button className="btn-primary" onClick={() => decide(c.id, "approved")}>{t("common.approve")}</button>
                    <button className="btn-danger" onClick={() => decide(c.id, "rejected")}>{t("common.reject")}</button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        <div className="mt-3"><Note tone="sun">{t("ministry.reserves.legal")}</Note></div>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title={t("ministry.reserves.targets")} subtitle={t("ministry.reserves.targetsSub")}>
          <table className="table"><thead><tr><th>{t("common.crop")}</th><th>{t("ministry.reserves.target")}</th><th>{t("ministry.reserves.stock")}</th></tr></thead>
            <tbody>{data.reserve_targets.map((r: any) => (
              <tr key={r.crop}><td>{crop(r.crop)}</td><td>{num(r.reserve_target_kt)} kt</td>
                <td>{stocks[r.crop] ? `${num(stocks[r.crop].kt)} kt (${stocks[r.crop].period})` : <Badge tone="danger">{t("common.missing")}</Badge>}</td></tr>))}</tbody></table>
        </Card>
        <Card title={t("ministry.reserves.dams")} subtitle="ONAGRI">
          {!data.dams.length ? <Note tone="sun">{t("ministry.home.damsMissing")}</Note> : (
            <table className="table"><thead><tr><th>{t("ministry.reserves.dam")}</th><th>{t("farm.governorate")}</th><th>Mm³</th><th>%</th></tr></thead>
              <tbody>{data.dams.map((d: any) => <tr key={d.dam}><td>{d.dam}</td><td>{gov(d.governorate)}</td><td>{num(d.storage_mm3, 1)} / {num(d.capacity_mm3)}</td><td>{d.fill_pct !== undefined ? <Badge tone={d.fill_pct < 30 ? "danger" : d.fill_pct < 50 ? "sun" : "water"}>{num(d.fill_pct, 1)} %</Badge> : "—"}</td></tr>)}</tbody></table>
          )}
        </Card>
      </div>

      <Card title={t("ministry.reserves.farms")} subtitle={t("ministry.reserves.farmsSub")}>
        {!data.farms.length ? <Empty title={t("ministry.home.noFarms")} /> : (
          <div className="overflow-x-auto">
            <table className="table min-w-[860px]"><thead><tr><th>{t("farm.name")}</th><th>{t("farm.governorate")}</th><th>{t("common.area")}</th><th>{t("ministry.reserves.size")}</th><th>{t("ministry.reserves.coldT")}</th><th>PV</th><th>{t("ministry.reserves.battery")}</th><th>{t("energy.autonomy")}</th><th>{t("energy.exportCap")}</th></tr></thead>
              <tbody>{data.farms.map((f: any) => (
                <tr key={f.farm_id}><td className="font-semibold">{f.name}</td><td>{gov(f.governorate)}</td><td>{num(f.area_ha, 2)} ha</td>
                  <td>{f.large ? <Badge tone="water">{t("farm.large")}</Badge> : <Badge tone="slate">{t("farm.small")}</Badge>}</td>
                  <td>{num(f.cold_t, 1)} t</td><td>{num(f.kwp, 1)} kWc</td><td>{num(f.battery_kwh)} kWh</td><td>{f.autonomy_hours ? `${num(f.autonomy_hours, 1)} h` : "—"}</td><td>{num(f.export_within_cap_kwh)} kWh</td></tr>))}</tbody></table>
          </div>
        )}
      </Card>
    </div>
  );
}
