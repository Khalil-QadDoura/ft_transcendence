import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  clearTokens,
  getAccessToken,
  getStoredRefreshToken,
  setStoredRefreshToken,
  setTokens,
  refreshAccessToken,
} from "../../api/client";
import { routes } from "../../app/router";
import { AuthProvider } from "./AuthProvider";
import { AuthError, createAuthGateway, type AuthGateway } from "./gateway";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root;
let container: HTMLDivElement;
let client: AuthGateway;
beforeEach(() => {
  clearTokens();
  localStorage.clear();
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  client = {
    register: vi.fn().mockResolvedValue(undefined),
    verify: vi.fn().mockResolvedValue(undefined),
    login: vi.fn().mockResolvedValue(undefined),
    logout: vi.fn().mockResolvedValue(undefined),
    getStatus: () => "anonymous",
    getSessionVersion: () => 0,
    restore: vi.fn().mockResolvedValue(undefined),
    subscribe: () => () => {},
  };
});
afterEach(async () => {
  await act(() => root.unmount());
  container.remove();
  clearTokens();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
function jsonResponse(body: string) {
  return new Response(body, {
    headers: { "Content-Type": "application/json" },
  });
}
async function render(path: string, query = new QueryClient()) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  await act(() =>
    root.render(
      <StrictMode>
        <QueryClientProvider client={query}>
          <AuthProvider client={client}>
            <RouterProvider router={router} />
          </AuthProvider>
        </QueryClientProvider>
      </StrictMode>,
    ),
  );
  return router;
}
async function fill(name: string, value: string) {
  const input = container.querySelector<HTMLInputElement>(`[name="${name}"]`)!;
  await act(() => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function submit() {
  await act(() => {
    container
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}
test("registration rejects a mismatch, normalizes email, and clears secrets after success", async () => {
  await render("/register?next=%2Fjobs");
  await fill("email", "  Ana@Example.com  ");
  await fill("password", "correct horse");
  await fill("confirm", "different");
  await submit();
  expect(client.register).not.toHaveBeenCalled();
  expect(container.textContent).toContain("Passwords must match");
  await fill("confirm", "correct horse");
  await submit();
  expect(client.register).toHaveBeenCalledWith({
    email: "ana@example.com",
    password: "correct horse",
    confirm: "correct horse",
  });
  expect(container.querySelector("h1")?.textContent).toBe("Check your inbox.");
  expect(container.querySelector("input")).toBeNull();
  expect(
    container.querySelector('a[href="/login?next=%2Fjobs"]'),
  ).not.toBeNull();
});
test.each([
  [401, "don’t match"],
  [403, "Verify your email"],
  [429, "Too many attempts"],
  [500, "couldn’t reach"],
])(
  "login explains HTTP %s without exposing raw server data",
  async (status, message) => {
    vi.mocked(client.login).mockRejectedValue(
      new AuthError(status as number, { debug: "PRIVATE" }),
    );
    await render("/login");
    await fill("email", "ana@example.com");
    await fill("password", "incorrect");
    await submit();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      message,
    );
    expect(container.textContent).not.toContain("PRIVATE");
  },
);

test("registration explains an existing verified account and retains the sign-in destination", async () => {
  vi.mocked(client.register).mockRejectedValue(
    new AuthError(409, {
      error: { code: "409", detail: "Email already registered" },
    }),
  );
  await render("/register?next=%2Ffriends");
  await fill("email", "ana@example.com");
  await fill("password", "correct horse");
  await fill("confirm", "correct horse");
  await submit();
  expect(container.querySelector('[role="alert"]')?.textContent).toBe(
    "This email already has an account. Try signing in.",
  );
  expect(container.textContent).not.toContain("couldn’t reach");
  expect(
    container.querySelector('a[href="/login?next=%2Ffriends"]'),
  ).not.toBeNull();
  expect(
    container.querySelector<HTMLButtonElement>('[type="submit"]')?.disabled,
  ).toBe(false);
});

test("empty login password stays in the form without making a request", async () => {
  await render("/login");
  await fill("email", "ana@example.com");
  await submit();
  expect(client.login).not.toHaveBeenCalled();
  expect(container.textContent).toContain("Enter your password.");
  expect(document.activeElement?.id).toBe("auth-password");
});
test("backend 422 marks and focuses the permitted field", async () => {
  vi.mocked(client.login).mockRejectedValue(
    new AuthError(422, {
      error: { code: "422", detail: "body → email: invalid address" },
    }),
  );
  await render("/login");
  await fill("email", "ana@example.com");
  await fill("password", "password");
  await submit();
  expect(document.activeElement?.id).toBe("auth-email");
  expect(
    container.querySelector("#auth-email")?.getAttribute("aria-invalid"),
  ).toBe("true");
  expect(container.querySelector("#auth-email-error")?.textContent).toBe(
    "invalid address",
  );
});
test("pending submission is disabled and network failure remains retryable", async () => {
  let reject!: (error: Error) => void;
  vi.mocked(client.login).mockReturnValue(
    new Promise((_, fail) => {
      reject = fail;
    }),
  );
  await render("/login");
  await fill("email", "ana@example.com");
  await fill("password", "password");
  await submit();
  expect(
    container.querySelector<HTMLButtonElement>('[type="submit"]')?.disabled,
  ).toBe(true);
  await act(() => reject(new TypeError("offline")));
  expect(
    container.querySelector<HTMLButtonElement>('[type="submit"]')?.disabled,
  ).toBe(false);
  expect(container.textContent).toContain("couldn’t reach");
});
test("verification is single-flight under StrictMode and ignores an old route result", async () => {
  let resolve!: () => void;
  vi.mocked(client.verify)
    .mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    )
    .mockRejectedValueOnce(new AuthError(400, {}));
  const router = await render("/verify-email?token=first");
  expect(client.verify).toHaveBeenCalledTimes(1);
  await act(() => router.navigate("/verify-email?token=second"));
  expect(container.textContent).toContain(
    "invalid, expired or has been replaced",
  );
  await act(() => resolve());
  expect(container.textContent).not.toContain("Your email is confirmed");
});
test("missing token makes no verification request", async () => {
  await render("/verify-email");
  expect(client.verify).not.toHaveBeenCalled();
  expect(container.textContent).toContain("missing its verification token");
});
test("verification can retry a transient network error", async () => {
  vi.mocked(client.verify).mockRejectedValueOnce(new TypeError("offline"));
  await render("/verify-email?token=retry");
  await act(() => {
    Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent === "Try verification again")!
      .click();
  });
  expect(container.textContent).toContain("Your email is confirmed");
  expect(client.verify).toHaveBeenCalledTimes(2);
});
test("real gateway drives safe login redirect and sends the refresh token on logout", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(
      jsonResponse(
        JSON.stringify({
          access_token: "access-test",
          refresh_token: "refresh-test",
          token_type: "bearer",
        }),
      ),
    )
    .mockResolvedValueOnce(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetcher);
  client = createAuthGateway();
  const router = await render("/login?next=%2Fjobs%3Fview%3Dall%23latest");
  await fill("email", "ana@example.com");
  await fill("password", "password");
  await submit();
  expect(
    router.state.location.pathname +
      router.state.location.search +
      router.state.location.hash,
  ).toBe("/jobs?view=all#latest");
  await act(() => {
    Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent === "Sign out")!
      .click();
  });
  expect(router.state.location.pathname).toBe("/login");
  expect(client.getStatus()).toBe("anonymous");
  expect(fetcher.mock.calls[1][1].body).toBe(
    JSON.stringify({ refresh_token: "refresh-test" }),
  );
});
test("failed logout still clears local state and warns about server revocation", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(
          JSON.stringify({
            access_token: "access",
            refresh_token: "refresh",
            token_type: "bearer",
          }),
        ),
      )
      .mockRejectedValueOnce(new TypeError("offline")),
  );
  client = createAuthGateway();
  await client.login({ email: "a@example.com", password: "password" });
  const router = await render("/profile");
  await act(() => {
    Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent === "Sign out")!
      .click();
  });
  expect(client.getStatus()).toBe("anonymous");
  expect(router.state.location.search).toBe("?logout=local");
  expect(container.textContent).toContain("couldn’t revoke");
});
test("malformed successful responses never create an authenticated session", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse("{}")));
  const gateway = createAuthGateway();
  await expect(
    gateway.login({ email: "a@example.com", password: "password" }),
  ).rejects.toThrow();
  expect(gateway.getStatus()).toBe("anonymous");
});
test("a logout cannot be undone by an older in-flight login", async () => {
  let resolve!: (response: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    ),
  );
  const gateway = createAuthGateway();
  const login = gateway.login({ email: "a@example.com", password: "password" });
  await gateway.logout();
  resolve(
    jsonResponse(
      JSON.stringify({
        access_token: "a",
        refresh_token: "r",
        token_type: "bearer",
      }),
    ),
  );
  await login;
  expect(gateway.getStatus()).toBe("anonymous");
});
test("the shared session rotates before expiry and remains authenticated", async () => {
  vi.useFakeTimers();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(() =>
      jsonResponse(
        JSON.stringify({
          access_token: "a",
          refresh_token: "r",
          token_type: "bearer",
        }),
      ),
    ),
  );
  const gateway = createAuthGateway();
  await gateway.login({ email: "a@example.com", password: "password" });
  expect(gateway.getStatus()).toBe("authenticated");
  await vi.advanceTimersByTimeAsync(840_000);
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(gateway.getStatus()).toBe("authenticated");
});

test("reload holds the protected URL while a stored refresh token is verified once under StrictMode", async () => {
  setStoredRefreshToken("stored-refresh");
  let resolve!: (value: Response) => void;
  const fetcher = vi.fn().mockImplementation(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  vi.stubGlobal("fetch", fetcher);
  client = createAuthGateway();
  const router = await render("/friends?tab=pending#list");
  expect(container.textContent).toContain("Checking your session");
  expect(router.state.location.pathname).toBe("/friends");
  expect(fetcher).toHaveBeenCalledTimes(1);
  await act(async () => {
    resolve(
      jsonResponse(
        JSON.stringify({
          access_token: "restored",
          refresh_token: "rotated",
          token_type: "bearer",
        }),
      ),
    );
  });
  expect(client.getStatus()).toBe("authenticated");
  expect(
    router.state.location.pathname +
      router.state.location.search +
      router.state.location.hash,
  ).toBe("/friends?tab=pending#list");
  expect(getStoredRefreshToken()).toBe("rotated");
});

test("rejected restoration clears credentials and preserves the safe return route", async () => {
  setStoredRefreshToken("revoked-refresh");
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response("{}", { status: 401 })),
  );
  client = createAuthGateway();
  const router = await render("/friends?tab=pending");
  expect(client.getStatus()).toBe("anonymous");
  expect(router.state.location.pathname).toBe("/login");
  expect(new URLSearchParams(router.state.location.search).get("next")).toBe(
    "/friends?tab=pending",
  );
  expect(getStoredRefreshToken()).toBeNull();
});

test("login 401 uses the public endpoint and never triggers refresh or sends confirmation", async () => {
  setStoredRefreshToken("old-refresh");
  const fetcher = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        error: { code: "401", detail: "Invalid email or password" },
      }),
      { status: 401, headers: { "Content-Type": "application/json" } },
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  const gateway = createAuthGateway();
  await expect(
    gateway.login({ email: "a@example.com", password: "incorrect" }),
  ).rejects.toMatchObject({ status: 401 });
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][0]).toBe("/api/auth/login");
  expect(fetcher.mock.calls[0][1].headers.get("Authorization")).toBeNull();
});

test("shared-client 422 survives the adapter and focuses the email field", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          error: { code: "422", detail: "body → email: invalid address" },
        }),
        { status: 422, headers: { "Content-Type": "application/json" } },
      ),
    ),
  );
  client = createAuthGateway();
  await render("/login");
  await fill("email", "ana@example.com");
  await fill("password", "password");
  await submit();
  expect(document.activeElement?.id).toBe("auth-email");
});

test("private cached queries clear on account replacement but survive ordinary rotation", async () => {
  setTokens({ accessToken: "account-a", refreshToken: "refresh-a" });
  client = createAuthGateway();
  const query = new QueryClient();
  await render("/profile", query);
  query.setQueryData(["private-profile"], { name: "Account A" });
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      jsonResponse(
        JSON.stringify({
          access_token: "access-a-rotated",
          refresh_token: "refresh-a-rotated",
        }),
      ),
    ),
  );
  await act(() => refreshAccessToken());
  expect(query.getQueryData(["private-profile"])).toEqual({
    name: "Account A",
  });
  await act(() =>
    setTokens({ accessToken: "account-b", refreshToken: "refresh-b" }),
  );
  expect(client.getStatus()).toBe("authenticated");
  expect(query.getQueryData(["private-profile"])).toBeUndefined();
  expect(getAccessToken()).toBe("account-b");
});

test("temporary restoration failure preserves the protected route and offers retry", async () => {
  setStoredRefreshToken("saved-refresh");
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(new Response("{}", { status: 503 }))
      .mockResolvedValueOnce(
        jsonResponse(
          JSON.stringify({
            access_token: "restored",
            refresh_token: "rotated",
            token_type: "bearer",
          }),
        ),
      ),
  );
  client = createAuthGateway();
  const router = await render("/friends?tab=pending");
  expect(router.state.location.pathname).toBe("/friends");
  expect(container.textContent).toContain("Your saved sign-in has been kept");
  expect(getStoredRefreshToken()).toBe("saved-refresh");
  const retry = Array.from(container.querySelectorAll("button")).find(
    (button) => button.textContent === "Try again",
  )!;
  await act(() => retry.click());
  expect(client.getStatus()).toBe("authenticated");
  expect(router.state.location.pathname + router.state.location.search).toBe(
    "/friends?tab=pending",
  );
  expect(container.textContent).not.toContain(
    "Your saved sign-in has been kept",
  );
});

test("login offers a clickable recovery route without submitting credentials", async () => {
  const router = await render("/login");
  const link = container.querySelector<HTMLAnchorElement>(
    'a[href="/forgot-password"]',
  )!;
  expect(link.textContent).toBe("Forgot password?");
  await act(() => link.click());
  expect(router.state.location.pathname).toBe("/forgot-password");
  expect(client.login).not.toHaveBeenCalled();
});
