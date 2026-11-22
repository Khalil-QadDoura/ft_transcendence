export const flatten = (value, prefix = "") =>
  Object.entries(value).flatMap(([key, child]) =>
    child !== null && typeof child === "object" && !Array.isArray(child)
      ? flatten(child, `${prefix}${key}.`)
      : [[`${prefix}${key}`, child]],
  );
const plural = /_(zero|one|two|few|many|other)$/;
const parameters = (value) =>
  [...String(value).matchAll(/{{\s*([^},\s]+)(?:[^}]*?)}}/g)]
    .map((m) => m[1])
    .sort();
export function validateMessages(source, target, language) {
  const english = Object.fromEntries(flatten(source));
  const translated = Object.fromEntries(flatten(target));
  const errors = [];
  const bases = [
    ...new Set(Object.keys(english).map((key) => key.replace(plural, ""))),
  ];
  for (const key of bases) {
    if (key in english && !(key in translated)) errors.push(`missing ${key}`);
    if (
      Object.keys(english).some(
        (k) => k.startsWith(`${key}_`) && plural.test(k),
      )
    ) {
      for (const category of new Intl.PluralRules(language).resolvedOptions()
        .pluralCategories) {
        if (!(`${key}_${category}` in translated))
          errors.push(`missing plural ${key}_${category}`);
      }
    }
  }
  for (const [key, value] of Object.entries(translated)) {
    const base = key.replace(plural, "");
    if (!bases.includes(base)) {
      errors.push(`unknown ${key}`);
      continue;
    }
    if (typeof value !== "string" || !value.trim()) {
      errors.push(`empty/non-string ${key}`);
      continue;
    }
    const expected = parameters(
      english[key] ?? english[base] ?? english[`${base}_other`],
    );
    const actual = parameters(value);
    // Arabic zero/one/two can name the quantity without printing a numeral.
    const mayOmitCount = language === "ar" && /_(zero|one|two)$/.test(key);
    const filtered =
      mayOmitCount && !actual.includes("count")
        ? expected.filter((p) => p !== "count")
        : expected;
    if (JSON.stringify(actual) !== JSON.stringify(filtered))
      errors.push(`interpolation mismatch ${key}`);
  }
  return errors;
}
