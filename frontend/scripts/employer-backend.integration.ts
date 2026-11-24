// Run only against the disposable captured-mail harness, never real accounts.
import { afterAll, expect, test, vi } from "vitest";
import { apiClient, clearTokens } from "../src/api/client";
import { createAuthGateway } from "../src/features/auth/gateway";
import { employerApi, jobForm } from "../src/features/employer/api";
const origin = process.env.WOZU_TEST_BACKEND_URL;
if (
  !origin ||
  !["127.0.0.1", "localhost", "[::1]"].includes(new URL(origin).hostname)
)
  throw new Error("Use the disposable loopback backend.");
const realFetch = globalThis.fetch;
vi.stubGlobal("fetch", (input: string | URL | Request, options?: RequestInit) =>
  realFetch(new URL(String(input), origin), options),
);
afterAll(() => {
  clearTokens();
  vi.unstubAllGlobals();
});
const gateway = createAuthGateway();
async function account() {
  clearTokens();
  const credentials = {
    email: `employer-${crypto.randomUUID()}@example.com`,
    password: `Test-${crypto.randomUUID()}`,
  };
  await gateway.register(credentials);
  const mail = await realFetch(
    `${origin}/__review/mail?email=${encodeURIComponent(credentials.email)}`,
  );
  expect(mail.status).toBe(200);
  const { link } = (await mail.json()) as { link: string };
  await gateway.verify(new URL(link).searchParams.get("token")!);
  await gateway.login(credentials);
  return credentials;
}
test("real backend: company prerequisite, draft, publish, owner isolation and soft delete", async () => {
  const owner = await account();
  await expect(employerApi.list()).rejects.toMatchObject({ status: 404 });
  await apiClient("/companies", {
    method: "POST",
    body: { name: "Employer integration" },
  });
  expect(await employerApi.list()).toEqual([]);
  const input = jobForm.parse({
    title: " Engineer ",
    description: "Build useful things",
    location: "Baku",
    latitude: "40.4",
    longitude: "49.8",
    status: "draft",
    salary_amount: "",
    salary_currency: "",
    salary_type: "monthly",
    schedule: "full_time",
    urgency: "normal",
  });
  const draft = await employerApi.save(input);
  expect(draft).toMatchObject({
    title: "Engineer",
    status: "draft",
    salary_amount: null,
    views_count: 0,
    applications_count: 0,
    new_applications_count: 0,
  });
  expect((await employerApi.list()).map((j) => j.id)).toContain(draft.id);
  const published = await employerApi.save(
    {
      ...input,
      title: "Senior Engineer",
      status: "open",
      salary_amount: "0",
      salary_currency: "AZN",
    },
    draft.id,
  );
  expect(published).toMatchObject({
    title: "Senior Engineer",
    status: "open",
    salary_currency: "AZN",
  });
  expect(Number(published.salary_amount)).toBe(0);
  await account();
  await apiClient("/companies", {
    method: "POST",
    body: { name: "Other employer" },
  });
  expect(await employerApi.list()).toEqual([]);
  await expect(employerApi.save(input, draft.id)).rejects.toMatchObject({
    status: 404,
  });
  await expect(employerApi.remove(draft.id)).rejects.toMatchObject({
    status: 404,
  });
  await gateway.login(owner);
  await employerApi.remove(draft.id);
  expect(await employerApi.list()).toEqual([]);
  await expect(apiClient(`/jobs/${draft.id}`)).rejects.toMatchObject({
    status: 404,
  });
});
