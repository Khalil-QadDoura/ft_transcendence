import { afterEach, expect, test, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import i18n, {
  initialLanguage,
  formatNumber,
  formatDate,
  languages,
} from "./index";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { apiClient } from "../api/client";
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
afterEach(async () => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  await i18n.changeLanguage("en");
  localStorage.clear();
});
test("saved language wins, regional browser languages fall back safely", () => {
  vi.spyOn(navigator, "languages", "get").mockReturnValue(["de-DE", "az-AZ"]);
  localStorage.setItem("wozu_language", "ru");
  expect(initialLanguage()).toBe("ru");
  localStorage.setItem("wozu_language", "invalid");
  expect(initialLanguage()).toBe("az");
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("disabled");
  });
  expect(initialLanguage()).toBe("az");
});
test.each(languages)(
  "%s updates lang, direction, storage and Intl",
  async (language) => {
    await i18n.changeLanguage(language);
    expect(document.documentElement.lang).toBe(language);
    expect(document.documentElement.dir).toBe(
      language === "ar" ? "rtl" : "ltr",
    );
    expect(localStorage.getItem("wozu_language")).toBe(language);
    expect(formatNumber(12345.6)).toBe(
      new Intl.NumberFormat(language).format(12345.6),
    );
    const date = new Date("2026-11-17T12:00:00Z");
    expect(formatDate(date, { timeZone: "UTC" })).toBe(
      new Intl.DateTimeFormat(language, { timeZone: "UTC" }).format(date),
    );
  },
);
test("blocked storage does not prevent switching; missing translations use English", async () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("disabled");
  });
  i18n.addResource("en", "common", "testFallback", "English fallback");
  await i18n.changeLanguage("ar");
  expect(i18n.t("testFallback")).toBe("English fallback");
  expect(document.documentElement.dir).toBe("rtl");
});
test("native selector switches language without leaving the page", async () => {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(() => root.render(<LanguageSwitcher />));
    const select = container.querySelector("select")!;
    expect(select.options).toHaveLength(5);
    await act(() => {
      select.value = "tr";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(container.textContent).toContain("Dil");
    expect(localStorage.getItem("wozu_language")).toBe("tr");
  } finally {
    await act(() => root.unmount());
    container.remove();
  }
});
test("requests use the active language and respect explicit overrides", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetchMock);
  await i18n.changeLanguage("ru");
  await apiClient("/health", { skipAuth: true });
  expect(
    new Headers(fetchMock.mock.calls[0][1].headers).get("Accept-Language"),
  ).toBe("ru");
  await apiClient("/health", {
    skipAuth: true,
    headers: { "Accept-Language": "en" },
  });
  expect(
    new Headers(fetchMock.mock.calls[1][1].headers).get("Accept-Language"),
  ).toBe("en");
});
