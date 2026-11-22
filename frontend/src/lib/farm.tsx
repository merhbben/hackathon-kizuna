import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "./api";

type FarmCtx = {
  farms: any[]; farm: any | null; plan: any | null; loading: boolean;
  select: (id: number) => void; reloadFarms: () => Promise<void>; reloadPlan: () => Promise<void>;
  setFarm: (f: any) => void; setPlan: (p: any) => void;
};
const Ctx = createContext<FarmCtx>(null as any);
const KEY = "agrosphere.farm";

export function FarmProvider({ children }: { children: ReactNode }) {
  const [farms, setFarms] = useState<any[]>([]);
  const [farm, setFarmState] = useState<any | null>(null);
  const [plan, setPlan] = useState<any | null>(null);
  const [farmsLoading, setLoading] = useState(true);
  const [planLoading, setPlanLoading] = useState(false);
  const loading = farmsLoading || planLoading;

  const reloadFarms = useCallback(async () => {
    const list = await api<any[]>("/api/farms");
    setFarms(list);
    let id: number | null = null;
    try { id = Number(localStorage.getItem(KEY)) || null; } catch { /* ignore */ }
    const chosen = list.find((f) => f.id === (farm?.id ?? id)) || list[0] || null;
    setFarmState(chosen);
    setLoading(false);
  }, [farm?.id]);

  const seq = useRef(0);
  const reloadPlan = useCallback(async () => {
    const my = ++seq.current;                       // ignore responses of superseded requests
    if (!farm || !farm.plans?.length) { setPlan(null); setPlanLoading(false); return; }
    setPlanLoading(true);
    try { const p = await api(`/api/farms/${farm.id}/plans/latest`); if (my === seq.current) setPlan(p); }
    catch { if (my === seq.current) setPlan(null); }
    finally { if (my === seq.current) setPlanLoading(false); }
  }, [farm?.id, farm?.plans?.length]);

  useEffect(() => { reloadFarms().catch(() => setLoading(false)); /* eslint-disable-next-line */ }, []);
  useEffect(() => { reloadPlan(); }, [reloadPlan]);

  const select = (id: number) => {
    const f = farms.find((x) => x.id === id);
    if (f) { setFarmState(f); try { localStorage.setItem(KEY, String(id)); } catch { /* ignore */ } }
  };
  const setFarm = (f: any) => { setFarmState(f); setFarms((l) => (l.some((x) => x.id === f.id) ? l.map((x) => (x.id === f.id ? f : x)) : [...l, f])); };
  return <Ctx.Provider value={{ farms, farm, plan, loading, select, reloadFarms, reloadPlan, setFarm, setPlan }}>{children}</Ctx.Provider>;
}

export const useFarm = () => useContext(Ctx);
