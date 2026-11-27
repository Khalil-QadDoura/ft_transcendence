import { test } from "node:test";
import assert from "node:assert/strict";
import {
  sourceHash,
  validateTranslation,
} from "./legal-translation-validation.mjs";
const original =
  "# Policy\nLast updated: 2026-11-17\n## 1. First\n### Details\n- Keep data for 30 days. Contact a@example.com\n## 2. Next\n";
test("accepts matching structural coverage and normalized source hashes", () => {
  assert.equal(
    sourceHash(original.replaceAll("\n", "\r\n")),
    sourceHash(original),
  );
  assert.deepEqual(
    validateTranslation(original, original, sourceHash(original)),
    [],
  );
});
test("rejects stale source, missing sections, lists, contacts and damaged characters", () => {
  const translated = original
    .replace("## 2. Next", "")
    .replace("- Keep", "Keep")
    .replace("a@example.com", "\uFFFD");
  const errors = validateTranslation(original, translated, "old-hash");
  for (const fragment of [
    "source changed",
    "section numbers",
    "list coverage",
    "contact/link",
    "replacement character",
  ])
    assert.ok(errors.some((e) => e.includes(fragment)));
  assert.ok(
    validateTranslation(
      original,
      original.replace("2026-11-17", "2026-11-18"),
      sourceHash(original),
    ).includes("source date mismatch"),
  );
});
