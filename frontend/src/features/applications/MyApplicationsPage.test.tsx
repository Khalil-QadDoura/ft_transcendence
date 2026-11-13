import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { MyApplicationsPage } from "./MyApplicationsPage";
import type { ApplicationItem } from "./types";

// Mock the API module
vi.mock("./api", () => ({
  listMyApplications: vi.fn(),
  withdrawApplication: vi.fn(),
}));

let root: Root;
let container: HTMLDivElement;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mockApplications: ApplicationItem[] = [
  {
    id: 1,
    job_id: 101,
    applicant_id: 5,
    company_id: 12,
    intro_video_id: 20,
    status: "submitted",
    cover_note: "Excited to join the engineering team!",
    conversation_id: null,
    applied_at: "2026-11-12T10:00:00Z",
    updated_at: "2026-11-12T10:00:00Z",
    viewed_at: null,
    job_title: "Senior React Engineer",
    company_name: "TechFlow Inc.",
  },
  {
    id: 2,
    job_id: 102,
    applicant_id: 5,
    company_id: 14,
    intro_video_id: 20,
    status: "invited",
    cover_note: null,
    conversation_id: 42,
    applied_at: "2026-11-11T09:00:00Z",
    updated_at: "2026-11-12T14:00:00Z",
    viewed_at: "2026-11-12T12:00:00Z",
    job_title: "Full Stack Developer",
    company_name: "Nexus Labs",
  },
];

describe("MyApplicationsPage Component (FE-15)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => {
      root.unmount();
    });
    container.remove();
    vi.restoreAllMocks();
  });

  const renderPage = async () => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <MyApplicationsPage />
        </MemoryRouter>,
      );
    });
  };

  it("renders empty state when candidate has no applications", async () => {
    vi.mocked(api.listMyApplications).mockResolvedValueOnce({
      items: [],
      next_cursor: null,
    });

    await renderPage();

    expect(
      container.querySelector('[data-testid="empty-applications-card"]'),
    ).not.toBeNull();
    expect(container.textContent).toContain("No applications found");
  });

  it("renders list of applications with job titles, companies and statuses", async () => {
    vi.mocked(api.listMyApplications).mockResolvedValueOnce({
      items: mockApplications,
      next_cursor: null,
    });

    await renderPage();

    expect(container.textContent).toContain("Senior React Engineer");
    expect(container.textContent).toContain("TechFlow Inc.");
    expect(
      container.querySelector('[data-testid="status-submitted"]'),
    ).not.toBeNull();

    expect(container.textContent).toContain("Full Stack Developer");
    expect(container.textContent).toContain("Nexus Labs");
    expect(
      container.querySelector('[data-testid="status-invited"]'),
    ).not.toBeNull();

    // Open Chat button is present for application with conversation_id: 42
    expect(
      container.querySelector('[data-testid="chat-link-btn-2"]'),
    ).not.toBeNull();
  });

  it("withdraws an application after user confirmation", async () => {
    vi.mocked(api.listMyApplications).mockResolvedValueOnce({
      items: [mockApplications[0]],
      next_cursor: null,
    });
    vi.mocked(api.withdrawApplication).mockResolvedValueOnce();

    await renderPage();

    const withdrawBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="withdraw-btn-1"]',
    );
    expect(withdrawBtn).not.toBeNull();

    // Click withdraw trigger
    await act(async () => {
      withdrawBtn?.click();
    });

    // Confirmation box visible
    expect(
      container.querySelector('[data-testid="withdraw-confirm-box-1"]'),
    ).not.toBeNull();

    // Confirm withdraw
    const confirmBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="confirm-withdraw-btn-1"]',
    );
    expect(confirmBtn).not.toBeNull();

    await act(async () => {
      confirmBtn?.click();
    });

    expect(api.withdrawApplication).toHaveBeenCalledWith(1);
    expect(
      container.querySelector('[data-testid="status-withdrawn"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="withdraw-btn-1"]'),
    ).toBeNull();
  });

  it("filters applications when switching tabs", async () => {
    vi.mocked(api.listMyApplications)
      .mockResolvedValueOnce({
        items: mockApplications,
        next_cursor: null,
      })
      .mockResolvedValueOnce({
        items: [mockApplications[1]],
        next_cursor: null,
      });

    await renderPage();

    expect(container.textContent).toContain("Senior React Engineer");

    // Click Invited filter tab
    const tabInvited = container.querySelector<HTMLButtonElement>(
      '[data-testid="filter-tab-invited"]',
    );
    expect(tabInvited).not.toBeNull();

    await act(async () => {
      tabInvited?.click();
    });

    expect(api.listMyApplications).toHaveBeenCalledWith(
      expect.objectContaining({ status: "invited" }),
    );
    expect(container.textContent).toContain("Full Stack Developer");
  });

  it("loads more applications using pagination cursor", async () => {
    vi.mocked(api.listMyApplications)
      .mockResolvedValueOnce({
        items: [mockApplications[0]],
        next_cursor: 100,
      })
      .mockResolvedValueOnce({
        items: [mockApplications[1]],
        next_cursor: null,
      });

    await renderPage();

    const loadMoreBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="load-more-btn"]',
    );
    expect(loadMoreBtn).not.toBeNull();

    await act(async () => {
      loadMoreBtn?.click();
    });

    expect(api.listMyApplications).toHaveBeenCalledWith(
      expect.objectContaining({ cursor: 100 }),
    );
    expect(container.textContent).toContain("Full Stack Developer");
    expect(container.querySelector('[data-testid="load-more-btn"]')).toBeNull();
  });
});
