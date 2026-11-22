import i18n from "../i18n";

const loc = () => (i18n.language === "ar" ? "ar-TN" : "fr-TN");

export function num(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return new Intl.NumberFormat(loc(), { maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(v);
}

export function area(m2: number | null | undefined): string {
  if (m2 === null || m2 === undefined) return "—";
  return m2 >= 10000 ? `${num(m2 / 10000, 2)} ha` : `${num(m2, 0)} m²`;
}

export function mass(kg: number | null | undefined): string {
  if (kg === null || kg === undefined) return "—";
  return kg >= 1000 ? `${num(kg / 1000, 1)} t` : `${num(kg, 0)} kg`;
}

export function date(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short", year: "numeric" }) {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(loc(), opts).format(new Date(iso));
}

export const MONTHS = (i: number) => new Intl.DateTimeFormat(loc(), { month: "short" }).format(new Date(2026, i, 1));
