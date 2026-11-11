import { useTranslation } from "react-i18next";
import { languages, activeLanguage } from "./index";
const names = {
  en: "English",
  ar: "العربية",
  az: "Azərbaycanca",
  tr: "Türkçe",
  ru: "Русский",
};
export function LanguageSwitcher() {
  const { t, i18n } = useTranslation();
  return (
    <label className="language-picker">
      <span className="sr-only">{t("language")}</span>
      <select
        name="language"
        value={activeLanguage()}
        onChange={(event) => void i18n.changeLanguage(event.target.value)}
      >
        {languages.map((language) => (
          <option key={language} value={language} lang={language}>
            {names[language]}
          </option>
        ))}
      </select>
    </label>
  );
}
