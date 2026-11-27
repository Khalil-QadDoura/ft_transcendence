import { afterEach, expect, test, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { PublicProfile } from "./PublicProfile";
import { peopleApi, type Person } from "./api";
import { profileApi } from "../profile/api";
import { ApiError } from "../../api/client";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
afterEach(() => vi.restoreAllMocks());
test.each([null, "pending_sent", "pending_received", "accepted"] as const)(
  "renders friendship state %s without exposing private email",
  async (status) => {
    vi.spyOn(profileApi, "get").mockResolvedValue({ id: 1 } as Awaited<
      ReturnType<typeof profileApi.get>
    >);
    vi.spyOn(peopleApi, "profile").mockResolvedValue({
      id: 2,
      first_name: "Ada",
      last_name: "Lovelace",
      position: "Engineer",
      bio: "Hello",
      avatar_url: "/avatar.png",
      is_online: true,
      friendship_status: status,
      friendship_id: 81,
    } as Person);
    const remove = vi.spyOn(peopleApi, "remove");
    const div = document.createElement("div");
    document.body.append(div);
    const root = createRoot(div);
    const cache = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    try {
      await act(async () =>
        root.render(
          <QueryClientProvider client={cache}>
            <MemoryRouter initialEntries={["/users/2"]}>
              <Routes>
                <Route path="/users/:id" element={<PublicProfile />} />
              </Routes>
            </MemoryRouter>
          </QueryClientProvider>,
        ),
      );
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
      });
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
      });
      expect(div.textContent).toContain("Ada Lovelace");
      expect(div.textContent).toContain("Online");
      expect(div.textContent).toContain(
        status === null
          ? "Add friend"
          : status === "pending_sent"
            ? "Request sent"
            : status === "pending_received"
              ? "Accept"
              : "Remove friend",
      );
      expect(remove).not.toHaveBeenCalled();
    } finally {
      await act(() => root.unmount());
      cache.clear();
      div.remove();
    }
  },
);

test("a conflicting friend request refreshes the relationship before another action", async () => {
  vi.spyOn(profileApi, "get").mockResolvedValue({ id: 1 } as Awaited<
    ReturnType<typeof profileApi.get>
  >);
  let changed = false;
  const profile = vi
    .spyOn(peopleApi, "profile")
    .mockImplementation(async () => ({
      id: 2,
      first_name: "Ada",
      last_name: "Lovelace",
      position: null,
      bio: null,
      avatar_url: "/avatar.png",
      is_online: false,
      friendship_status: changed ? "pending_received" : null,
      friendship_id: changed ? 81 : null,
    }));
  vi.spyOn(peopleApi, "add").mockImplementation(async () => {
    changed = true;
    throw new ApiError(409, "conflict", "A request already exists");
  });
  const div = document.createElement("div");
  document.body.append(div);
  const root = createRoot(div);
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  cache.setQueryDefaults(["friends"], { gcTime: Infinity });
  cache.setQueryData(["friends", "list"], []);
  try {
    await act(async () =>
      root.render(
        <QueryClientProvider client={cache}>
          <MemoryRouter initialEntries={["/users/2"]}>
            <Routes>
              <Route path="/users/:id" element={<PublicProfile />} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>,
      ),
    );
    const button = (label: string) =>
      Array.from(div.querySelectorAll("button")).find(
        (b) => b.textContent === label,
      );
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 100));
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 100));
    });
    expect(button("Add friend")).toBeDefined();
    await act(async () => button("Add friend")!.click());
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 100));
    });
    expect(button("Add friend")).toBeUndefined();
    expect(button("Accept")?.disabled).toBe(false);
    expect(div.querySelector('[role="alert"]')?.textContent).toContain(
      "connection changed",
    );
    expect(profile).toHaveBeenCalledTimes(2);
    expect(cache.getQueryState(["friends", "list"])?.isInvalidated).toBe(true);
  } finally {
    await act(() => root.unmount());
    cache.clear();
    div.remove();
  }
});

test.each(["remove", "accept", "decline", "cancel"] as const)(
  "reconciles a stale %s action after 404 and closes confirmation",
  async (action) => {
    vi.spyOn(profileApi, "get").mockResolvedValue({ id: 1 } as Awaited<
      ReturnType<typeof profileApi.get>
    >);
    let changed = false;
    vi.spyOn(peopleApi, "profile").mockImplementation(async () => ({
      id: 2,
      first_name: "Ada",
      last_name: null,
      position: null,
      bio: null,
      avatar_url: "/avatar.png",
      is_online: false,
      friendship_status: changed
        ? null
        : action === "remove"
          ? "accepted"
          : action === "cancel"
            ? "pending_sent"
            : "pending_received",
      friendship_id: changed ? null : 81,
    }));
    const call = vi
      .spyOn(peopleApi, action === "cancel" ? "remove" : action)
      .mockImplementation(async () => {
        changed = true;
        throw new ApiError(404, "missing", "Relationship no longer exists");
      });
    const div = document.createElement("div");
    document.body.append(div);
    const root = createRoot(div);
    const cache = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    const settle = () =>
      act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 60));
      });
    const click = (label: string, scope: Element = div) =>
      act(async () => {
        Array.from(scope.querySelectorAll("button"))
          .find((b) => b.textContent === label)!
          .click();
      });
    try {
      await act(async () =>
        root.render(
          <QueryClientProvider client={cache}>
            <MemoryRouter initialEntries={["/users/2"]}>
              <Routes>
                <Route path="/users/:id" element={<PublicProfile />} />
              </Routes>
            </MemoryRouter>
          </QueryClientProvider>,
        ),
      );
      await settle();
      await settle();
      const label =
        action === "remove"
          ? "Remove friend"
          : action === "cancel"
            ? "Cancel request"
            : action === "accept"
              ? "Accept"
              : "Decline";
      await click(label);
      if (action === "remove")
        await click(label, div.querySelector('[role="dialog"]')!);
      await settle();
      expect(div.querySelector('[role="dialog"]')).toBeNull();
      expect(div.textContent).toContain("Add friend");
      expect(div.querySelector('[role="alert"]')?.textContent).toContain(
        "connection changed",
      );
      expect(call.mock.calls).toEqual([[81]]);
    } finally {
      await act(() => root.unmount());
      cache.clear();
      div.remove();
    }
  },
);

test("updates online status live from presence store without page reload (FE-12)", async () => {
  const { presenceStore } = await import("../presence/presenceStore");
  presenceStore.reset();

  vi.spyOn(profileApi, "get").mockResolvedValue({ id: 1 } as Awaited<
    ReturnType<typeof profileApi.get>
  >);
  vi.spyOn(peopleApi, "profile").mockResolvedValue({
    id: 5,
    first_name: "Grace",
    last_name: "Hopper",
    position: "Admiral",
    bio: "Pioneer",
    avatar_url: "/avatar.png",
    is_online: false,
    friendship_status: "accepted",
    friendship_id: 99,
  } as Person);

  const div = document.createElement("div");
  document.body.append(div);
  const root = createRoot(div);
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });

  try {
    await act(async () =>
      root.render(
        <QueryClientProvider client={cache}>
          <MemoryRouter initialEntries={["/users/5"]}>
            <Routes>
              <Route path="/users/:id" element={<PublicProfile />} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>,
      ),
    );

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });

    expect(div.textContent).toContain("Grace Hopper");
    expect(div.textContent).toContain("Offline");

    // Live presence event: user 5 goes online
    await act(async () => {
      presenceStore.setPresence(5, true);
    });

    expect(div.textContent).toContain("Online");

    // Live presence event: user 5 goes offline (immediate)
    await act(async () => {
      presenceStore.setPresence(5, false, { immediate: true });
    });

    expect(div.textContent).toContain("Offline");
  } finally {
    presenceStore.reset();
    await act(() => root.unmount());
    cache.clear();
    div.remove();
  }
});
