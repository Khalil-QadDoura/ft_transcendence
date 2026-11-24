import { afterEach, expect, test, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { FriendsPage } from "./FriendsPage";
import { friendsApi } from "./friends";
import { ApiError } from "../../api/client";
import { peopleApi } from "./api";
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
afterEach(() => vi.restoreAllMocks());
test("failed accept rolls back the optimistic request removal", async () => {
  vi.spyOn(friendsApi, "list").mockResolvedValue([]);
  vi.spyOn(friendsApi, "requests").mockResolvedValue([
    { id: 81, requester_id: 42, addressee_id: 1, status: "pending" },
  ]);
  let reject!: (error: Error) => void;
  vi.spyOn(peopleApi, "accept").mockImplementation(
    () =>
      new Promise((_, no) => {
        reject = no;
      }),
  );
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
          <MemoryRouter>
            <FriendsPage />
          </MemoryRouter>
        </QueryClientProvider>,
      ),
    );
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    const click = async (text: string) =>
      act(async () =>
        Array.from(div.querySelectorAll("button"))
          .find((button) => button.textContent === text)!
          .click(),
      );
    await click("Requests");
    expect(
      div.querySelector('button[aria-label="Accept request from member 42"]'),
    ).not.toBeNull();
    expect(
      div.querySelector('button[aria-label="Decline request from member 42"]'),
    ).not.toBeNull();
    await click("Accept");
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(div.textContent).not.toContain("Request from member 42");
    await act(async () => reject(new Error("offline")));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(div.textContent).toContain("Request from member 42");
    expect(div.querySelector('[role="alert"]')?.textContent).toContain(
      "Please try again",
    );
    expect(peopleApi.accept).toHaveBeenCalledWith(81);
  } finally {
    await act(() => root.unmount());
    cache.clear();
    div.remove();
  }
});

test("failed removal stays in the dialog, restores the friend, and can be retried", async () => {
  const friend = {
    user_id: 42,
    friendship_id: 81,
    first_name: "Ada",
    last_name: "Lovelace",
    position: null,
    avatar_url: "/avatar.png",
    is_online: false,
  };
  let removed = false;
  vi.spyOn(friendsApi, "list").mockImplementation(async () =>
    removed ? [] : [friend],
  );
  vi.spyOn(friendsApi, "requests").mockResolvedValue([]);
  const remove = vi
    .spyOn(peopleApi, "remove")
    .mockRejectedValueOnce(new Error("offline"))
    .mockImplementationOnce(async () => {
      removed = true;
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
  const removeButton = (scope: Element) =>
    Array.from(scope.querySelectorAll("button")).find(
      (button) => button.textContent === "Remove friend",
    )!;
  try {
    await act(async () =>
      root.render(
        <QueryClientProvider client={cache}>
          <MemoryRouter>
            <FriendsPage />
          </MemoryRouter>
        </QueryClientProvider>,
      ),
    );
    await settle();
    await act(async () => removeButton(div).click());
    expect(remove).not.toHaveBeenCalled();
    let dialog = div.querySelector('[role="dialog"]')!;
    await act(async () => removeButton(dialog).click());
    await settle();
    dialog = div.querySelector('[role="dialog"]')!;
    expect(dialog.querySelector('[role="alert"]')?.textContent).toContain(
      "Please try again",
    );
    expect(div.querySelectorAll('[role="alert"]')).toHaveLength(1);
    expect(div.textContent).toContain("Ada Lovelace");
    expect(removeButton(dialog).disabled).toBe(false);
    await act(async () => removeButton(dialog).click());
    await settle();
    expect(div.querySelector('[role="dialog"]')).toBeNull();
    expect(div.textContent).not.toContain("Ada Lovelace");
    expect(remove.mock.calls).toEqual([[81], [81]]);
  } finally {
    await act(() => root.unmount());
    cache.clear();
    div.remove();
  }
});

test.each([404, 409])(
  "stale removal %s closes the dialog and reconciles the list",
  async (status) => {
    const friend = {
      user_id: 42,
      friendship_id: 81,
      first_name: "Ada",
      last_name: "Lovelace",
      position: null,
      avatar_url: "/avatar.png",
      is_online: false,
    };
    let removed = false;
    vi.spyOn(friendsApi, "list").mockImplementation(async () =>
      removed ? [] : [friend],
    );
    vi.spyOn(friendsApi, "requests").mockResolvedValue([]);
    const remove = vi
      .spyOn(peopleApi, "remove")
      .mockImplementation(async () => {
        removed = true;
        throw new ApiError(status, "changed", "Relationship changed");
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
    const removeButton = (scope: Element) =>
      Array.from(scope.querySelectorAll("button")).find(
        (button) => button.textContent === "Remove friend",
      )!;
    try {
      await act(async () =>
        root.render(
          <QueryClientProvider client={cache}>
            <MemoryRouter>
              <FriendsPage />
            </MemoryRouter>
          </QueryClientProvider>,
        ),
      );
      await settle();
      await act(async () => removeButton(div).click());
      expect(remove).not.toHaveBeenCalled();
      const dialog = div.querySelector('[role="dialog"]')!;
      await act(async () => removeButton(dialog).click());
      await settle();
      expect(div.querySelector('[role="dialog"]')).toBeNull();
      expect(div.querySelector('[role="alert"]')?.textContent).toContain(
        "connection changed",
      );
      expect(div.textContent).not.toContain("Ada Lovelace");
      expect(div.textContent).toContain("Open someone's profile");
      expect(remove.mock.calls).toEqual([[81]]);
    } finally {
      await act(() => root.unmount());
      cache.clear();
      div.remove();
    }
  },
);
