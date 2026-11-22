import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

export function Card({ title, subtitle, action, children, className = "" }: { title?: ReactNode; subtitle?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card p-4 sm:p-5 ${className}`}>
      {(title || action) && (
        <header className="mb-4 flex flex-wrap items-start justify-between gap-2">
          <div>
            {title && <h2 className="text-base font-bold text-ink-900">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-ink-500">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, unit, hint, tone = "brand", badge }: { label: ReactNode; value: ReactNode; unit?: string; hint?: ReactNode; tone?: "brand" | "water" | "sun" | "danger"; badge?: ReactNode }) {
  const tones = { brand: "text-brand-700 bg-brand-50", water: "text-water-700 bg-water-50", sun: "text-sun-600 bg-sun-100", danger: "text-danger-700 bg-danger-50" };
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-ink-500">{label}</span>
        {badge}
      </div>
      <div className={`mt-2 inline-flex items-baseline gap-1 rounded-lg px-2 py-1 ${tones[tone]}`}>
        <span className="text-2xl font-bold tabular-nums">{value}</span>
        {unit && <span className="text-sm font-semibold opacity-80">{unit}</span>}
      </div>
      {hint && <p className="mt-2 text-xs text-ink-500">{hint}</p>}
    </div>
  );
}

const QUALITY_STYLE: Record<string, string> = {
  official: "bg-brand-100 text-brand-800",
  official_national_average: "bg-brand-100 text-brand-800",
  official_governorate: "bg-brand-100 text-brand-800",
  measured: "bg-water-100 text-water-700",
  estimated: "bg-sun-100 text-sun-600",
  estimated_national_average: "bg-sun-100 text-sun-600",
  forecast: "bg-purple-100 text-purple-700",
  manual: "bg-slate-100 text-slate-700",
  missing: "bg-danger-50 text-danger-700",
};

/** Provenance badge — every number in the app shows whether it is official, measured, estimated or forecast. */
export function Quality({ q }: { q?: string | null }) {
  const { t } = useTranslation();
  if (!q) return null;
  const key = q.startsWith("official") ? "official" : q.startsWith("estimated") ? "estimated" : q;
  return <span className={`chip ${QUALITY_STYLE[q] || QUALITY_STYLE.manual}`} title={q}>{t(`quality.${key}`, { defaultValue: q })}</span>;
}

export function Badge({ tone = "brand", children }: { tone?: "brand" | "water" | "sun" | "danger" | "slate"; children: ReactNode }) {
  const m = { brand: "bg-brand-100 text-brand-800", water: "bg-water-100 text-water-700", sun: "bg-sun-100 text-sun-600", danger: "bg-danger-50 text-danger-700", slate: "bg-slate-100 text-slate-700" };
  return <span className={`chip ${m[tone]}`}>{children}</span>;
}

export function Loader({ label }: { label?: string }) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-3 p-6 text-sm text-ink-500" role="status">
      <span className="h-5 w-5 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
      {label || t("common.loading")}
    </div>
  );
}

export function ErrorBox({ error }: { error: any }) {
  const { t } = useTranslation();
  if (!error) return null;
  const code = error?.detail?.code || (typeof error?.detail === "string" ? error.detail : error?.message);
  return (
    <div className="rounded-xl border border-danger-500/30 bg-danger-50 p-3 text-sm text-danger-700" role="alert">
      {t(`errors.${code}`, { defaultValue: t("errors.generic") })}
      {code && <span className="ms-2 font-mono text-[11px] opacity-70">({code})</span>}
    </div>
  );
}

export function Empty({ icon = "🌱", title, children }: { icon?: string; title: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-brand-200 bg-brand-50/40 p-8 text-center">
      <span className="text-3xl" aria-hidden>{icon}</span>
      <p className="font-semibold text-ink-700">{title}</p>
      {children && <div className="text-sm text-ink-500">{children}</div>}
    </div>
  );
}

export function Field({ label, children, hint }: { label: ReactNode; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-ink-400">{hint}</span>}
    </label>
  );
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { id: T; label: ReactNode }[] }) {
  return (
    <div className="inline-flex rounded-xl bg-brand-50 p-1" role="tablist">
      {items.map((i) => (
        <button key={i.id} role="tab" aria-selected={value === i.id} onClick={() => onChange(i.id)}
          className={`rounded-lg px-3 py-1.5 text-sm font-semibold transition ${value === i.id ? "bg-white text-brand-700 shadow-sm" : "text-ink-500 hover:text-brand-700"}`}>
          {i.label}
        </button>
      ))}
    </div>
  );
}

export function Note({ tone = "water", children }: { tone?: "water" | "sun" | "danger"; children: ReactNode }) {
  const m = { water: "border-water-300/50 bg-water-50 text-water-700", sun: "border-sun-400/40 bg-sun-100 text-sun-600", danger: "border-danger-500/30 bg-danger-50 text-danger-700" };
  return <div className={`rounded-xl border p-3 text-xs leading-relaxed ${m[tone]}`}>{children}</div>;
}

export function GapBar({ value, max }: { value: number | null; max: number }) {
  if (value === null || !max) return <span className="text-ink-400">—</span>;
  const w = Math.min(100, (Math.abs(value) / max) * 100);
  const neg = value < 0;
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-2 w-24 overflow-hidden rounded-full bg-slate-100">
        <div className={`absolute inset-y-0 ${neg ? "bg-danger-500" : "bg-brand-500"}`} style={{ width: `${w}%`, insetInlineStart: 0 }} />
      </div>
      <span className={`tabular-nums text-xs font-semibold ${neg ? "text-danger-700" : "text-brand-700"}`}>{value > 0 ? "+" : ""}{Math.round(value)}</span>
    </div>
  );
}
