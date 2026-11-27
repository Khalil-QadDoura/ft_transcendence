import i18next, { type Resource } from "i18next";
import { initReactI18next } from "react-i18next";
import { calendarDate } from "./date-format";

export const languages = ["en", "ar", "az", "tr", "ru"] as const;
export type Language = (typeof languages)[number];
const storageKey = "wozu_language";
export function supportedLanguage(value: string | null): Language | undefined {
  const base = value?.toLowerCase().split(/[-_]/)[0];
  return languages.find((language) => language === base);
}
export function initialLanguage(): Language {
  try {
    const saved = supportedLanguage(localStorage.getItem(storageKey));
    if (saved) return saved;
  } catch {
    /* Storage can be disabled; browser preferences still work. */
  }
  for (const locale of navigator.languages ?? [navigator.language]) {
    const match = supportedLanguage(locale);
    if (match) return match;
  }
  return "en";
}
export function activeLanguage(): Language {
  return (
    supportedLanguage(i18next.resolvedLanguage ?? i18next.language) ?? "en"
  );
}
function syncDocument(language: string) {
  const locale = supportedLanguage(language) ?? "en";
  document.documentElement.lang = locale;
  document.documentElement.dir = locale === "ar" ? "rtl" : "ltr";
  try {
    localStorage.setItem(storageKey, locale);
  } catch {
    /* Tab-only preference. */
  }
}
// Every namespace is checked by i18n:check and eagerly registered for instant switching.
const resources: Resource = {};
for (const [path, messages] of Object.entries(
  import.meta.glob<Record<string, unknown>>("./*/*.json", {
    eager: true,
    import: "default",
  }),
)) {
  const [, language, file] = path.split("/");
  (resources[language] ??= {})[file.replace(".json", "")] = messages;
}

i18next.use(initReactI18next);
void i18next.init({
  lng: initialLanguage(),
  fallbackLng: "en",
  supportedLngs: [...languages],
  resources,
  defaultNS: "common",
  ns: Object.keys(resources.en),
  initAsync: false,
  interpolation: { escapeValue: false },
});
syncDocument(activeLanguage());
i18next.on("languageChanged", syncDocument);
export const formatNumber = (
  value: number,
  options?: Intl.NumberFormatOptions,
) => new Intl.NumberFormat(activeLanguage(), options).format(value);
export const formatDate = (value: Date, options?: Intl.DateTimeFormatOptions) =>
  calendarDate(value, activeLanguage(), options);
export default i18next;
import "./rtl.css";
