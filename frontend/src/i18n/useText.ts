import { useTranslation } from "react-i18next";
import "./index";

// Subscribe domain screens to the active language and translated resources.
export function useText() {
  return useTranslation("screens");
}
