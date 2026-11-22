import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import fr from "./fr";
import ar from "./ar";

const saved = (() => { try { return localStorage.getItem("agrosphere.lang"); } catch { return null; } })();

i18n.use(initReactI18next).init({
  resources: { fr: { translation: fr }, ar: { translation: ar } },
  lng: saved === "ar" ? "ar" : "fr",
  fallbackLng: "fr",
  interpolation: { escapeValue: false },
});

export function applyDirection(lng: string) {
  document.documentElement.lang = lng === "ar" ? "ar-TN" : "fr";
  document.documentElement.dir = lng === "ar" ? "rtl" : "ltr";
}
applyDirection(i18n.language);
i18n.on("languageChanged", (l) => { applyDirection(l); try { localStorage.setItem("agrosphere.lang", l); } catch { /* ignore */ } });

export default i18n;
