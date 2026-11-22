import i18n, { languages } from "./index";

// Getters resolve at render time, including messages used by non-React helpers.
// Components using this adapter must subscribe with useTranslation(namespace).
export function translatedCopy<T extends Record<string, string>>(
  namespace: string,
  source: T,
): T {
  return Object.defineProperties(
    {},
    Object.fromEntries(
      Object.keys(source).map((key) => [
        key,
        {
          enumerable: true,
          get: () => i18n.t(key, { ns: namespace }),
        },
      ]),
    ),
  ) as T;
}

// An existing form error can survive a language switch. Re-resolve known UI
// messages without translating arbitrary server text or user-generated content.
export function localizeMessage(
  namespace: string,
  message?: string,
  fallbackKey?: string,
): string | undefined {
  if (!message) return message;
  const entries = (
    value: Record<string, unknown>,
    prefix = "",
  ): [string, unknown][] =>
    Object.entries(value).flatMap(([key, child]) =>
      child !== null && typeof child === "object"
        ? entries(child as Record<string, unknown>, `${prefix}${key}.`)
        : [[`${prefix}${key}`, child]],
    );
  for (const language of languages) {
    const copy = i18n.getResourceBundle(language, namespace) as
      Record<string, unknown> | undefined;
    const key = entries(copy ?? {}).find(([, value]) => value === message)?.[0];
    if (key) return i18n.t(key, { ns: namespace });
  }
  return fallbackKey ? i18n.t(fallbackKey, { ns: namespace }) : message;
}
