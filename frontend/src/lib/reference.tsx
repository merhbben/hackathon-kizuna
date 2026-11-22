import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { api } from "./api";

export type CropRef = { code: string; name: { fr: string; ar: string }; color: string; category: string; perennial: boolean; cycle_days: number; storage: any; planting_months: [number, number][] };
type Ref = { crops: Record<string, CropRef>; govs: Record<string, { fr: string; ar: string }>; geo: any | null };

const RefCtx = createContext<Ref>({ crops: {}, govs: {}, geo: null });

export function ReferenceProvider({ children }: { children: ReactNode }) {
  const [ref, setRef] = useState<Ref>({ crops: {}, govs: {}, geo: null });
  useEffect(() => {
    let alive = true;
    const load = (attempt: number) =>
      Promise.all([api<CropRef[]>("/api/reference/crops"), api<any>("/api/reference/governorates")]).then(([c, g]) => {
        if (alive) setRef({ crops: Object.fromEntries(c.map((x) => [x.code, x])), govs: g.names, geo: g.geojson });
      }).catch(() => { if (alive && attempt < 5) setTimeout(() => load(attempt + 1), 1000 * (attempt + 1)); });
    load(0);
    return () => { alive = false; };
  }, []);
  return <RefCtx.Provider value={ref}>{children}</RefCtx.Provider>;
}

export function useRef_() { return useContext(RefCtx); }

export function useNames() {
  const { i18n } = useTranslation();
  const r = useContext(RefCtx);
  const l: "fr" | "ar" = i18n.language === "ar" ? "ar" : "fr";
  return {
    crop: (code: string) => r.crops[code]?.name[l] || code,
    color: (code: string) => r.crops[code]?.color || "#7a8a80",
    gov: (code: string) => r.govs[code]?.[l] || code,
    crops: r.crops, govs: r.govs, geo: r.geo, lang: l,
  };
}
