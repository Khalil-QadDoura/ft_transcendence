import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ProfilePage } from "./ProfilePage";
import { profileApi, type Profile } from "./api";
import { ApiError } from "../../api/client";

const original: Profile = {
  id: 42,
  email: "profile@example.com",
  first_name: null,
  last_name: null,
  position: null,
  birth_date: null,
  bio: null,
  avatar_object_key: null,
  is_email_verified: true,
};
let root: Root;
let container: HTMLDivElement;
let cache: QueryClient;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  cache = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
});
afterEach(async () => {
  await act(() => root.unmount());
  cache.clear();
  container.remove();
  vi.restoreAllMocks();
});
async function render() {
  await act(async () => {
    root.render(
      <QueryClientProvider client={cache}>
        <ProfilePage />
      </QueryClientProvider>,
    );
  });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
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
test("incomplete profiles send only changed fields and show success after the response", async () => {
  vi.spyOn(profileApi, "get").mockResolvedValue(original);
  const patch = vi
    .spyOn(profileApi, "patch")
    .mockResolvedValue({ ...original, position: "Engineer" });
  await render();
  expect(
    container.querySelector<HTMLInputElement>('[type="email"]')!.readOnly,
  ).toBe(true);
  expect(container.textContent).toContain(
    "Photo uploads will be available soon",
  );
  expect(container.querySelector('[type="file"]')).toBeNull();
  await fill("position", " Engineer ");
  await submit();
  expect(patch).toHaveBeenCalledExactlyOnceWith({ position: "Engineer" });
  expect(container.querySelector('[role="status"]')?.textContent).toContain(
    "up to date",
  );
  await submit();
  expect(patch).toHaveBeenCalledTimes(1);
});
test("underage date prevents PATCH, focuses its input, and retains other edits", async () => {
  vi.spyOn(profileApi, "get").mockResolvedValue(original);
  const patch = vi.spyOn(profileApi, "patch");
  await render();
  await fill("position", "Designer");
  await fill("birth_date", `${new Date().getFullYear() - 5}-01-01`);
  await submit();
  expect(patch).not.toHaveBeenCalled();
  expect(document.activeElement).toBe(
    container.querySelector('[name="birth_date"]'),
  );
  expect(container.textContent).toContain("at least 18");
  expect(
    container.querySelector<HTMLInputElement>('[name="position"]')!.value,
  ).toBe("Designer");
});
test("server field errors preserve edits and focus the rejected field", async () => {
  vi.spyOn(profileApi, "get").mockResolvedValue(original);
  vi.spyOn(profileApi, "patch").mockRejectedValue(
    new ApiError(422, "422", "body → position: Position was rejected"),
  );
  await render();
  await fill("position", "Engineer");
  await submit();
  expect(container.textContent).toContain("Position was rejected");
  expect(document.activeElement).toBe(
    container.querySelector('[name="position"]'),
  );
  expect(container.querySelector('[role="status"]')).toBeNull();
});
test("failed save preserves edits without success and permits a retry", async () => {
  vi.spyOn(profileApi, "get").mockResolvedValue(original);
  const patch = vi
    .spyOn(profileApi, "patch")
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue({ ...original, first_name: "Zayid" });
  await render();
  await fill("first_name", "Zayid");
  await submit();
  expect(container.textContent).toContain("weren’t saved");
  expect(
    container.querySelector<HTMLInputElement>('[name="first_name"]')!.value,
  ).toBe("Zayid");
  expect(container.querySelector('[role="status"]')).toBeNull();
  await submit();
  expect(patch).toHaveBeenCalledTimes(2);
  expect(container.querySelector('[role="status"]')?.textContent).toContain(
    "up to date",
  );
});
test("load failures show retry instead of an editable blank profile", async () => {
  vi.spyOn(profileApi, "get")
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue(original);
  await render();
  expect(container.querySelector("form")).toBeNull();
  expect(container.textContent).toContain("couldn’t load");
  await act(async () => container.querySelector("button")!.click());
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
  expect(container.querySelector("form")).not.toBeNull();
});
