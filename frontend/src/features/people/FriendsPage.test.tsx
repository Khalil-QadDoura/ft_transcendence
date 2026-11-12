import { afterEach, expect, test, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { FriendsPage } from "./FriendsPage";
import { friendsApi } from "./friends";
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
