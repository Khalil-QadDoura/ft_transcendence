import { beforeEach, afterEach, expect, it, vi } from "vitest";
import {
  api,
  hasSession,
  query,
  refreshSession,
  safeNext,
  setTokens,
} from "./client";

beforeEach(() => setTokens(null));
afterEach(() => vi.unstubAllGlobals());
const pair = {
  access_token: "access",
  refresh_token: "refresh",
  token_type: "bearer",
};

it("keeps redirect targets on this origin", () => {
  for (const path of [
    "//evil.example",
    "/\\evil.example",
    "https://evil.example",
    null,
  ])
    expect(safeNext(path)).toBe("/jobs");
  expect(safeNext("/jobs/7?from=saved")).toBe("/jobs/7?from=saved");
});
it("preserves zero and safely encodes search parameters", () => {
  expect(
    query({ offset: 0, search: "design & product", empty: "", absent: null }),
  ).toBe("offset=0&search=design+%26+product");
});
it("shares token refresh across concurrent requests", async () => {
  setTokens(pair);
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(pair)));
  vi.stubGlobal("fetch", fetch);
  await Promise.all([refreshSession(), refreshSession(), refreshSession()]);
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("does not resurrect a session after logout while refresh is in flight", async () => {
  setTokens(pair);
  let resolve!: (response: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((r) => {
          resolve = r;
        }),
    ),
  );
  const refresh = refreshSession();
  setTokens(null);
  resolve(new Response(JSON.stringify(pair)));
  await expect(refresh).rejects.toThrow("Session changed");
  expect(hasSession()).toBe(false);
});
it("refreshes an expired credential for authenticated password changes", async () => {
  setTokens(pair);
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Expired" }), { status: 401 }),
    )
    .mockResolvedValueOnce(new Response(JSON.stringify(pair)))
    .mockResolvedValueOnce(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetch);
  await api("/auth/change-password", { method: "POST", body: "{}" });
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(fetch.mock.calls[1][0]).toBe("/api/auth/refresh");
});
it("does not refresh after invalid login credentials", async () => {
  setTokens(pair);
  const fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ detail: "Invalid credentials" }), {
      status: 401,
    }),
  );
  vi.stubGlobal("fetch", fetch);
  await expect(api("/auth/login", { method: "POST" })).rejects.toThrow(
    "Invalid credentials",
  );
  expect(fetch).toHaveBeenCalledTimes(1);
});
