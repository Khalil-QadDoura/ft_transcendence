import { useTranslation } from "react-i18next";
import "./index";

// Domain text is extracted now; FE-07 supplies reviewed translations.
export function useText() {
  return useTranslation("screens");
}
