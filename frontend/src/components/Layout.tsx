import { NavLink, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../lib/auth";
import { api } from "../lib/api";

export function LanguageToggle({ compact = false }: { compact?: boolean }) {
  const { i18n } = useTranslation();
  const { user } = useAuth();
  const next = i18n.language === "ar" ? "fr" : "ar";
  const change = () => {
    i18n.changeLanguage(next);
    if (user) api("/api/auth/me", { method: "PATCH", json: { language: next } }).catch(() => undefined);
  };
  return (
    <button onClick={change} className="btn-ghost !px-3 !py-2" aria-label="Français / تونسي">
      <span className={i18n.language === "fr" ? "text-brand-700" : "text-ink-400"}>Français</span>
      <span className="text-ink-400">/</span>
      <span className={`font-arabic ${i18n.language === "ar" ? "text-brand-700" : "text-ink-400"}`}>تونسي</span>
      {!compact && <span className="sr-only">language</span>}
    </button>
  );
}

const ICONS: Record<string, string> = { home: "🗺️", plan: "🌾", reserves: "❄️", alerts: "🔔", terrain: "📐", myplan: "🧩", water: "💧", harvest: "🧺" };

export default function Layout() {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const nav = user?.role === "ministry"
    ? [{ to: "/ministry", id: "home" }, { to: "/ministry/plan", id: "plan" }, { to: "/ministry/reserves", id: "reserves" }, { to: "/ministry/alerts", id: "alerts" }]
    : [{ to: "/farm/plan", id: "myplan" }, { to: "/farm/water", id: "water" }, { to: "/farm/harvest", id: "harvest" }];
  return (
    <div className="min-h-full pb-20 md:pb-0">
      <header className="sticky top-0 z-30 border-b border-brand-100 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-3">
          <div className="flex items-center gap-2">
            <img src="/favicon.svg" alt="" className="h-8 w-8" />
            <div className="leading-tight">
              <div className="text-sm font-bold text-brand-800">AgroSphere AI</div>
              <div className="text-[10px] text-ink-500">{user?.role === "ministry" ? t("layout.ministry") : t("layout.farmer")}</div>
            </div>
          </div>
          <nav className="mx-4 hidden flex-1 items-center gap-1 md:flex">
            {nav.map((n) => (
              <NavLink key={n.to} to={n.to} end className={({ isActive }) => `rounded-xl px-3 py-2 text-sm font-semibold transition ${isActive ? "bg-brand-600 text-white" : "text-ink-700 hover:bg-brand-50"}`}>
                <span aria-hidden className="me-1.5">{ICONS[n.id]}</span>{t(`nav.${n.id}`)}
              </NavLink>
            ))}
          </nav>
          <div className="ms-auto flex items-center gap-2">
            {user?.role === "farmer" && <NavLink to="/farm/terrain" className="hidden text-xs font-semibold text-ink-500 hover:text-brand-700 sm:inline">⚙ {t("nav.terrainData")}</NavLink>}
            <LanguageToggle compact />
            <button onClick={logout} className="btn-ghost !px-3 !py-2" title={user?.email}>{t("layout.logout")}</button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-5">
        <Outlet />
      </main>
      <nav className={`fixed inset-x-0 bottom-0 z-30 grid ${nav.length === 3 ? "grid-cols-3" : "grid-cols-4"} border-t border-brand-100 bg-white md:hidden`}>
        {nav.map((n) => (
          <NavLink key={n.to} to={n.to} end className={({ isActive }) => `flex flex-col items-center gap-0.5 py-2 text-[11px] font-semibold ${isActive ? "text-brand-700" : "text-ink-500"}`}>
            <span aria-hidden className="text-lg">{ICONS[n.id]}</span>{t(`nav.${n.id}`)}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
