import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, download } from "../../lib/api";
import { useApi } from "../../lib/hooks";
import { date, num } from "../../lib/format";
import { useNames } from "../../lib/reference";
import { Badge, Card, Empty, ErrorBox, Field, Loader, Note, Quality, Tabs } from "../../components/ui";

const SEV: Record<string, "danger" | "sun" | "slate"> = { critical: "danger", warning: "sun", info: "slate" };
const KIND_ICON: Record<string, string> = { drought: "☀️", shortage: "📉", surplus: "📈", power: "⚡", water: "💧", data: "🗂️" };

export function AlertList({ alerts, gov, compact = false }: { alerts: any[]; gov: (c: string) => string; compact?: boolean }) {
  const { t, i18n } = useTranslation();
  if (!alerts.length) return <Empty icon="✅" title={t("alerts.none")} />;
  return (
    <ul className="space-y-2">
      {alerts.map((a) => (
        <li key={a.id} className="flex items-start gap-3 rounded-xl border border-brand-100 p-3">
          <span className="text-xl" aria-hidden>{KIND_ICON[a.kind] || "🔔"}</span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={SEV[a.severity]}>{t(`severity.${a.severity}`)}</Badge>
              {a.entity !== "TN" && <span className="text-xs text-ink-500">{gov(a.entity)}</span>}
              {a.evidence?.quality && <Quality q={a.evidence.quality} />}
            </div>
            <p className="mt-1 text-sm font-semibold">{a.title[i18n.language === "ar" ? "ar" : "fr"]}</p>
            {!compact && a.evidence?.start && <p className="text-xs text-ink-500">{date(a.evidence.start)} → {date(a.evidence.end)} · {num(a.evidence.rain_mm)} mm / {num(a.evidence.normal_mm)} mm (NASA POWER)</p>}
          </div>
        </li>
      ))}
    </ul>
  );
}

export default function AlertsManagement() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<"alerts" | "simulate" | "policy" | "data">("alerts");
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">{t("ministry.alerts.title")}</h1>
          <p className="text-sm text-ink-500">{t("ministry.alerts.subtitle")}</p>
        </div>
        <Tabs value={tab} onChange={setTab} items={[{ id: "alerts", label: t("ministry.alerts.tabAlerts") }, { id: "simulate", label: t("ministry.alerts.tabSim") }, { id: "policy", label: t("ministry.alerts.tabPolicy") }, { id: "data", label: t("ministry.alerts.tabData") }]} />
      </div>
      {tab === "alerts" && <AlertsTab />}
      {tab === "simulate" && <SimulationTab />}
      {tab === "policy" && <PolicyTab />}
      {tab === "data" && <DataTab />}
    </div>
  );
}

function AlertsTab() {
  const { t } = useTranslation();
  const { gov } = useNames();
  const { data, loading, error, setData } = useApi<any[]>("/api/ministry/alerts");
  const [busy, setBusy] = useState(false);
  const refresh = async () => { setBusy(true); try { setData(await api("/api/ministry/alerts/refresh", { method: "POST" })); } finally { setBusy(false); } };
  return (
    <Card title={t("ministry.alerts.active")} subtitle={t("ministry.alerts.activeSub")} action={<button className="btn-primary" onClick={refresh} disabled={busy}>{busy ? t("common.loading") : t("ministry.alerts.refresh")}</button>}>
      {loading ? <Loader /> : error ? <ErrorBox error={error} /> : <AlertList alerts={data || []} gov={gov} />}
    </Card>
  );
}

function SimulationTab() {
  const { t } = useTranslation();
  const { crop } = useNames();
  const [s, setS] = useState({ population_pct: 0, yield_pct: 0, rain_pct: 0, import_cut_pct: 0, margin_pct: 5 });
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  const run = async () => { setBusy(true); setErr(null); try { setRes(await api("/api/ministry/simulate", { method: "POST", json: s })); } catch (e) { setErr(e); } finally { setBusy(false); } };
  const sliders: [keyof typeof s, number, number][] = [["rain_pct", -60, 40], ["population_pct", -5, 10], ["yield_pct", -50, 30], ["import_cut_pct", 0, 100], ["margin_pct", 0, 20]];
  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <Card title={t("ministry.sim.title")} subtitle={t("ministry.sim.subtitle")}>
        <div className="space-y-4">
          {sliders.map(([k, min, max]) => (
            <Field key={k} label={<span className="flex justify-between"><span>{t(`ministry.sim.${k}`)}</span><span className="tabular-nums text-brand-700">{s[k] > 0 && k !== "margin_pct" && k !== "import_cut_pct" ? "+" : ""}{s[k]} %</span></span>}>
              <input type="range" min={min} max={max} value={s[k]} onChange={(e) => setS({ ...s, [k]: Number(e.target.value) })} className="w-full accent-brand-600" />
            </Field>
          ))}
          <button className="btn-primary w-full" onClick={run} disabled={busy}>{busy ? t("common.loading") : t("ministry.sim.run")}</button>
          <ErrorBox error={err} />
          <Note tone="sun">{t("ministry.sim.note")}</Note>
        </div>
      </Card>
      <Card className="lg:col-span-2" title={t("ministry.sim.results")} subtitle={res ? t("ministry.sim.resultsSub", { year: res.year, pop: num(res.population / 1e6, 2) }) : undefined}>
        {!res ? <Empty icon="🧪" title={t("ministry.sim.empty")} /> : (
          <>
            <div className="h-72" dir="ltr">
              <ResponsiveContainer>
                <BarChart data={res.items.map((i: any) => ({ name: crop(i.crop), base: i.gap_base_kt, sim: i.gap_sim_kt }))}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e7efe9" /><XAxis dataKey="name" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v: any) => `${num(v)} kt`} /><Legend />
                  <Bar dataKey="base" name={t("ministry.sim.base")} fill="#a3b8ab" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="sim" name={t("ministry.sim.scenario")} fill="#1c6fb8" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <table className="table mt-3"><thead><tr><th>{t("common.crop")}</th><th>{t("ministry.sim.base")}</th><th>{t("ministry.sim.scenario")}</th><th>{t("ministry.plan.water")}</th><th>{t("ministry.plan.market")}</th></tr></thead>
              <tbody>{res.items.map((i: any) => <tr key={i.crop}><td>{crop(i.crop)}</td><td>{num(i.gap_base_kt)} kt</td><td className={(i.gap_sim_kt || 0) < 0 ? "text-danger-700 font-semibold" : "text-brand-700 font-semibold"}>{num(i.gap_sim_kt)} kt</td><td>{num(i.water_sim_mm3, 1)} Mm³</td><td>{i.price_pressure ? t(`pressure.${i.price_pressure.direction}`) : "—"}</td></tr>)}</tbody></table>
          </>
        )}
      </Card>
    </div>
  );
}

function PolicyTab() {
  const { t } = useTranslation();
  const { data, loading, error, setData } = useApi<any[]>("/api/ministry/policy");
  const [edit, setEdit] = useState<Record<string, string>>({});
  const [err, setErr] = useState<any>(null);
  if (loading) return <Loader />;
  if (error) return <ErrorBox error={error} />;
  const save = async (key: string, validate: boolean) => {
    setErr(null);
    try {
      const raw = edit[key] ?? JSON.stringify(data!.find((x) => x.key === key)!.value);
      const value = raw.trim() === "" ? null : JSON.parse(raw);
      setData(await api(`/api/ministry/policy/${encodeURIComponent(key)}`, { method: "PUT", json: { value, validate } }));
      setEdit((e) => { const n = { ...e }; delete n[key]; return n; });
    } catch (e) { setErr(e instanceof SyntaxError ? { message: "invalid_json" } : e); }
  };
  return (
    <Card title={t("ministry.policy.title")} subtitle={t("ministry.policy.subtitle")}>
      <ErrorBox error={err} />
      <div className="divide-y divide-brand-50">
        {data!.map((p) => (
          <div key={p.key} className="grid gap-2 py-3 md:grid-cols-12 md:items-center">
            <div className="md:col-span-4">
              <div className="text-sm font-semibold">{t(`policy.${p.key.replace(/\./g, "_")}`, { defaultValue: p.key })}</div>
              <div className="text-[11px] text-ink-500">{p.source}</div>
            </div>
            <input className="input font-mono md:col-span-4" value={edit[p.key] ?? JSON.stringify(p.value)} onChange={(e) => setEdit({ ...edit, [p.key]: e.target.value })} />
            <div className="flex items-center gap-2 md:col-span-4 md:justify-end">
              <Badge tone={p.status === "validated" ? "brand" : "sun"}>{t(`status.${p.status}`)}</Badge>
              <button className="btn-ghost !py-1.5" onClick={() => save(p.key, false)}>{t("common.save")}</button>
              <button className="btn-primary !py-1.5" onClick={() => save(p.key, true)}>{t("common.validate")}</button>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function DataTab() {
  const { t } = useTranslation();
  const ds = useApi<any>("/api/ministry/data-sources");
  const models = useApi<any[]>("/api/ministry/models");
  const [imp, setImp] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const upload = async (f: File) => {
    const form = new FormData(); form.append("file", f);
    setImp(await api("/api/ministry/data-import", { method: "POST", form })); ds.reload();
  };
  const refresh = async (key: string) => { setBusy(key); try { await api(`/api/ministry/data-sources/${key}/refresh`, { method: "POST" }); ds.reload(); } catch (e) { setImp({ error: e }); } finally { setBusy(null); } };
  const retrain = async () => { setBusy("models"); try { await api("/api/ministry/models/retrain", { method: "POST" }); models.reload(); } finally { setBusy(null); } };
  const sel = (models.data || []).filter((m) => m.selected);
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card title={t("ministry.data.sources")} subtitle={t("ministry.data.sourcesSub")}>
        {ds.loading ? <Loader /> : ds.data && (
          <>
            <table className="table"><thead><tr><th>Source</th><th>{t("ministry.data.last")}</th><th>{t("ministry.data.records")}</th><th></th></tr></thead>
              <tbody>{ds.data.status.map((s: any) => <tr key={s.key}><td className="font-semibold">{s.key}</td><td className="text-xs">{s.last_success ? date(s.last_success) : "—"}</td><td>{num(s.records)}</td>
                <td>{["faostat", "worldbank", "nasa_power"].includes(s.key) && <button className="btn-ghost !px-2 !py-1 text-xs" disabled={busy === s.key} onClick={() => refresh(s.key)}>{busy === s.key ? "…" : t("ministry.data.refresh")}</button>}</td></tr>)}</tbody></table>
            <div className="mt-3 flex flex-wrap gap-2">{ds.data.datasets.map((d: any) => <span key={d.dataset + d.quality} className="chip bg-slate-100 text-slate-700">{d.dataset} <Quality q={d.quality} /> {num(d.records)}</span>)}</div>
            <h3 className="mt-4 text-sm font-bold">{t("ministry.data.notIntegrated")}</h3>
            <ul className="mt-1 space-y-1 text-xs text-ink-500">{ds.data.not_integrated.map((n: any) => <li key={n.source}><b>{n.source}</b> — {n.reason}</li>)}</ul>
          </>
        )}
      </Card>
      <Card title={t("ministry.data.import")} subtitle={t("ministry.data.importSub")}>
        <input type="file" accept=".csv" className="input" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-50 p-3 text-[11px]" dir="ltr">indicator,entity,item,period,value,unit,quality,source_url,note{"\n"}dam_storage_mm3,TN-31,Sidi Salem,2026-11-20,250.3,Mm3,official,https://www.onagri.nat.tn/...,</pre>
        {imp && (imp.error ? <ErrorBox error={imp.error} /> : <p className="mt-2 text-sm">{t("ministry.data.imported", { n: imp.imported })} {imp.errors?.length ? <span className="text-danger-700">· {imp.errors.length} {t("ministry.data.errors")}</span> : null}</p>)}
        <div className="mt-4 flex flex-wrap gap-2">
          <button className="btn-ghost" onClick={() => download("/api/ministry/reports/balance.csv", "bilan.csv")}>{t("ministry.data.report")}</button>
        </div>
      </Card>
      <Card className="lg:col-span-2" title={t("ministry.data.models")} subtitle={t("ministry.data.modelsSub")} action={<button className="btn-ghost" onClick={retrain} disabled={busy === "models"}>{busy === "models" ? t("common.loading") : t("ministry.data.retrain")}</button>}>
        {models.loading ? <Loader /> : (
          <div className="overflow-x-auto">
            <table className="table min-w-[720px]"><thead><tr><th>{t("ministry.data.task")}</th><th>{t("common.crop")}</th><th>{t("ministry.data.selected")}</th><th>MAPE</th><th>{t("ministry.data.compare")}</th><th>{t("ministry.data.version")}</th></tr></thead>
              <tbody>{sel.map((m) => {
                const others = (models.data || []).filter((x) => x.task === m.task && x.item === m.item);
                return <tr key={m.task + m.item}><td className="text-xs">{t(`tasks.${m.task}`)}</td><td>{m.item}</td><td><Badge tone={["lightgbm", "xgboost"].includes(m.model) ? "water" : "slate"}>{m.model}</Badge></td><td className="tabular-nums">{num(m.mape_pct, 2)} %</td>
                  <td className="text-[11px] text-ink-500">{others.map((o) => `${o.model} ${num(o.mape_pct, 1)}`).join(" · ")}</td><td className="font-mono text-[11px]">{m.version} · {m.data_signature}</td></tr>;
              })}</tbody></table>
          </div>
        )}
        <div className="mt-3"><Note>{t("ministry.data.modelsNote")}</Note></div>
      </Card>
    </div>
  );
}
