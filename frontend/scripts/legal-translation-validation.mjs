import { createHash } from "node:crypto";
export const normalize = (text) => text.replace(/\r\n/g, "\n");
export const sourceHash = (text) =>
  createHash("sha256").update(normalize(text)).digest("hex");
export function validateTranslation(source, translated, expectedHash) {
  const errors = [];
  if (sourceHash(source) !== expectedHash)
    errors.push(
      "source changed: re-review translations and update the manifest",
    );
  if (translated.includes("\uFFFD"))
    errors.push("invalid replacement character");
  const date = (s) => s.match(/^Last updated: (.+)$/m)?.[1];
  if (!date(source) || date(source) !== date(translated))
    errors.push("source date mismatch");
  const headings = (s) =>
    [...s.matchAll(/^## (\d+)\./gm)].map((m) => m[1]).join(",");
  if (headings(source) !== headings(translated))
    errors.push("section numbers differ");
  for (const pattern of [/^### /gm, /^- /gm]) {
    if (
      [...source.matchAll(pattern)].length !==
      [...translated.matchAll(pattern)].length
    )
      errors.push("subsection or list coverage differs");
  }
  for (const value of new Set(
    source.match(/https?:\/\/[^\s)]+|[\w.+-]+@[\w.-]+\.[a-z]+/g) ?? [],
  )) {
    if (!translated.includes(value))
      errors.push(`missing source contact/link: ${value}`);
  }
  if (translated.length < source.length * 0.5)
    errors.push("translation unexpectedly short");
  return errors;
}
