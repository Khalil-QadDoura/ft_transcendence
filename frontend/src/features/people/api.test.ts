import { afterEach, expect, test, vi } from "vitest";
import { peopleApi, userId } from "./api";
afterEach(() => vi.unstubAllGlobals());
test("profile IDs reject paths, zero, fractions and oversized values", () => {
  for (const id of ["../me", 0, -1, 1.5, 2147483648])
    expect(userId.safeParse(id).success).toBe(false);
});
test("friend removal uses the relation ID, not the profile user ID", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetch);
  await peopleApi.remove(81);
  expect(fetch.mock.calls[0][0]).toBe("/api/friends/81");
  expect(fetch.mock.calls[0][1].method).toBe("DELETE");
});
test("direct conversation sends the backend peer_user_id contract", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue(
      new Response(JSON.stringify({ id: 7 }), {
        headers: { "Content-Type": "application/json" },
      }),
    );
  vi.stubGlobal("fetch", fetch);
  expect(await peopleApi.message(42)).toEqual({ id: 7 });
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ peer_user_id: 42 });
});
