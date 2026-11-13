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
  const fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ id: 7 }), {
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetch);
  expect(await peopleApi.message(42)).toEqual({ id: 7 });
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ peer_user_id: 42 });
});

test("public profiles require the merged backend relationship ID contract", async () => {
  const data = {
    id: 42,
    first_name: "Ada",
    last_name: null,
    position: null,
    bio: null,
    avatar_url: "/avatar.png",
    is_online: false,
    friendship_status: "accepted",
  };
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(Response.json(data))
    .mockResolvedValueOnce(Response.json({ ...data, friendship_id: 81 }));
  vi.stubGlobal("fetch", fetch);
  await expect(peopleApi.profile(42)).rejects.toThrow();
  await expect(peopleApi.profile(42)).resolves.toMatchObject({
    id: 42,
    friendship_id: 81,
  });
});
