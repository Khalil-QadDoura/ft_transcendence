import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { JobsPage } from "./JobsPage";
import type { Job, JobListResponse } from "./types";

const mockJobs: Job[] = [
  {
    id: 1,
    owner_id: 10,
    company_name: "Acme Robotics",
    title: "Senior Frontend Engineer",
    description:
      "Building next generation web interfaces in React and Tailwind.",
    status: "active",
    latitude: 24.4539,
    longitude: 54.3773,
    location: "Abu Dhabi, UAE",
    salary_amount: 25000,
    salary_type: "monthly",
    salary_currency: "AED",
    schedule: "full_time",
    urgency: "hot",
    views_count: 42,
    applications_count: 5,
    created_at: "2026-11-10T10:00:00Z",
  },
  {
    id: 2,
    owner_id: 11,
    company_name: "Desert AI Labs",
    title: "AI Research Intern",
    description: "Working on LLM agents and multi-player gaming systems.",
    status: "active",
    latitude: 25.2048,
    longitude: 55.2708,
    location: "Dubai, UAE",
    salary_amount: 8000,
    salary_type: "monthly",
    salary_currency: "AED",
    schedule: "internship",
    urgency: "urgent",
    views_count: 89,
    applications_count: 12,
    created_at: "2026-11-09T14:30:00Z",
  },
];

let root: Root;
let container: HTMLDivElement;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function setNativeValue(
  element: HTMLInputElement | HTMLSelectElement,
  value: string,
) {
  const valueSetter = Object.getOwnPropertyDescriptor(element, "value")?.set;
  const prototype = Object.getPrototypeOf(element);
  const prototypeValueSetter = Object.getOwnPropertyDescriptor(
    prototype,
    "value",
  )?.set;

  if (prototypeValueSetter && valueSetter !== prototypeValueSetter) {
    prototypeValueSetter.call(element, value);
  } else if (valueSetter) {
    valueSetter.call(element, value);
  } else {
    element.value = value;
  }
}

describe("JobsPage (FE-23)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it("renders open jobs list with company, salary, urgency, and schedule badges", async () => {
    vi.spyOn(api, "fetchOpenJobs").mockResolvedValue({
      items: mockJobs,
      next_cursor: null,
    });

    const router = createMemoryRouter(
      [{ path: "/jobs", element: <JobsPage /> }],
      { initialEntries: ["/jobs"] },
    );

    await act(async () => {
      root.render(<RouterProvider router={router} />);
    });

    expect(container.textContent).toContain("Senior Frontend Engineer");
    expect(container.textContent).toContain("Acme Robotics");
    expect(container.textContent).toContain("AED 25,000 / monthly");
    expect(container.textContent).toContain("Hot 🔥");
    expect(container.textContent).toContain("Full time");

    expect(container.textContent).toContain("AI Research Intern");
    expect(container.textContent).toContain("Desert AI Labs");
    expect(container.textContent).toContain("Urgent ⚡");
    expect(container.textContent).toContain("Internship");
  });

  it("filters jobs by keyword search input", async () => {
    const fetchSpy = vi.spyOn(api, "fetchOpenJobs").mockResolvedValue({
      items: [mockJobs[0]],
      next_cursor: null,
    });

    const router = createMemoryRouter(
      [{ path: "/jobs", element: <JobsPage /> }],
      { initialEntries: ["/jobs"] },
    );

    await act(async () => {
      root.render(<RouterProvider router={router} />);
    });

    const keywordInput = container.querySelector(
      "#job-keyword-filter",
    ) as HTMLInputElement;
    expect(keywordInput).not.toBeNull();

    await act(async () => {
      setNativeValue(keywordInput, "Frontend");
      keywordInput.dispatchEvent(new Event("input", { bubbles: true }));
      keywordInput.dispatchEvent(new Event("change", { bubbles: true }));
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      expect.objectContaining({ keyword: "Frontend" }),
    );
  });

  it("filters by schedule dropdown", async () => {
    const fetchSpy = vi.spyOn(api, "fetchOpenJobs").mockResolvedValue({
      items: [mockJobs[1]],
      next_cursor: null,
    });

    const router = createMemoryRouter(
      [{ path: "/jobs", element: <JobsPage /> }],
      { initialEntries: ["/jobs"] },
    );

    await act(async () => {
      root.render(<RouterProvider router={router} />);
    });

    const scheduleSelect = container.querySelector(
      "#job-schedule-filter",
    ) as HTMLSelectElement;
    expect(scheduleSelect).not.toBeNull();

    await act(async () => {
      scheduleSelect.value = "internship";
      scheduleSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      expect.objectContaining({ schedule: "internship" }),
    );
  });

  it("handles cursor pagination with Load More button", async () => {
    const firstPage: JobListResponse = {
      items: [mockJobs[0]],
      next_cursor: 2,
    };
    const secondPage: JobListResponse = {
      items: [mockJobs[1]],
      next_cursor: null,
    };

    const fetchSpy = vi
      .spyOn(api, "fetchOpenJobs")
      .mockResolvedValueOnce(firstPage)
      .mockResolvedValueOnce(secondPage);

    const router = createMemoryRouter(
      [{ path: "/jobs", element: <JobsPage /> }],
      { initialEntries: ["/jobs"] },
    );

    await act(async () => {
      root.render(<RouterProvider router={router} />);
    });

    expect(container.textContent).toContain("Senior Frontend Engineer");

    // Click load more
    const buttons = Array.from(container.querySelectorAll("button"));
    const loadMoreButton = buttons.find((b) =>
      b.textContent?.includes("Load more jobs"),
    );
    expect(loadMoreButton).toBeDefined();

    await act(async () => {
      loadMoreButton?.click();
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      expect.objectContaining({ cursor: 2 }),
    );
    expect(container.textContent).toContain("Senior Frontend Engineer");
    expect(container.textContent).toContain("AI Research Intern");
  });

  it("displays empty state when no jobs match search criteria", async () => {
    vi.spyOn(api, "fetchOpenJobs").mockResolvedValue({
      items: [],
      next_cursor: null,
    });

    const router = createMemoryRouter(
      [{ path: "/jobs", element: <JobsPage /> }],
      { initialEntries: ["/jobs?keyword=NonExistentRole"] },
    );

    await act(async () => {
      root.render(<RouterProvider router={router} />);
    });

    expect(container.textContent).toContain("No open roles found");
    const resetButton = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent?.includes("Reset all filters"),
    );
    expect(resetButton).toBeDefined();

    await act(async () => {
      resetButton?.click();
    });

    const keywordInput = container.querySelector(
      "#job-keyword-filter",
    ) as HTMLInputElement;
    expect(keywordInput?.value).toBe("");
  });

  it("renders error alert with retry button when API fails", async () => {
    const fetchSpy = vi
      .spyOn(api, "fetchOpenJobs")
      .mockRejectedValueOnce(new Error("Network connection lost"))
      .mockResolvedValueOnce({ items: mockJobs, next_cursor: null });

    const router = createMemoryRouter(
      [{ path: "/jobs", element: <JobsPage /> }],
      { initialEntries: ["/jobs"] },
    );

    await act(async () => {
      root.render(<RouterProvider router={router} />);
    });

    expect(container.textContent).toContain("Network connection lost");
    const retryButton = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent?.includes("Retry"),
    );
    expect(retryButton).toBeDefined();

    await act(async () => {
      retryButton?.click();
    });

    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain("Senior Frontend Engineer");
  });

  it("handles geolocation request and updates filters", async () => {
    vi.spyOn(api, "fetchOpenJobs").mockResolvedValue({
      items: mockJobs,
      next_cursor: null,
    });

    const mockGeolocation = {
      getCurrentPosition: vi.fn().mockImplementation((success) => {
        success({
          coords: {
            latitude: 24.4539,
            longitude: 54.3773,
          },
        });
      }),
    };
    vi.stubGlobal("navigator", {
      ...navigator,
      geolocation: mockGeolocation,
    });

    const router = createMemoryRouter(
      [{ path: "/jobs", element: <JobsPage /> }],
      { initialEntries: ["/jobs"] },
    );

    await act(async () => {
      root.render(<RouterProvider router={router} />);
    });

    const locButton = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent?.includes("Use My Location"),
    );
    expect(locButton).toBeDefined();

    await act(async () => {
      locButton?.click();
    });

    expect(mockGeolocation.getCurrentPosition).toHaveBeenCalled();
    expect(container.textContent).toContain("Location Active");
  });
});
