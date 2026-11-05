import { afterEach, expect, it, vi } from "vitest";
import { credentials, profileSchema } from "./schemas";
afterEach(() => vi.useRealTimers());
it("rejects malformed credentials", () => {
  expect(
    credentials.safeParse({ email: "invalid", password: "123" }).success,
  ).toBe(false);
  expect(
    credentials.safeParse({
      email: "candidate@example.com",
      password: "WozuDemo!2026",
    }).success,
  ).toBe(true);
});
it("enforces the eighteenth birthday including its boundary", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-05T12:00:00Z"));
  const profile = {
    first_name: "Alex",
    last_name: "Morgan",
    position: "Designer",
    bio: "",
  };
  expect(
    profileSchema.safeParse({ ...profile, birth_date: "2008-11-05" }).success,
  ).toBe(true);
  expect(
    profileSchema.safeParse({ ...profile, birth_date: "2008-11-06" }).success,
  ).toBe(false);
  expect(
    profileSchema.safeParse({ ...profile, birth_date: "nonsense" }).success,
  ).toBe(false);
});
