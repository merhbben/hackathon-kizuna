/** Inputs → AgroBrain models → optimised plan, with the real figures of THIS farm at every step
 *  (from plan.summary.pipeline, computed by the backend; nothing is computed here). */
import { useTranslation } from "react-i18next";
import { num } from "../lib/format";
import { useNames } from "../lib/reference";

function Step({ n, title, lines, tone = "slate", warn }: { n: string; title: string; lines: React.ReactNode[]; tone?: "slate" | "brand" | "water"; warn?: boolean }) {
  const bg = tone === "brand" ? "bg-brand-50 border-brand-200" : tone === "water" ? "bg-water-50 border-water-300/60" : "bg-white border-brand-100";
  return (
    <div className={`min-w-0 rounded-xl border p-3 ${bg} ${warn ? "ring-2 ring-sun-300" : ""}`}>
      <div className="mb-1 flex items-center gap-2 text-xs font-bold text-ink-700"><span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-ink-900 text-[10px] text-white">{n}</span>{title}</div>
      <ul className="space-y-0.5 text-[12px] leading-snug text-ink-700">{lines.filter(Boolean).map((l, i) => <li key={i}>{l}</li>)}</ul>
    </div>
  );
}

const Arrow = () => <div className="hidden items-center justify-center text-2xl text-brand-500 xl:flex" aria-hidden>→</div>;

export function Pipeline({ pl, summary }: { pl: any; summary: any }) {
  const { t } = useTranslation();
  const { crop } = useNames();
  if (!pl) return null;
  const I = pl.inputs, W = pl.water, O = pl.optimisation;
  const limits: string[] = W.limits || [];
  const quotaLimit = limits.includes("quota");
  const waterLimit = limits.some((l) => l.startsWith("water_"));
  const irrigated = Object.entries<number>(summary.optimizer?.irrigated_ha || {});
  const rainfed = Object.entries<number>(summary.optimizer?.rainfed_ha || {});
  return (
    <section className="rounded-xl2 border border-brand-100 bg-white p-4 shadow-sm">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-bold">{t("pl.title")}</h2>
        <span className="text-xs text-ink-500">{t("pl.sub")}</span>
      </div>
      <div className="grid gap-3 xl:grid-cols-[1fr_auto_2.4fr_auto_1fr]">
        {/* 1. inputs */}
        <Step n="1" title={t("pl.inputs")} lines={[
          <>{t(I.source === "plan_file" ? "pl.fromPlan" : "pl.fromMap")} · <b>{I.vertices}</b> {t("pl.vertices")} · <b>{num(I.area_ha, 2)} ha</b></>,
          <>{t("pl.location")} : {t(`pl.loc_${I.location_quality}`, { defaultValue: I.location_quality })}</>,
          <>{t("pl.sources", { n: I.sources })} : {I.flow_m3h.map((f: number | null, i: number) => `F${i + 1} ${f ?? "?"} m³/h`).join(" · ") || "—"}</>,
          I.quota_m3 ? <>{t("pl.quota")} : <b>{num(I.quota_m3)} m³/{t("p2.year")}</b></> : null,
          <>{t("pl.pumps")} : {I.pumps_kw.length ? I.pumps_kw.map((k: number) => `${k} kW`).join(" · ") : "?"}{I.pv_kwc ? ` · PV ${I.pv_kwc} kWc` : ""}</>,
          <>{t("p2.irrigTech")} : {t(`method.${I.irrigation_method}`)}</>,
        ]} />
        <Arrow />
        {/* 2. models */}
        <div className="grid min-w-0 gap-2 rounded-xl border border-dashed border-brand-200 p-2 sm:grid-cols-2 lg:grid-cols-3">
          <div className="text-[11px] font-bold uppercase tracking-wide text-brand-700 sm:col-span-2 lg:col-span-3">🧠 {t("pl.models")}</div>
          <Step n="2a" tone="water" title={t("pl.climate")} lines={[
            <>{t("p2.rain")} <b>{num(pl.climate.rain_mm)} mm</b> · ET0 <b>{num(pl.climate.et0_mm)} mm</b>/{t("p2.year")}</>,
            pl.climate.frost_months.length ? t("pl.frost", { n: pl.climate.frost_months.length }) : t("pl.noFrost"),
          ]} />
          <Step n="2b" title={t("pl.suitability")} lines={[
            <>{t("pl.suitable", { n: pl.suitability.suitable, of: pl.suitability.evaluated })}</>,
            Object.keys(pl.suitability.excluded).length ? <>{t("pl.excluded")} : {Object.entries<number>(pl.suitability.excluded).map(([r, n]) => `${t(`reasons.${r}`, { defaultValue: r })} (${n})`).join(", ")}</> : null,
            <>{t("p2.soil")} : {t(`texture.${pl.soil.texture}`, { defaultValue: pl.soil.texture })} {String(pl.soil.source).startsWith("missing") ? <span className="text-sun-600">({t("pl.soilDefault")})</span> : String(pl.soil.source).startsWith("SoilGrids") ? <span className="text-ink-500">(SoilGrids)</span> : null}</>,
          ]} />
          <Step n="2c" tone="water" warn={quotaLimit || waterLimit} title={t("pl.water")} lines={[
            <>{t("pl.available")} : <b>{num(W.quota_m3 ?? W.annual_capacity_m3)} m³/{t("p2.year")}</b> {W.quota_m3 ? `(${t("pl.quotaShort")})` : `(${t("pl.pumping")})`}</>,
            W.need_full_irrigation_m3 != null ? <>{t("pl.needAll")} : <b>{num(W.need_full_irrigation_m3)} m³</b></> : null,
            <>{t("pl.used")} : <b>{num(W.used_m3)} m³</b></>,
          ]} />
          <Step n="2d" tone="brand" warn={quotaLimit || waterLimit} title={t("pl.optimisation")} lines={[
            <>{t("pl.irrigated")} : <b>{num(O.irrigated_ha, 2)} ha</b>{irrigated.length ? ` (${irrigated.map(([c, a]) => `${crop(c)} ${num(a, 2)}`).join(", ")})` : ""}</>,
            O.rainfed_ha > 0 ? <>{t("pl.rainfed")} : <b>{num(O.rainfed_ha, 2)} ha</b> ({rainfed.map(([c, a]) => `${crop(c)} ${num(a, 2)}`).join(", ")})</> : null,
            O.unused_ha > 0.01 ? <span className="text-sun-600">{t("pl.unused")} : <b>{num(O.unused_ha, 2)} ha</b></span> : null,
            <>{t("pl.limit")} : <b>{limits.length ? limits.map((l) => t(`pl.lim_${l.startsWith("water_") ? "water" : l}`, { m: l.slice(6) })).join(", ") : t("pl.lim_none")}</b></>,
          ]} />
          <Step n="2e" title={t("pl.partition")} lines={[
            <>{t("pl.parcels", { n: pl.partition.parcels })} · {num(pl.partition.productive_ha, 2)} ha</>,
            <>{t("pl.infra")} : {num(pl.partition.infrastructure_ha, 2)} ha</>,
            <>{t("pl.nearSources")}</>,
          ]} />
          <Step n="2f" tone="water" title={t("pl.irrigEnergy")} lines={[
            <>{t("pl.season")} : <b>{num(pl.irrigation.season_m3)} m³</b> · <b>{num(pl.energy.pump_kwh)} kWh</b></>,
            pl.irrigation.conflicts ? <span className="text-danger-700">{t("p2.pumpConflict", { n: pl.irrigation.conflicts })}</span> : <>{t("pl.noConflict")}</>,
            pl.energy.pv_kwc_recommended ? <>{t("pl.pvReco")} : {num(pl.energy.pv_kwc_recommended, 1)} kWc</> : null,
          ]} />
          {pl.cold_store && <Step n="2g" tone="water" title={`❄ ${t("cb.pipeline")} (> ${num(pl.cold_store.threshold_ha)} ha)`} lines={pl.cold_store.chosen.length ? [
            <>{t("cb.pipeStored", { crops: pl.cold_store.chosen.map((c: string) => crop(c)).join(" + "), v: num(pl.cold_store.volume_m3) })}</>,
            pl.cold_store.kwp != null ? <>{t("cb.pipeEnergy", { kwh: num(pl.cold_store.annual_kwh), kwp: num(pl.cold_store.kwp, 1), n: pl.cold_store.panels, cov: num(pl.cold_store.solar_coverage_pct, 1) })}</> : null,
          ] : [<span className="text-sun-600">{t(`cb.reason_${pl.cold_store.reason}`)}</span>]} />}
        </div>
        <Arrow />
        {/* 3. output */}
        <Step n="3" tone="brand" title={t("pl.output")} lines={[
          <><b>{t("pl.parcels", { n: pl.partition.parcels })}</b> · {t("pl.crops", { n: O.crops })}</>,
          <>{t("pl.cultivated")} : <b>{num(pl.partition.productive_ha, 2)} / {num(I.area_ha, 2)} ha</b></>,
          <>{t("plan.production")} : <b>{num(Object.values<number>(summary.production_t || {}).reduce((a, b) => a + b, 0), 1)} t</b></>,
          <>{t("p2.water")} : <b>{num(summary.water_m3)} m³</b></>,
        ]} />
      </div>
      {(quotaLimit || waterLimit) && (
        <p className="mt-3 rounded-lg bg-sun-100/70 px-3 py-2 text-sm text-ink-900">
          💡 {t(quotaLimit ? "pl.whyQuota" : "pl.whyWater", { avail: num(W.quota_m3 ?? W.annual_capacity_m3), need: num(W.need_full_irrigation_m3), irr: num(O.irrigated_ha, 2), rf: num(O.rainfed_ha, 2), un: num(O.unused_ha, 2) })}
        </p>
      )}
    </section>
  );
}
