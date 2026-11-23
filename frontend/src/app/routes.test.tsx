import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { routes } from "./router";
import { safeNext, SessionContext } from "./session";

let root: Root;
let container: HTMLDivElement;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
beforeEach(() => {
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});
async function render(
  path: string,
  session: "anonymous" | "authenticated" | "loading" = "anonymous",
) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  // The public status page (INF-16) reads /api/health through TanStack Query.
  const queries = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  await act(() =>
    root.render(
      <QueryClientProvider client={queries}>
        <SessionContext value={session}>
          <RouterProvider router={router} />
        </SessionContext>
      </QueryClientProvider>,
    ),
  );
  return router;
}
test.each([
  "/profile",
  "/company",
  "/friends",
  "/chat/7",
  "/videos",
  "/employer/jobs",
  "/game/rooms/2",
  "/settings",
])("preserves protected destination %s through login", async (path) => {
  const router = await render(`${path}?view=all#latest`);
  expect(router.state.location.pathname).toBe("/login");
  expect(new URLSearchParams(router.state.location.search).get("next")).toBe(
    `${path}?view=all#latest`,
  );
  await act(() =>
    root.render(
      <SessionContext value="authenticated">
        <RouterProvider router={router} />
      </SessionContext>,
    ),
  );
  expect(
    router.state.location.pathname +
      router.state.location.search +
      router.state.location.hash,
  ).toBe(`${path}?view=all#latest`);
});
test.each([
  "/",
  "/jobs",
  "/jobs/4",
  "/game/rules",
  "/privacy",
  "/terms",
  "/status",
  "/login",
  "/register",
  "/verify-email",
  "/forgot-password",
  "/reset-password",
])("renders shared legal navigation at %s", async (path) => {
  const router = await render(path);
  expect(router.state.location.pathname).toBe(path);
  expect(container.querySelector("h1")).not.toBeNull();
  expect(container.querySelector('footer a[href="/privacy"]')).not.toBeNull();
  expect(container.querySelector('footer a[href="/terms"]')).not.toBeNull();
  expect(container.querySelector('footer a[href="/status"]')).not.toBeNull();
});
test("waits for session restoration before redirecting", async () => {
  const router = await render("/profile", "loading");
  expect(router.state.location.pathname).toBe("/profile");
  expect(container.querySelector('[role="status"]')?.textContent).toContain(
    "Checking",
  );
});
test("renders unknown paths and focuses the main landmark after navigation", async () => {
  const router = await render("/missing/path");
  expect(container.textContent).toContain("404");
  await act(() => router.navigate("/privacy"));
  expect(document.activeElement?.id).toBe("main");
  expect(document.title).toBe("Privacy Policy · WOZU");
});

test("preserves word spacing in tab titles across visual line breaks", async () => {
  const router = await render("/");
  expect(document.title).toBe("Your next chapter, in good company. · WOZU");
  expect(container.querySelectorAll("h1 br")).toHaveLength(2);
  await act(() => router.navigate("/missing/path"));
  expect(document.title).toBe("A different direction. · WOZU");
});

test("keeps the shared component preview available during development", async () => {
  await render("/dev/components");
  expect(container.textContent).toContain("Design System & Component Preview");
  expect(container.textContent).not.toContain("404 / A SMALL DETOUR");
});
test.each([
  null,
  "https://example.com",
  "//example.com",
  "/\\example.com",
  "/login",
  "/register?next=/login",
  "/login//",
  "/./login",
  "/\n/evil",
])("rejects external or looping return path %s", (value) => {
  expect(safeNext(value)).toBe("/profile");
});

test("public user profiles require the backend authenticated session", async () => {
  const router = await render("/users/2");
  expect(router.state.location.pathname).toBe("/login");
  expect(new URLSearchParams(router.state.location.search).get("next")).toBe(
    "/users/2",
  );
});
