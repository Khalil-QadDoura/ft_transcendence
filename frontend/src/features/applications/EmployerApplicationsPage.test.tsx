import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { EmployerApplicationsPage } from "./EmployerApplicationsPage";
import type { ApplicationItem, CandidateFeedItem } from "./types";

// Mock the API module
vi.mock("./api", () => ({
  listJobApplications: vi.fn(),
  updateApplicationStatus: vi.fn(),
  getCandidateFeed: vi.fn(),
}));

// Mock WebSocket event hook
type WsCallback<T> = (payload: T) => void;
const wsListeners = new Map<string, WsCallback<unknown>>();

vi.mock("../../api/ws", () => ({
  useWsEvent: vi.fn((type: string, handler: WsCallback<unknown>) => {
    wsListeners.set(type, handler);
  }),
}));

let root: Root;
let container: HTMLDivElement;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mockApplications: ApplicationItem[] = [
  {
    id: 10,
    job_id: 101,
    applicant_id: 5,
    company_id: 12,
    intro_video_id: 20,
    status: "submitted",
    cover_note: "I have 5 years of React experience.",
    conversation_id: null,
    applied_at: "2026-11-12T10:00:00Z",
    updated_at: "2026-11-12T10:00:00Z",
    viewed_at: null,
    applicant_display_name: "Alice Smith",
    applicant_position: "Senior Frontend Engineer",
    intro_video_url: "https://storage.wozu.dev/videos/intro10.mp4",
  },
  {
    id: 11,
    job_id: 101,
    applicant_id: 7,
    company_id: 12,
    intro_video_id: 22,
    status: "shortlisted",
    cover_note: "Excited about the product vision.",
    conversation_id: null,
    applied_at: "2026-11-13T09:00:00Z",
    updated_at: "2026-11-14T11:00:00Z",
    viewed_at: "2026-11-14T10:00:00Z",
    applicant_display_name: "Bob Jones",
    applicant_position: "UI/UX Designer",
    intro_video_url: null,
  },
];

const mockFeedItems: CandidateFeedItem[] = [
  {
    id: 1,
    user_id: 5,
    duration_sec: 45,
    size_bytes: 1024000,
    content_type: "video/mp4",
    signed_url: "https://storage.wozu.dev/videos/pitch1.mp4",
    expires_sec: 300,
    created_at: "2026-11-10T12:00:00Z",
    author_name: "Alice Smith",
    author_position: "Senior Frontend Engineer",
  },
];

describe("EmployerApplicationsPage Component (FE-28)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    wsListeners.clear();
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

  const renderPage = async (jobId: string | number = 101) => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={[`/employer/jobs/${jobId}/applications`]}>
          <Routes>
            <Route
              path="/employer/jobs/:id/applications"
              element={<EmployerApplicationsPage />}
            />
          </Routes>
        </MemoryRouter>,
      );
    });
  };

  it("renders empty state when job has no applications", async () => {
    vi.mocked(api.listJobApplications).mockResolvedValueOnce({
      items: [],
      next_cursor: null,
    });

    await renderPage();

    expect(
      container.querySelector('[data-testid="empty-applications-card"]'),
    ).not.toBeNull();
    expect(container.textContent).toContain("No applications found");
  });

  it("renders list of applications and details with video player and cover note", async () => {
    vi.mocked(api.listJobApplications).mockResolvedValueOnce({
      items: mockApplications,
      next_cursor: null,
    });
    vi.mocked(api.updateApplicationStatus).mockResolvedValueOnce({
      ...mockApplications[0],
      status: "viewed",
    });

    await renderPage();

    expect(
      container.querySelector('[data-testid="application-item-10"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="application-item-11"]'),
    ).not.toBeNull();
    expect(container.textContent).toContain("Alice Smith");
    expect(container.textContent).toContain("Bob Jones");

    // Detail pane for first application
    expect(
      container.querySelector('[data-testid="candidate-video-player"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="cover-note-text"]')?.textContent,
    ).toContain("I have 5 years of React experience.");
  });

  it("auto-marks submitted application as viewed on selection", async () => {
    vi.mocked(api.listJobApplications).mockResolvedValueOnce({
      items: [mockApplications[0]],
      next_cursor: null,
    });
    vi.mocked(api.updateApplicationStatus).mockResolvedValueOnce({
      ...mockApplications[0],
      status: "viewed",
    });

    await renderPage();

    expect(api.updateApplicationStatus).toHaveBeenCalledWith(10, "viewed");
  });

  it("enforces allowed transitions strictly according to EMPLOYER_TRANSITIONS", async () => {
    // When application is shortlisted: allowed transitions are contacted, hired, rejected.
    vi.mocked(api.listJobApplications).mockResolvedValueOnce({
      items: [mockApplications[1]], // status: "shortlisted"
      next_cursor: null,
    });

    await renderPage();

    // Allowed
    expect(
      container.querySelector('[data-testid="transition-contacted"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="transition-hired"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="transition-rejected"]'),
    ).not.toBeNull();

    // Disallowed for 'shortlisted': submitted, viewed, withdrawn must NOT exist
    expect(
      container.querySelector('[data-testid="transition-submitted"]'),
    ).toBeNull();
    expect(
      container.querySelector('[data-testid="transition-viewed"]'),
    ).toBeNull();
    expect(
      container.querySelector('[data-testid="transition-withdrawn"]'),
    ).toBeNull();
  });

  it("handles transitioning status to contacted and opens linked conversation", async () => {
    vi.mocked(api.listJobApplications).mockResolvedValueOnce({
      items: [mockApplications[1]], // status: "shortlisted"
      next_cursor: null,
    });
    vi.mocked(api.updateApplicationStatus).mockResolvedValueOnce({
      ...mockApplications[1],
      status: "contacted",
      conversation_id: 88,
    });

    await renderPage();

    const contactBtn = container.querySelector(
      '[data-testid="transition-contacted"]',
    ) as HTMLButtonElement;
    expect(contactBtn).not.toBeNull();

    await act(async () => {
      contactBtn.click();
    });

    expect(api.updateApplicationStatus).toHaveBeenCalledWith(11, "contacted");

    const convLink = container.querySelector(
      '[data-testid="open-conversation-btn"]',
    ) as HTMLAnchorElement;
    expect(convLink).not.toBeNull();
    expect(convLink.getAttribute("href")).toBe("/chat/88");
  });

  it("displays inline error alert on 409 conflict during status transition", async () => {
    vi.mocked(api.listJobApplications).mockResolvedValueOnce({
      items: [mockApplications[1]],
      next_cursor: null,
    });
    vi.mocked(api.updateApplicationStatus).mockRejectedValueOnce(
      new Error("Invalid transition: status conflict"),
    );

    await renderPage();

    const rejectBtn = container.querySelector(
      '[data-testid="transition-rejected"]',
    ) as HTMLButtonElement;

    await act(async () => {
      rejectBtn.click();
    });

    expect(
      container.querySelector('[data-testid="status-error-alert"]'),
    ).not.toBeNull();
    expect(container.textContent).toContain("Invalid transition");
  });

  it("renders candidate pitch feed when feed tab is selected", async () => {
    vi.mocked(api.listJobApplications).mockResolvedValueOnce({
      items: [],
      next_cursor: null,
    });
    vi.mocked(api.getCandidateFeed).mockResolvedValueOnce({
      items: mockFeedItems,
      next_cursor: null,
    });

    await renderPage();

    const feedTab = container.querySelector(
      '[data-testid="tab-candidate-feed"]',
    ) as HTMLButtonElement;
    expect(feedTab).not.toBeNull();

    await act(async () => {
      feedTab.click();
    });

    expect(api.getCandidateFeed).toHaveBeenCalledWith(101, {
      cursor: undefined,
      limit: 20,
    });
    expect(
      container.querySelector('[data-testid="feed-item-1"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="feed-video-player"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="feed-author-name"]')?.textContent,
    ).toBe("Alice Smith");
  });

  it("handles live WebSocket application_created and application_updated events", async () => {
    vi.mocked(api.listJobApplications).mockResolvedValueOnce({
      items: [mockApplications[1]], // Bob Jones (id: 11)
      next_cursor: null,
    });

    await renderPage();

    // Trigger application_created
    const newApp: ApplicationItem = {
      id: 99,
      job_id: 101,
      applicant_id: 42,
      company_id: 12,
      intro_video_id: null,
      status: "submitted",
      cover_note: "Fresh applicant note",
      conversation_id: null,
      applied_at: "2026-11-23T12:00:00Z",
      updated_at: "2026-11-23T12:00:00Z",
      viewed_at: null,
      applicant_display_name: "Charlie Brown",
      applicant_position: "DevOps Engineer",
      intro_video_url: null,
    };

    await act(async () => {
      const createdHandler = wsListeners.get("application_created");
      createdHandler?.(newApp);
    });

    expect(
      container.querySelector('[data-testid="application-item-99"]'),
    ).not.toBeNull();
    expect(container.textContent).toContain("Charlie Brown");

    // Trigger application_updated
    await act(async () => {
      const updatedHandler = wsListeners.get("application_updated");
      updatedHandler?.({
        ...newApp,
        status: "hired",
      });
    });

    expect(
      container.querySelector(
        '[data-testid="application-item-99"] [data-testid="status-hired"]',
      ),
    ).not.toBeNull();
  });
});
