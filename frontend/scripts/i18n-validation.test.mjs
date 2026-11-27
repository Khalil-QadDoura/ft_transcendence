import { test } from "node:test";
import assert from "node:assert/strict";
import { validateMessages } from "./i18n-validation.mjs";
test("rejects missing, unknown, empty and mismatched placeholders", () => {
  assert.deepEqual(
    validateMessages(
      { title: "Hi {{name}}", save: "Save" },
      { title: "أهلًا {{id}}", extra: "x", save: "" },
      "ar",
    ),
    ["interpolation mismatch title", "unknown extra", "empty/non-string save"],
  );
  assert.deepEqual(validateMessages({ save: "Save" }, {}, "az"), [
    "missing save",
  ]);
});
test("requires every Arabic and Russian plural category", () => {
  const source = {
    count: "{{count}} items",
    count_one: "{{count}} item",
    count_other: "{{count}} items",
  };
  assert.equal(
    validateMessages(source, { count: "{{count}} عنصر" }, "ar").length,
    6,
  );
  assert.equal(
    validateMessages(source, { count: "{{count}} элементов" }, "ru").length,
    4,
  );
  const ar = {
    count: "{{count}} عنصر",
    count_zero: "لا عناصر",
    count_one: "عنصر واحد",
    count_two: "عنصران",
    count_few: "{{count, number}} عناصر",
    count_many: "{{count}} عنصرًا",
    count_other: "{{count}} عنصر",
  };
  assert.deepEqual(validateMessages(source, ar, "ar"), []);
});

test("plural families need no unsuffixed base key", () => {
  const source = {
    minutes_one: "{{count}} minute",
    minutes_other: "{{count}} minutes",
  };
  const target = {
    minutes_one: "{{count}} минута",
    minutes_few: "{{count}} минуты",
    minutes_many: "{{count}} минут",
    minutes_other: "{{count}} минуты",
  };
  assert.deepEqual(validateMessages(source, target, "ru"), []);
  delete target.minutes_many;
  assert.deepEqual(validateMessages(source, target, "ru"), [
    "missing plural minutes_many",
  ]);
});
