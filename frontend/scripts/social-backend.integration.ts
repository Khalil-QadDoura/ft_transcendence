// Disposable loopback backend only; uses the real shared client and BE-22 routes.
import { afterAll, expect, test, vi } from "vitest";
import {
  createAuthGateway,
  type Credentials,
} from "../src/features/auth/gateway";
import { clearTokens } from "../src/api/client";
import { profileApi } from "../src/features/profile/api";
import { peopleApi } from "../src/features/people/api";
import { friendsApi } from "../src/features/people/friends";

const origin = process.env.WOZU_TEST_BACKEND_URL;
if (
  !origin ||
  !["localhost", "127.0.0.1", "[::1]"].includes(new URL(origin).hostname)
) {
  throw new Error("Use a disposable loopback backend with captured test mail.");
}
const realFetch = globalThis.fetch;
vi.stubGlobal(
  "fetch",
  (input: string | URL | Request, options?: RequestInit) => {
    const headers = new Headers(options?.headers);
    // Separate the test actors from other integration suites' rate-limit buckets.
    headers.set("X-Real-IP", "10.13.0.20");
    return realFetch(new URL(String(input), origin), { ...options, headers });
  },
);
const gateway = createAuthGateway();
async function signIn(credentials: Credentials) {
  clearTokens();
  await gateway.login(credentials);
}
async function createPerson(name: string) {
  const credentials = {
    email: `social-${crypto.randomUUID()}@example.com`,
    password: `Test-${crypto.randomUUID()}`,
  };
  await gateway.register(credentials);
  let link: string | undefined;
  for (let attempt = 0; attempt < 100; attempt++) {
    const mail = await realFetch(
      `${origin}/__review/mail?email=${encodeURIComponent(credentials.email)}`,
    );
    if (mail.ok) {
      link = ((await mail.json()) as { link: string }).link;
      break;
    }
    if (mail.status !== 404) throw new Error(`Inbox returned ${mail.status}`);
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  if (!link) throw new Error("Verification email did not arrive");
  await gateway.verify(new URL(link).searchParams.get("token")!);
  await signIn(credentials);
  const person = await profileApi.patch({
    first_name: name,
    bio: "Disposable social integration account",
  });
  return { ...credentials, id: person.id };
}
afterAll(() => {
  clearTokens();
  vi.unstubAllGlobals();
});

test("merged BE-22: profile privacy, incoming requests, decline, accept, reload, removal and chat", async () => {
  const alice = await createPerson("Alice");
  const bob = await createPerson("Bob");
  await signIn(alice);
  const initial = await peopleApi.profile(bob.id);
  expect(initial).toMatchObject({
    first_name: "Bob",
    friendship_status: null,
    friendship_id: null,
  });
  expect(initial).not.toHaveProperty("email");
  await peopleApi.add(bob.id);
  const sent = await peopleApi.profile(bob.id);
  expect(sent.friendship_status).toBe("pending_sent");
  expect(sent.friendship_id).toBeGreaterThan(0);
  await expect(peopleApi.add(bob.id)).rejects.toMatchObject({ status: 409 });
  await signIn(bob);
  const incoming = await friendsApi.requests();
  expect(incoming).toEqual([
    expect.objectContaining({ id: sent.friendship_id, requester_id: alice.id }),
  ]);
  expect(await peopleApi.profile(alice.id)).toMatchObject({
    friendship_status: "pending_received",
    friendship_id: sent.friendship_id,
  });
  await peopleApi.decline(incoming[0].id);
  expect(await friendsApi.requests()).toEqual([]);
  expect((await peopleApi.profile(alice.id)).friendship_id).toBeNull();
  await peopleApi.add(alice.id);
  await signIn(alice);
  const [request] = await friendsApi.requests();
  await peopleApi.accept(request.id);
  // Discard client credentials and sign in again: no relationship ID is retained in memory.
  await signIn(alice);
  const [friend] = await friendsApi.list();
  expect(friend).toMatchObject({
    user_id: bob.id,
    friendship_id: request.id,
    first_name: "Bob",
  });
  expect(await peopleApi.profile(bob.id)).toMatchObject({
    friendship_status: "accepted",
    friendship_id: request.id,
  });
  const conversation = await peopleApi.message(bob.id);
  expect(conversation.id).toBeGreaterThan(0);
  expect((await peopleApi.message(bob.id)).id).toBe(conversation.id);
  await peopleApi.remove(friend.friendship_id);
  expect(await friendsApi.list()).toEqual([]);
  expect((await peopleApi.profile(bob.id)).friendship_status).toBeNull();
  await signIn(bob);
  expect(await friendsApi.list()).toEqual([]);
});
