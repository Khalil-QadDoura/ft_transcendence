import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import * as api from "./api";
import { JobDetailPage } from "./JobDetailPage";
import type { Job } from "./types";

const mockJob: Job = {
  id: 42,
  owner_id: 100,
  company_name: "Quantum Cloud",
  title: "Full Stack Engineer",
  description:
    "Exciting opportunity to build real-time distributed web systems.",
  status: "active",
  latitude: 24.4539,
  longitude: 54.3773,
  location: "Abu Dhabi",
  salary_amount: 30000,
  salary_type: "monthly",
  salary_currency: "AED",
  schedule: "full_time",
  urgency: "hot",
  views_count: 120,
  applications_count: 8,
  created_at: "2026-11-10T12:00:00Z",
};

let root: Root;
let container: HTMLDivElement;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function setNativeValue(
  element: HTMLInputElement | HTMLTextAreaElement,
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

describe("JobDetailPage (FE-24)", () => {
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

  it("renders job title, details, and records view on open", async () => {
    vi.spyOn(api, "fetchJobDetail").mockResolvedValue(mockJob);
    const viewSpy = vi.spyOn(api, "recordJobView").mockResolvedValue();

    const router = createMemoryRouter(
      [{ path: "/jobs/:id", element: <JobDetailPage /> }],
      { initialEntries: ["/jobs/42"] },
    );

    await act(async () => {
      root.render(<RouterProvider router={router} />);
    });

    expect(container.textContent).toContain("Full Stack Engineer");
    expect(container.textContent).toContain("Quantum Cloud");
    expect(container.textContent).toContain("AED 30,000 / monthly");
    expect(container.textContent).toContain("120 views");
    expect(container.textContent).toContain("8 candidates applied");
    expect(container.textContent).toContain(
      "Exciting opportunity to build real-time",
    );

    expect(viewSpy).toHaveBeenCalledWith("42");
  });

  it("opens apply modal and submits cover note successfully", async () => {
    vi.spyOn(api, "fetchJobDetail").mockResolvedValue(mockJob);
    vi.spyOn(api, "recordJobView").mockResolvedValue();
    const applySpy = vi
      .spyOn(api, "applyToJob")
      .mockResolvedValue({ id: 1, status: "pending" });

    const router = createMemoryRouter(
      [{ path: "/jobs/:id", element: <JobDetailPage /> }],
      { initialEntries: ["/jobs/42"] },
    );

    await act(async () => {
      root.render(<RouterProvider router={router} />);
    });

    // Click Apply button
    const applyButton = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent?.includes("Apply with Video"),
    );
    expect(applyButton).toBeDefined();

    await act(async () => {
      applyButton?.click();
    });

    // Modal dialog should be in document
    const textarea = document.querySelector(
      "#apply-cover-note",
    ) as HTMLTextAreaElement;
    expect(textarea).not.toBeNull();

    await act(async () => {
      setNativeValue(textarea, "I love this role!");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      textarea.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const submitBtn = Array.from(document.querySelectorAll("button")).find(
      (b) => b.textContent?.includes("Submit Application"),
    );
    expect(submitBtn).toBeDefined();

    await act(async () => {
      submitBtn?.click();
    });

    expect(applySpy).toHaveBeenCalledWith("42", "I love this role!");
    expect(container.textContent).toContain("Application submitted!");
  });

  it("handles profile_incomplete apply guard and offers navigation to /profile", async () => {
    vi.spyOn(api, "fetchJobDetail").mockResolvedValue(mockJob);
    vi.spyOn(api, "recordJobView").mockResolvedValue();

    // 422 error with next_step: profile
    const guardError = new ApiError(422, "profile_incomplete", {
      code: "profile_incomplete",
      next_step: "profile",
    });
    vi.spyOn(api, "applyToJob").mockRejectedValue(guardError);

    const router = createMemoryRouter(
      [{ path: "/jobs/:id", element: <JobDetailPage /> }],
      { initialEntries: ["/jobs/42"] },
    );

    await act(async () => {
      root.render(<RouterProvider router={router} />);
    });

    const applyButton = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent?.includes("Apply with Video"),
    );
    await act(async () => {
      applyButton?.click();
    });

    const submitBtn = Array.from(document.querySelectorAll("button")).find(
      (b) => b.textContent?.includes("Submit Application"),
    );
    await act(async () => {
      submitBtn?.click();
    });

    expect(document.body.textContent).toContain(
      "Your candidate profile is incomplete",
    );
    expect(document.body.textContent).toContain("Complete Profile Now →");
  });

  it("handles no_video apply guard and offers navigation to /videos", async () => {
    vi.spyOn(api, "fetchJobDetail").mockResolvedValue(mockJob);
    vi.spyOn(api, "recordJobView").mockResolvedValue();

    // 422 error with next_step: videos
    const guardError = new ApiError(422, "no_video", {
      code: "no_video",
      next_step: "videos",
    });
    vi.spyOn(api, "applyToJob").mockRejectedValue(guardError);

    const router = createMemoryRouter(
      [{ path: "/jobs/:id", element: <JobDetailPage /> }],
      { initialEntries: ["/jobs/42"] },
    );

    await act(async () => {
      root.render(<RouterProvider router={router} />);
    });

    const applyButton = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent?.includes("Apply with Video"),
    );
    await act(async () => {
      applyButton?.click();
    });

    const submitBtn = Array.from(document.querySelectorAll("button")).find(
      (b) => b.textContent?.includes("Submit Application"),
    );
    await act(async () => {
      submitBtn?.click();
    });

    expect(document.body.textContent).toContain(
      "WOZU requires a video introduction",
    );
    expect(document.body.textContent).toContain("Go to Video Resumes →");
  });

  it("renders 'View Applications' link when the job is owned by current user", async () => {
    vi.spyOn(api, "fetchJobDetail").mockResolvedValue(mockJob);
    vi.spyOn(api, "recordJobView").mockResolvedValue();

    const router = createMemoryRouter(
      [{ path: "/jobs/:id", element: <JobDetailPage currentUserId={100} /> }],
      { initialEntries: ["/jobs/42"] },
    );

    await act(async () => {
      root.render(<RouterProvider router={router} />);
    });

    expect(container.textContent).toContain("View Applications (8)");
    expect(container.textContent).not.toContain("Apply with Video");
  });
});
