import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  apiClient,
  clearTokens,
  getAccessToken,
  getStoredRefreshToken,
  logoutSession,
  refreshAccessToken,
  setTokens,
} from "./client";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}
beforeEach(() => {
  clearTokens();
  localStorage.clear();
});
afterEach(() => {
  clearTokens();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test("parallel protected requests rotate once and replay with the same new token", async () => {
  setTokens({ accessToken: "expired", refreshToken: "old-refresh" });
  const rotation = deferred<Response>();
  const fetcher = vi
    .fn()
    .mockImplementation((url: string, options: RequestInit) => {
      if (url.endsWith("/refresh")) return rotation.promise;
      return Promise.resolve(
        new Headers(options.headers).get("Authorization") === "Bearer fresh"
          ? json({ ok: true })
          : json({ error: { code: "401", detail: "expired" } }, 401),
      );
    });
  vi.stubGlobal("fetch", fetcher);
  const a = apiClient("/users/me");
  const b = apiClient("/users/me");
  await vi.waitFor(() =>
    expect(
      fetcher.mock.calls.filter(([url]) => url.endsWith("/refresh")),
    ).toHaveLength(1),
  );
  rotation.resolve(json({ access_token: "fresh", refresh_token: "rotated" }));
  await expect(Promise.all([a, b])).resolves.toEqual([
    { ok: true },
    { ok: true },
  ]);
  expect(fetcher).toHaveBeenCalledTimes(5);
});

test("logout cannot be undone by a late refresh and revokes its replacement token", async () => {
  setTokens({ accessToken: "old-access", refreshToken: "old-refresh" });
  const rotation = deferred<Response>();
  const revoked: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string, options: RequestInit) => {
      if (url.endsWith("/refresh")) return rotation.promise;
      revoked.push(JSON.parse(options.body as string).refresh_token);
      return Promise.resolve(new Response(null, { status: 204 }));
    }),
  );
  const refresh = refreshAccessToken();
  const logout = logoutSession();
  expect(getAccessToken()).toBeNull();
  expect(getStoredRefreshToken()).toBeNull();
  rotation.resolve(
    json({ access_token: "late-access", refresh_token: "late-refresh" }),
  );
  await Promise.all([refresh, logout]);
  expect(getAccessToken()).toBeNull();
  expect(getStoredRefreshToken()).toBeNull();
  expect(revoked.sort()).toEqual(["late-refresh", "old-refresh"]);
});

test.each([true, false])(
  "old refresh success=%s cannot replace or clear a newer login",
  async (success) => {
    setTokens({ accessToken: "a", refreshToken: "a-refresh" });
    const rotation = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(rotation.promise));
    const refresh = refreshAccessToken();
    setTokens({ accessToken: "b", refreshToken: "b-refresh" });
    rotation.resolve(
      success
        ? json({ access_token: "a-new", refresh_token: "a-new-refresh" })
        : json({}, 401),
    );
    await refresh;
    expect(getAccessToken()).toBe("b");
    expect(getStoredRefreshToken()).toBe("b-refresh");
  },
);

test("a late private response after account replacement cannot enter the new cache", async () => {
  setTokens({ accessToken: "a", refreshToken: "a-refresh" });
  const response = deferred<Response>();
  vi.stubGlobal("fetch", vi.fn().mockReturnValue(response.promise));
  const request = apiClient("/users/me");
  setTokens({ accessToken: "b", refreshToken: "b-refresh" });
  response.resolve(json({ email: "account-a@example.com" }));
  await expect(request).rejects.toMatchObject({ code: "session_changed" });
});

test("a slow 401 after another request rotated reuses the new access token", async () => {
  setTokens({ accessToken: "old", refreshToken: "refresh" });
  const slow = deferred<Response>();
  const fetcher = vi
    .fn()
    .mockReturnValueOnce(slow.promise)
    .mockResolvedValueOnce(
      json({ access_token: "new", refresh_token: "new-refresh" }),
    )
    .mockResolvedValueOnce(json({ ok: true }));
  vi.stubGlobal("fetch", fetcher);
  const request = apiClient("/users/me");
  await refreshAccessToken();
  slow.resolve(json({}, 401));
  await expect(request).resolves.toEqual({ ok: true });
  expect(
    fetcher.mock.calls.filter(([url]) => url === "/api/auth/refresh"),
  ).toHaveLength(1);
});

test("a second 401 signs out after one bounded retry", async () => {
  setTokens({ accessToken: "old", refreshToken: "refresh" });
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(json({}, 401))
    .mockResolvedValueOnce(
      json({ access_token: "new", refresh_token: "new-refresh" }),
    )
    .mockResolvedValueOnce(json({}, 401));
  vi.stubGlobal("fetch", fetcher);
  await expect(apiClient("/users/me")).rejects.toMatchObject({ status: 401 });
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(getAccessToken()).toBeNull();
});

test.each([
  {},
  { access_token: "a" },
  { access_token: "a", refresh_token: "r", token_type: "other" },
])(
  "malformed rotation data never restores authentication: %j",
  async (body) => {
    setTokens({ accessToken: "old", refreshToken: "refresh" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(body)));
    await expect(refreshAccessToken()).resolves.toBeNull();
    expect(getAccessToken()).toBeNull();
    expect(getStoredRefreshToken()).toBeNull();
  },
);

test("blocked browser storage still allows tab-local refresh and logout", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  setTokens({ accessToken: "access", refreshToken: "refresh" });
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(
      json({ access_token: "new", refresh_token: "rotated" }),
    )
    .mockResolvedValueOnce(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetcher);
  await refreshAccessToken();
  await logoutSession();
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({
    refresh_token: "rotated",
  });
  expect(getAccessToken()).toBeNull();
});
