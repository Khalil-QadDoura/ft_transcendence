import { beforeEach, afterEach, expect, test, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { AccountSettings, ForgotPassword, ResetPassword } from "./AccountPages";
import { accountApi } from "./api";
import {
  ApiError,
  clearTokens,
  setTokens,
  getAccessToken,
} from "../../api/client";
let root: Root;
let container: HTMLDivElement;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(() => root.unmount());
  container.remove();
  clearTokens();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
async function render(path: string) {
  const router = createMemoryRouter(
    [
      { path: "/settings", element: <AccountSettings /> },
      { path: "/forgot-password", element: <ForgotPassword /> },
      { path: "/reset-password", element: <ResetPassword /> },
      { path: "/login", element: <p>Sign in</p> },
    ],
    { initialEntries: [path] },
  );
  await act(() => root.render(<RouterProvider router={router} />));
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
  await act(() =>
    container
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
}
test("missing reset token never presents a password submission", async () => {
  await render("/reset-password");
  expect(container.querySelector("form")).toBeNull();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain(
    "missing",
  );
});
test("forgot validates email and shows the same generic success", async () => {
  const forgot = vi
    .spyOn(accountApi, "forgot")
    .mockResolvedValue({ message: "anything" });
  await render("/forgot-password");
  await fill("email", "not-an-email");
  await submit();
  expect(forgot).not.toHaveBeenCalled();
  await fill("email", "person@example.com");
  await submit();
  expect(forgot).toHaveBeenCalledWith("person@example.com");
  expect(container.querySelector('[role="status"]')?.textContent).toContain(
    "If this email has an eligible account",
  );
});
test("reset requires matching passwords and redirects only after success", async () => {
  const reset = vi.spyOn(accountApi, "reset").mockResolvedValue();
  const router = await render("/reset-password?token=test-link");
  await fill("new_password", "new-password");
  await fill("confirm", "wrong");
  await submit();
  expect(reset).not.toHaveBeenCalled();
  await fill("confirm", "new-password");
  await submit();
  expect(reset).toHaveBeenCalledWith("test-link", "new-password");
  expect(router.state.location.pathname).toBe("/login");
});
test("expired reset remains on the page with a fresh-link action", async () => {
  vi.spyOn(accountApi, "reset").mockRejectedValue(
    new ApiError(400, "400", "Invalid or expired link"),
  );
  const router = await render("/reset-password?token=expired");
  await fill("new_password", "new-password");
  await fill("confirm", "new-password");
  await submit();
  expect(router.state.location.pathname).toBe("/reset-password");
  expect(container.querySelector('[role="alert"]')?.textContent).toContain(
    "Invalid or expired link",
  );
  expect(container.querySelector('a[href="/forgot-password"]')).not.toBeNull();
});
test("deletion requires confirmation, cancel sends nothing, failure stays visible", async () => {
  const remove = vi
    .spyOn(accountApi, "remove")
    .mockRejectedValue(new Error("offline"));
  await render("/settings");
  const button = () =>
    Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent === "Delete account",
    )!;
  await act(() => button().click());
  expect(remove).not.toHaveBeenCalled();
  await act(() =>
    Array.from(document.querySelectorAll("button"))
      .find((b) => b.textContent === "Keep my account")!
      .click(),
  );
  expect(remove).not.toHaveBeenCalled();
  await act(() => button().click());
  await act(() =>
    Array.from(document.querySelectorAll("button"))
      .find((b) => b.textContent === "Yes, delete my account")!
      .click(),
  );
  expect(remove).toHaveBeenCalledOnce();
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain(
    "try again",
  );
});
test("400 change-password preserves tokens; 204 clears them", async () => {
  setTokens({ accessToken: "test-access", refreshToken: "test-refresh" });
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Wrong current password" }), {
        status: 400,
      }),
    )
    .mockResolvedValueOnce(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetchMock);
  await expect(
    accountApi.change("wrong", "new-password"),
  ).rejects.toMatchObject({ status: 400 });
  expect(getAccessToken()).toBe("test-access");
  await accountApi.change("correct", "new-password");
  expect(getAccessToken()).toBeNull();
  expect(fetchMock.mock.calls).toHaveLength(2);
});
