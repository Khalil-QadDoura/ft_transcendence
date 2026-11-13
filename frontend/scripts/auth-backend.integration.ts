// Opt-in integration against a disposable backend with the local capture-mail
// harness described in docs/auth-screens.md. Never point this at real accounts.
import { afterAll, expect, test, vi } from "vitest";
import * as initialClient from "../src/api/client";
import { createAuthGateway } from "../src/features/auth/gateway";

const origin = process.env.WOZU_TEST_BACKEND_URL;
if (
  !origin ||
  !["127.0.0.1", "localhost", "[::1]"].includes(new URL(origin).hostname)
) {
  throw new Error(
    "Set WOZU_TEST_BACKEND_URL to the disposable loopback backend with captured test mail.",
  );
}
const realFetch = globalThis.fetch;
const requests: string[] = [];
vi.stubGlobal(
  "fetch",
  (input: string | URL | Request, options?: RequestInit) => {
    const url = new URL(String(input), origin);
    requests.push(`${options?.method ?? "GET"} ${url.pathname}`);
    return realFetch(url, options);
  },
);
let activeClient = initialClient;
afterAll(() => {
  activeClient.clearTokens();
  vi.unstubAllGlobals();
});

test("Khalil backend: register, verify, login, bearer profile, reload, concurrent refresh and logout", async () => {
  activeClient.clearTokens();
  const credentials = {
    email: `fe04-${crypto.randomUUID()}@example.com`,
    password: `Test-${crypto.randomUUID()}`,
  };
  let gateway = createAuthGateway();
  await gateway.register(credentials);
  expect(gateway.getStatus()).toBe("authenticated");
  // An unverified registration can be repeated; only a verified account is a 409.
  await gateway.register(credentials);
  await expect(gateway.login(credentials)).rejects.toMatchObject({
    status: 403,
  });
  const mail = await realFetch(
    `${origin}/__review/mail?email=${encodeURIComponent(credentials.email)}`,
  );
  expect(mail.status).toBe(200);
  const { link } = (await mail.json()) as { link: string };
  const verificationToken = new URL(link).searchParams.get("token")!;
  await gateway.verify(verificationToken);
  await expect(gateway.register(credentials)).rejects.toMatchObject({
    status: 409,
  });
  const beforeFailure = requests.length;
  await expect(
    gateway.login({ ...credentials, password: "incorrect-password" }),
  ).rejects.toMatchObject({ status: 401 });
  expect(requests.slice(beforeFailure)).toEqual(["POST /api/auth/login"]);
  await gateway.login(credentials);
  expect(gateway.getStatus()).toBe("authenticated");
  expect(
    await activeClient.apiClient<{ email: string }>("/users/me"),
  ).toMatchObject({ email: credentials.email });

  // Model a fresh browser document: discard module memory, keep only the persisted
  // refresh token. The UI restoration/loading behavior also has component coverage.
  const savedRefresh = activeClient.getStoredRefreshToken()!;
  activeClient.clearTokens();
  localStorage.setItem("wozu_refresh_token", savedRefresh);
  vi.resetModules();
  activeClient = await import("../src/api/client");
  gateway = (await import("../src/features/auth/gateway")).createAuthGateway();
  expect(gateway.getStatus()).toBe("loading");
  await Promise.all([gateway.restore(), gateway.restore()]);
  expect(gateway.getStatus()).toBe("authenticated");
  expect(activeClient.getStoredRefreshToken()).not.toBe(savedRefresh);
  expect(
    await activeClient.apiClient<{ email: string }>("/users/me"),
  ).toMatchObject({ email: credentials.email });

  // Exercise the real backend's 401 and single-use rotation contract concurrently.
  activeClient.setTokens({
    accessToken: "invalid-access-test",
    refreshToken: activeClient.getStoredRefreshToken()!,
  });
  const beforeConcurrent = requests.filter(
    (path) => path === "POST /api/auth/refresh",
  ).length;
  const profiles = await Promise.all(
    [1, 2, 3].map(() => activeClient.apiClient<{ email: string }>("/users/me")),
  );
  expect(profiles.every((profile) => profile.email === credentials.email)).toBe(
    true,
  );
  expect(
    requests.filter((path) => path === "POST /api/auth/refresh"),
  ).toHaveLength(beforeConcurrent + 1);

  const revoked = activeClient.getStoredRefreshToken();
  await gateway.logout();
  expect(gateway.getStatus()).toBe("anonymous");
  expect(activeClient.getAccessToken()).toBeNull();
  expect(localStorage.getItem("wozu_refresh_token")).toBeNull();
  const reuse = await realFetch(`${origin}/api/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: revoked }),
  });
  expect(reuse.status).toBe(401);
});
