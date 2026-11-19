import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import {
  defaultScheduler,
  notifyManager,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import i18n from "../../i18n";
import { routes } from "../../app/router";
import { SessionContext } from "../../app/session";
import { StatusPage } from "./StatusPage";

// The real answer of the main stack on 2026-11-19 (worker off until PR #69): HTTP 200.
const REAL_HEALTH = {
  status: "degraded",
  components: { db: "ok", redis: "ok", minio: "ok", worker: "down" },
};
const ALL_UP = {
  status: "ok",
  components: { db: "ok", redis: "ok", minio: "ok", worker: "ok" },
};
const ORDER = ["api", "database", "redis", "storage", "worker"];

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root;
let container: HTMLDivElement;
let queries: QueryClient;
let fetchMock: ReturnType<typeof vi.fn>;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

beforeEach(() => {
  vi.useFakeTimers({
    toFake: [
      "setTimeout",
      "clearTimeout",
      "setInterval",
      "clearInterval",
      "Date",
    ],
  });
  vi.setSystemTime(new Date("2026-11-19T10:15:30Z"));
  // TanStack batches store notifications with setTimeout(0); fake timers give a 0 ms
  // timer created inside a tick 1 ms, so a 0 ms advance would never flush it.
  notifyManager.setScheduler(queueMicrotask);
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  queries = new QueryClient();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(() => root.unmount());
  queries.clear();
  container.remove();
  notifyManager.setScheduler(defaultScheduler);
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** Lets the pending fetch, the body read and the store notification settle, without moving the clock. */
const settle = () => act(() => vi.advanceTimersByTimeAsync(0));

async function renderPage() {
  await act(() =>
    root.render(
      <QueryClientProvider client={queries}>
        <StatusPage />
      </QueryClientProvider>,
    ),
  );
  await settle();
}

const overall = () =>
  container.querySelector("[aria-live='polite']")?.textContent ?? "";
const items = () =>
  Array.from(container.querySelectorAll("ul > li")).map((li) => ({
    id: li.getAttribute("data-component"),
    state: li.querySelector("[data-state]")?.getAttribute("data-state"),
    text: li.textContent,
  }));

describe("public status page", () => {
  test("(a) all five up: operational, five green labelled items in fixed order", async () => {
    fetchMock.mockResolvedValue(json(ALL_UP));
    await renderPage();
    expect(overall()).toContain("All systems operational");
    expect(container.querySelectorAll("h1")).toHaveLength(1);
    expect(items().map(({ id }) => id)).toEqual(ORDER);
    expect(items().every(({ state }) => state === "up")).toBe(true);
    expect(items().map(({ text }) => text)).toEqual([
      "API✓Up",
      "Database✓Up",
      "Redis✓Up",
      "File storage✓Up",
      "Background worker✓Up",
    ]);
    const badge = container.querySelector("[data-state='up']")!;
    expect(badge.className).toContain("text-success");
  });

  test("(b) real fixture with the worker down: degraded, worker red with a text label", async () => {
    fetchMock.mockResolvedValue(json(REAL_HEALTH));
    await renderPage();
    expect(overall()).toContain("Degraded");
    const worker = items().find(({ id }) => id === "worker")!;
    expect(worker.state).toBe("down");
    expect(worker.text).toContain("Down");
    expect(
      container.querySelector("[data-component='worker'] [data-state]")!
        .className,
    ).toContain("text-danger");
    expect(items().filter(({ state }) => state === "up")).toHaveLength(4);
  });

  test("(c) a 503 with a JSON health body is still parsed and shown", async () => {
    fetchMock.mockResolvedValue(
      json(
        {
          status: "down",
          components: { db: "down", redis: "ok", minio: "ok", worker: "down" },
        },
        503,
      ),
    );
    await renderPage();
    expect(overall()).toContain("Degraded");
    expect(overall()).not.toContain("unreachable");
    expect(items().map(({ state }) => state)).toEqual([
      "up",
      "down",
      "up",
      "up",
      "down",
    ]);
  });

  test.each([
    [
      "network error",
      () => fetchMock.mockRejectedValue(new TypeError("Failed to fetch")),
    ],
    [
      "non-JSON 502 from the proxy",
      () =>
        fetchMock.mockResolvedValue(
          new Response("<html><body>502 Bad Gateway</body></html>", {
            status: 502,
            headers: { "Content-Type": "text/html" },
          }),
        ),
    ],
    [
      "JSON that is not a health body",
      () => fetchMock.mockResolvedValue(json({ detail: "x" }, 500)),
    ],
  ])(
    "(d) %s: API unreachable, API down, the rest unknown",
    async (_, arrange) => {
      arrange();
      await renderPage();
      expect(overall()).toContain("API unreachable");
      expect(items().map(({ state }) => state)).toEqual([
        "down",
        "unknown",
        "unknown",
        "unknown",
        "unknown",
      ]);
    },
  );

  test("(d) a check that hangs is aborted after 5 s and shown as API unreachable", async () => {
    fetchMock.mockImplementation(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) =>
          init.signal!.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          ),
        ),
    );
    await renderPage();
    expect(overall()).toContain("Checking");
    await act(() => vi.advanceTimersByTimeAsync(4_999));
    expect(overall()).toContain("Checking");
    await act(() => vi.advanceTimersByTimeAsync(1));
    await settle();
    expect(overall()).toContain("API unreachable");
  });

  test("(e) leaked hostnames, versions and tracebacks never reach the DOM or the console", async () => {
    const consoleSpies = (
      ["log", "info", "warn", "error", "debug"] as const
    ).map((level) => vi.spyOn(console, level));
    fetchMock.mockResolvedValue(
      json(
        {
          status: "degraded",
          version: "15.4",
          hostname: "api-7f9c4d",
          error:
            'Traceback (most recent call last):\n  File "/app/app/health/service.py", line 52',
          components: {
            db: "ok",
            redis: "redis://redis:6379/0",
            minio: { host: "minio:9000", version: "RELEASE.2025" },
            postgres: "postgres://app:secret@db:5432/app",
            version: "15.4",
          },
        },
        503,
      ),
    );
    await renderPage();
    const text = document.body.textContent ?? "";
    const html = document.body.innerHTML;
    for (const leak of [
      "redis://",
      "6379",
      "postgres",
      "secret",
      "15.4",
      "api-7f9c4d",
      "Traceback",
      "service.py",
      "minio:9000",
      "RELEASE",
    ]) {
      expect(text).not.toContain(leak);
      expect(html).not.toContain(leak);
    }
    expect(items().map(({ id }) => id)).toEqual(ORDER);
    // Unparseable values and a missing worker key show "unknown".
    expect(items().map(({ state }) => state)).toEqual([
      "up",
      "up",
      "unknown",
      "unknown",
      "unknown",
    ]);
    for (const spy of consoleSpies) expect(spy).not.toHaveBeenCalled();
  });

  test("(f) polls again after 15 s, not before, without credentials", async () => {
    fetchMock.mockImplementation(async () => json(REAL_HEALTH));
    await renderPage();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(() => vi.advanceTimersByTimeAsync(14_999));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe("/api/health");
    expect(init.credentials).toBe("omit");
    expect(new Headers(init.headers).has("Authorization")).toBe(false);
  });

  test("(h) shows the last check time in the active language and updates it", async () => {
    fetchMock.mockImplementation(async () => json(REAL_HEALTH));
    await renderPage();
    const time = () => container.querySelector("[data-last-checked] time");
    const expected = (when: Date, language: string) =>
      new Intl.DateTimeFormat(language, { timeStyle: "medium" }).format(when);
    expect(time()?.getAttribute("dateTime")).toBe("2026-11-19T10:15:30.000Z");
    expect(time()?.textContent).toBe(
      expected(new Date("2026-11-19T10:15:30Z"), "en"),
    );
    expect(container.textContent).toContain("Last checked:");
    await act(() => vi.advanceTimersByTimeAsync(15_000));
    await settle();
    expect(time()?.getAttribute("dateTime")).toBe("2026-11-19T10:15:45.000Z");
    try {
      await act(() => i18n.changeLanguage("ar"));
      expect(time()?.textContent).toBe(
        expected(new Date("2026-11-19T10:15:45Z"), "ar"),
      );
      expect(container.textContent).toContain("آخر فحص:");
    } finally {
      await act(() => i18n.changeLanguage("en"));
    }
  });
});

test("(g) /status renders for a logged-out visitor and the footer links to it", async () => {
  fetchMock.mockResolvedValue(json(REAL_HEALTH));
  const router = createMemoryRouter(routes, { initialEntries: ["/status"] });
  await act(() =>
    root.render(
      <QueryClientProvider client={queries}>
        <SessionContext value="anonymous">
          <RouterProvider router={router} />
        </SessionContext>
      </QueryClientProvider>,
    ),
  );
  await settle();
  expect(router.state.location.pathname).toBe("/status");
  expect(container.querySelector("h1")?.textContent).toBe("Service status");
  expect(container.querySelector('footer a[href="/status"]')).not.toBeNull();
  expect(overall()).toContain("Degraded");
});
