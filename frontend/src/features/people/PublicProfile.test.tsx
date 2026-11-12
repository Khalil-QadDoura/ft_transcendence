import { afterEach, expect, test, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { PublicProfile } from "./PublicProfile";
import { peopleApi, type Person } from "./api";
import { profileApi } from "../profile/api";

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
