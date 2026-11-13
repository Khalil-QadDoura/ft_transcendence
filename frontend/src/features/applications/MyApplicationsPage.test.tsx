import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { MyApplicationsPage } from "./MyApplicationsPage";
import type { ApplicationItem } from "./types";

// Mock the API module
vi.mock("./api", () => ({
  listMyApplications: vi.fn(),
  withdrawApplication: vi.fn(),
}));

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
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const renderWithRouter = (ui: React.ReactElement) => {
    return render(<BrowserRouter>{ui}</BrowserRouter>);
  };

  it("renders empty state when candidate has no applications", async () => {
    vi.mocked(api.listMyApplications).mockResolvedValueOnce({
      items: [],
      next_cursor: null,
    });

    renderWithRouter(<MyApplicationsPage />);

    expect(screen.getByTestId("applications-loading")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("empty-applications-card")).toBeInTheDocument();
      expect(screen.getByText("No applications found")).toBeInTheDocument();
    });
  });

  it("renders list of applications with job titles, companies and statuses", async () => {
    vi.mocked(api.listMyApplications).mockResolvedValueOnce({
      items: mockApplications,
      next_cursor: null,
    });

    renderWithRouter(<MyApplicationsPage />);

    await waitFor(() => {
      expect(screen.getByText("Senior React Engineer")).toBeInTheDocument();
      expect(screen.getByText("TechFlow Inc.")).toBeInTheDocument();
      expect(screen.getByTestId("status-submitted")).toBeInTheDocument();

      expect(screen.getByText("Full Stack Developer")).toBeInTheDocument();
      expect(screen.getByText("Nexus Labs")).toBeInTheDocument();
      expect(screen.getByTestId("status-invited")).toBeInTheDocument();

      // Open Chat button is present for application with conversation_id: 42
      expect(screen.getByTestId("chat-link-btn-2")).toBeInTheDocument();
    });
  });

  it("withdraws an application after user confirmation", async () => {
    vi.mocked(api.listMyApplications).mockResolvedValueOnce({
      items: [mockApplications[0]],
      next_cursor: null,
    });
    vi.mocked(api.withdrawApplication).mockResolvedValueOnce();

    renderWithRouter(<MyApplicationsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("withdraw-btn-1")).toBeInTheDocument();
    });

    // Click withdraw trigger
    fireEvent.click(screen.getByTestId("withdraw-btn-1"));

    // Confirmation box visible
    expect(screen.getByTestId("withdraw-confirm-box-1")).toBeInTheDocument();

    // Confirm withdraw
    fireEvent.click(screen.getByTestId("confirm-withdraw-btn-1"));

    await waitFor(() => {
      expect(api.withdrawApplication).toHaveBeenCalledWith(1);
      expect(screen.getByTestId("status-withdrawn")).toBeInTheDocument();
      expect(screen.queryByTestId("withdraw-btn-1")).not.toBeInTheDocument();
    });
  });

  it("filters applications when switching tabs", async () => {
    vi.mocked(api.listMyApplications)
      .mockResolvedValueOnce({
        items: mockApplications,
        next_cursor: null,
      })
      .mockResolvedValueOnce({
        items: [mockApplications[1]], // only invited
        next_cursor: null,
      });

    renderWithRouter(<MyApplicationsPage />);

    await waitFor(() => {
      expect(screen.getByText("Senior React Engineer")).toBeInTheDocument();
    });

    // Click Invited filter tab
    fireEvent.click(screen.getByTestId("filter-tab-invited"));

    await waitFor(() => {
      expect(api.listMyApplications).toHaveBeenCalledWith(
        expect.objectContaining({ status: "invited" }),
      );
      expect(screen.getByText("Full Stack Developer")).toBeInTheDocument();
    });
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

    renderWithRouter(<MyApplicationsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("load-more-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("load-more-btn"));

    await waitFor(() => {
      expect(api.listMyApplications).toHaveBeenCalledWith(
        expect.objectContaining({ cursor: 100 }),
      );
      expect(screen.getByText("Full Stack Developer")).toBeInTheDocument();
      expect(screen.queryByTestId("load-more-btn")).not.toBeInTheDocument();
    });
  });
});
