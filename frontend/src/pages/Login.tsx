import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../lib/auth";
import { LanguageToggle } from "../components/Layout";
import { ErrorBox, Field } from "../components/ui";
import { useNames } from "../lib/reference";

export default function Login() {
  const { t } = useTranslation();
  const { login, register } = useAuth();
  const { govs, lang } = useNames();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [f, setF] = useState({ email: "", password: "", full_name: "", governorate_code: "" });
  const [err, setErr] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(null);
    try {
      if (mode === "login") await login(f.email, f.password);
      else await register({ email: f.email, password: f.password, full_name: f.full_name, governorate_code: f.governorate_code || undefined });
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <div className="grid min-h-full lg:grid-cols-2">
      <div className="relative hidden overflow-hidden bg-gradient-to-br from-brand-700 via-brand-600 to-water-600 p-10 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="flex items-center gap-3"><img src="/favicon.svg" className="h-10 w-10" alt="" /><span className="text-xl font-bold">AgroSphere AI</span></div>
        <div>
          <h1 className="text-4xl font-bold leading-tight">{t("login.hero")}</h1>
          <p className="mt-4 max-w-md text-brand-50/90">{t("login.heroText")}</p>
          <p className="mt-8 text-sm italic text-brand-100">TuniNō — Two nations, one vision: sustainable agriculture</p>
        </div>
        <p className="text-xs text-brand-100/80">{t("login.sources")}</p>
      </div>
      <div className="flex flex-col p-6 sm:p-10">
        <div className="flex justify-end"><LanguageToggle /></div>
        <form onSubmit={submit} className="m-auto w-full max-w-sm space-y-4">
          <div className="lg:hidden flex items-center gap-2"><img src="/favicon.svg" className="h-9 w-9" alt="" /><span className="text-lg font-bold text-brand-800">AgroSphere AI</span></div>
          <h2 className="text-2xl font-bold">{mode === "login" ? t("login.title") : t("login.registerTitle")}</h2>
          {mode === "register" && (
            <>
              <Field label={t("login.name")}><input className="input" required minLength={2} value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
              <Field label={t("farm.governorate")}>
                <select className="input" value={f.governorate_code} onChange={(e) => setF({ ...f, governorate_code: e.target.value })}>
                  <option value="">—</option>
                  {Object.entries(govs).map(([k, v]) => <option key={k} value={k}>{v[lang]}</option>)}
                </select>
              </Field>
            </>
          )}
          <Field label={t("login.email")}><input className="input" type="email" required autoComplete="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
          <Field label={t("login.password")} hint={mode === "register" ? t("login.passwordHint") : undefined}>
            <input className="input" type="password" required minLength={mode === "register" ? 8 : 1} autoComplete={mode === "login" ? "current-password" : "new-password"} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
          </Field>
          <ErrorBox error={err} />
          <button className="btn-primary w-full" disabled={busy}>{mode === "login" ? t("login.submit") : t("login.create")}</button>
          <button type="button" className="w-full text-center text-sm font-semibold text-brand-700" onClick={() => setMode(mode === "login" ? "register" : "login")}>
            {mode === "login" ? t("login.noAccount") : t("login.haveAccount")}
          </button>
          {mode === "register" && <p className="text-xs text-ink-500">{t("login.ministryNote")}</p>}
        </form>
      </div>
    </div>
  );
}
