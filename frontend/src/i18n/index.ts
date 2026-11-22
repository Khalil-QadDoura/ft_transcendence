import employer from "./en/employer.json";
import people from "./en/people.json";
import i18next from "i18next";
import { initReactI18next } from "react-i18next";
import profile from "./en/profile.json";
import screens from "./en/screens.json";
import en from "./en/common.json";
import ar from "./ar/common.json";
import az from "./az/common.json";
import tr from "./tr/common.json";
import ru from "./ru/common.json";
import statusEn from "./en/status.json";
import statusAr from "./ar/status.json";
import statusAz from "./az/status.json";
import statusTr from "./tr/status.json";
import statusRu from "./ru/status.json";
import gameRulesEn from "./en/gameRules.json";
import gameRulesAr from "./ar/gameRules.json";
import gameRulesAz from "./az/gameRules.json";
import gameRulesTr from "./tr/gameRules.json";
import gameRulesRu from "./ru/gameRules.json";

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
i18next.use(initReactI18next);
void i18next.init({
  lng: initialLanguage(),
  fallbackLng: "en",
  supportedLngs: [...languages],
  resources: {
    en: {
      common: en,
      employer,
      screens,
      profile,
      people,
      status: statusEn,
      gameRules: gameRulesEn,
    },
    ar: { common: ar, status: statusAr, gameRules: gameRulesAr },
    az: { common: az, status: statusAz, gameRules: gameRulesAz },
    tr: { common: tr, status: statusTr, gameRules: gameRulesTr },
    ru: { common: ru, status: statusRu, gameRules: gameRulesRu },
  },
  defaultNS: "common",
  ns: [
    "employer",
    "common",
    "screens",
    "profile",
    "people",
    "status",
    "gameRules",
  ],
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
  new Intl.DateTimeFormat(activeLanguage(), options).format(value);
export default i18next;
