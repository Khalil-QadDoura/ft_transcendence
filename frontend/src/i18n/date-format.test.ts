import { expect, test } from "vitest";
import { calendarDate, relativePast } from "./date-format";
test("Azerbaijani dates and relative times do not depend on browser az locale data", () => {
  const day = new Date("2026-10-14T12:00:00Z");
  expect(
    calendarDate(day, "az", {
      day: "numeric",
      month: "short",
      timeZone: "UTC",
    }),
  ).toBe("14 okt");
  expect(
    calendarDate(day, "az", {
      day: "numeric",
      month: "long",
      year: "numeric",
      timeZone: "UTC",
    }),
  ).toBe("14 oktyabr 2026");
  expect(relativePast(5, "minute", "az")).toBe("5 dəq. əvvəl");
  expect(relativePast(2, "hour", "az")).toBe("2 saat əvvəl");
  expect(calendarDate(day, "ar", { month: "long", timeZone: "UTC" })).toBe(
    new Intl.DateTimeFormat("ar", { month: "long", timeZone: "UTC" }).format(
      day,
    ),
  );
});
