import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, test, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { employerApi, jobForm, type OwnedJob } from "./api";
import { EmployerJobs } from "./EmployerJobs";
import { ApiError } from "../../api/client";
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
afterEach(() => vi.restoreAllMocks());
const values = {
  title: "Engineer",
  description: "Build with us",
  location: "Baku",
  latitude: "40.4",
  longitude: "49.8",
  status: "draft",
  salary_amount: "",
  salary_currency: "",
  salary_type: "monthly",
  schedule: "full_time",
  urgency: "normal",
};
const job = {
  ...jobForm.parse(values),
  id: 19,
  company_name: "Example",
  views_count: 7,
  applications_count: 3,
  new_applications_count: 2,
} satisfies OwnedJob;
test("preserves zero salary and converts blank salary to null", () => {
  expect(jobForm.parse(values).salary_amount).toBeNull();
  expect(jobForm.parse({ ...values, salary_amount: "0" }).salary_amount).toBe(
    "0",
  );
});
test.each([
  { latitude: "" },
  { latitude: "91" },
  { longitude: "-181" },
  { salary_amount: "1.234" },
  { salary_amount: "-1" },
  { salary_currency: "US" },
  { status: "deleted" },
  { title: "  " },
])("rejects invalid backend fields %j", (bad) => {
  expect(jobForm.safeParse({ ...values, ...bad }).success).toBe(false);
});
async function mount(path = "/employer/jobs") {
  const div = document.createElement("div");
  document.body.append(div);
  const root = createRoot(div);
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  await act(async () =>
    root.render(
      <QueryClientProvider client={cache}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/employer/jobs" element={<EmployerJobs />} />
            <Route path="/employer/jobs/new" element={<EmployerJobs />} />
            <Route path="/employer/jobs/:id/edit" element={<EmployerJobs />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await act(async () => {
    await new Promise((r) => setTimeout(r, 60));
  });
  return {
    div,
    close: async () => {
      await act(() => root.unmount());
      cache.clear();
      div.remove();
    },
  };
}
const click = async (scope: Element, label: string) =>
  act(async () => {
    Array.from(scope.querySelectorAll("button"))
      .find((b) => b.textContent === label)!
      .click();
  });
test("confirms deletion, retains dialog on failure and retries the same owned job", async () => {
  let removed = false;
  vi.spyOn(employerApi, "list").mockImplementation(async () =>
    removed ? [] : [job],
  );
  const remove = vi
    .spyOn(employerApi, "remove")
    .mockRejectedValueOnce(new Error("offline"))
    .mockImplementationOnce(async () => {
      removed = true;
    });
  const { div, close } = await mount();
  try {
    expect(div.textContent).toContain("Engineer");
    await click(div, "Delete");
    expect(remove).not.toHaveBeenCalled();
    await click(div.querySelector('[role="dialog"]')!, "Delete job");
    expect(
      div.querySelector('[role="dialog"] [role="alert"]')?.textContent,
    ).toContain("try again");
    await click(div.querySelector('[role="dialog"]')!, "Delete job");
    await act(async () => {
      await new Promise((r) => setTimeout(r, 60));
    });
    expect(div.querySelector('[role="dialog"]')).toBeNull();
    expect(remove.mock.calls).toEqual([[19], [19]]);
    expect(div.textContent).toContain("Your next great hire");
  } finally {
    await close();
  }
});
test("does not open another employer's job editor", async () => {
  vi.spyOn(employerApi, "list").mockResolvedValue([job]);
  const { div, close } = await mount("/employer/jobs/20/edit");
  try {
    expect(div.textContent).toContain("no longer available");
    expect(div.querySelector("form")).toBeNull();
  } finally {
    await close();
  }
});
test("explains the active-company requirement", async () => {
  vi.spyOn(employerApi, "list").mockRejectedValue(
    new ApiError(404, "not_found", "Active company not found"),
  );
  const { div, close } = await mount();
  try {
    expect(div.querySelector('[role="alert"]')?.textContent).toContain(
      "active company",
    );
  } finally {
    await close();
  }
});
test("creates a draft with the backend payload and returns to the list", async () => {
  vi.spyOn(employerApi, "list").mockResolvedValue([]);
  const save = vi.spyOn(employerApi, "save").mockResolvedValue(job);
  const { div, close } = await mount("/employer/jobs/new");
  try {
    for (const name of ["title", "latitude", "longitude"] as const) {
      div.querySelector<HTMLInputElement>(`[name="${name}"]`)!.value =
        values[name];
    }
    await act(async () => {
      div
        .querySelector("form")!
        .dispatchEvent(
          new Event("submit", { bubbles: true, cancelable: true }),
        );
    });
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Engineer",
        status: "draft",
        latitude: 40.4,
        longitude: 49.8,
        salary_amount: null,
      }),
      undefined,
    );
  } finally {
    await close();
  }
});
