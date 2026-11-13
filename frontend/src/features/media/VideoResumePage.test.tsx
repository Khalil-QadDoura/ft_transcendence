import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as mediaApi from "./api";
import type { MyVideoItem } from "./types";
import { VideoResumePage } from "./VideoResumePage";

// Mock the API module
vi.mock("./api", () => ({
  listMyVideos: vi.fn(),
  postVideo: vi.fn(),
  unpostVideo: vi.fn(),
  deleteVideo: vi.fn(),
  requestVideoUploadUrl: vi.fn(),
  uploadVideoWithProgress: vi.fn(),
  confirmVideoUpload: vi.fn(),
}));

// Mock WebSocket event hook
type WsCallback<T> = (payload: T) => void;
const wsListeners = new Map<string, WsCallback<unknown>>();

vi.mock("../../api/ws", () => ({
  useWsEvent: vi.fn((type: string, handler: WsCallback<unknown>) => {
    wsListeners.set(type, handler);
  }),
}));

const mockVideos: MyVideoItem[] = [
  {
    id: 1,
    object_key: "users/1/intro/vid-1.mp4",
    duration_sec: 28,
    size_bytes: 12 * 1024 * 1024,
    content_type: "video/mp4",
    moderation_status: "approved",
    lifecycle_status: "posted",
    created_at: "2026-11-12T10:00:00Z",
    updated_at: "2026-11-12T10:05:00Z",
    signed_url: "https://localhost/files/vid-1.mp4",
    expires_sec: 300,
  },
  {
    id: 2,
    object_key: "users/1/intro/vid-2.mp4",
    duration_sec: 25,
    size_bytes: 10 * 1024 * 1024,
    content_type: "video/mp4",
    moderation_status: "pending",
    lifecycle_status: "unposted",
    created_at: "2026-11-12T11:00:00Z",
    updated_at: "2026-11-12T11:00:00Z",
    signed_url: "https://localhost/files/vid-2.mp4",
    expires_sec: 300,
  },
];

describe("VideoResumePage Component (FE-26)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    wsListeners.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders empty state when user has no recordings", async () => {
    vi.mocked(mediaApi.listMyVideos).mockResolvedValueOnce({ items: [] });

    render(<VideoResumePage />);

    expect(screen.getByTestId("videos-loading")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("empty-videos-card")).toBeInTheDocument();
      expect(screen.getByText("No video résumé yet")).toBeInTheDocument();
      expect(screen.getByTestId("video-quota-counter")).toHaveTextContent(
        "0 / 3 Videos",
      );
    });
  });

  it("renders active recordings with quota, moderation badges and player", async () => {
    vi.mocked(mediaApi.listMyVideos).mockResolvedValueOnce({
      items: mockVideos,
    });

    render(<VideoResumePage />);

    await waitFor(() => {
      expect(screen.getByTestId("video-quota-counter")).toHaveTextContent(
        "2 / 3 Videos",
      );
      // Featured posted video section
      expect(screen.getByTestId("active-posted-section")).toBeInTheDocument();
      expect(screen.getByTestId("badge-approved")).toBeInTheDocument();
      expect(screen.getByTestId("badge-pending")).toBeInTheDocument();

      // Video cards rendered
      expect(screen.getByTestId("video-card-1")).toBeInTheDocument();
      expect(screen.getByTestId("video-card-2")).toBeInTheDocument();
    });
  });

  it("disables record CTA when quota limit of 3 is reached", async () => {
    const threeVideos: MyVideoItem[] = [
      ...mockVideos,
      {
        id: 3,
        object_key: "users/1/intro/vid-3.mp4",
        duration_sec: 30,
        size_bytes: 15 * 1024 * 1024,
        content_type: "video/mp4",
        moderation_status: "approved",
        lifecycle_status: "unposted",
        created_at: "2026-11-12T12:00:00Z",
        updated_at: "2026-11-12T12:00:00Z",
        signed_url: "https://localhost/files/vid-3.mp4",
        expires_sec: 300,
      },
    ];

    vi.mocked(mediaApi.listMyVideos).mockResolvedValueOnce({
      items: threeVideos,
    });

    render(<VideoResumePage />);

    await waitFor(() => {
      expect(screen.getByTestId("video-quota-counter")).toHaveTextContent(
        "3 / 3 Videos",
      );
      const recordBtn = screen.getByTestId("record-video-cta");
      expect(recordBtn).toBeDisabled();
      expect(
        screen.getByText(
          "Limit of 3 videos reached. Delete one to record a new one.",
        ),
      ).toBeInTheDocument();
    });
  });

  it("posts an approved unposted video to the feed", async () => {
    const unpostedApprovedVideo: MyVideoItem = {
      id: 2,
      object_key: "users/1/intro/vid-2.mp4",
      duration_sec: 25,
      size_bytes: 10 * 1024 * 1024,
      content_type: "video/mp4",
      moderation_status: "approved",
      lifecycle_status: "unposted",
      created_at: "2026-11-12T11:00:00Z",
      updated_at: "2026-11-12T11:00:00Z",
      signed_url: "https://localhost/files/vid-2.mp4",
      expires_sec: 300,
    };

    vi.mocked(mediaApi.listMyVideos)
      .mockResolvedValueOnce({ items: [unpostedApprovedVideo] })
      .mockResolvedValueOnce({
        items: [{ ...unpostedApprovedVideo, lifecycle_status: "posted" }],
      });

    vi.mocked(mediaApi.postVideo).mockResolvedValueOnce({
      id: 2,
      moderation_status: "approved",
      lifecycle_status: "posted",
    });

    render(<VideoResumePage />);

    await waitFor(() => {
      expect(screen.getByTestId("post-card-btn-2")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("post-card-btn-2"));

    await waitFor(() => {
      expect(mediaApi.postVideo).toHaveBeenCalledWith(2);
      expect(mediaApi.listMyVideos).toHaveBeenCalledTimes(2);
    });
  });

  it("unposts an active video from the feed", async () => {
    vi.mocked(mediaApi.listMyVideos)
      .mockResolvedValueOnce({ items: mockVideos })
      .mockResolvedValueOnce({
        items: [
          { ...mockVideos[0], lifecycle_status: "unposted" },
          mockVideos[1],
        ],
      });

    vi.mocked(mediaApi.unpostVideo).mockResolvedValueOnce({
      id: 1,
      moderation_status: "approved",
      lifecycle_status: "unposted",
    });

    render(<VideoResumePage />);

    await waitFor(() => {
      expect(screen.getByTestId("unpost-btn-1")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("unpost-btn-1"));

    await waitFor(() => {
      expect(mediaApi.unpostVideo).toHaveBeenCalledWith(1);
      expect(mediaApi.listMyVideos).toHaveBeenCalledTimes(2);
    });
  });

  it("deletes a video after user confirmation", async () => {
    vi.mocked(mediaApi.listMyVideos)
      .mockResolvedValueOnce({ items: mockVideos })
      .mockResolvedValueOnce({
        items: [mockVideos[0]], // video 2 removed
      });

    vi.mocked(mediaApi.deleteVideo).mockResolvedValueOnce({
      id: 2,
      moderation_status: "pending",
      lifecycle_status: "deleted",
    });

    render(<VideoResumePage />);

    await waitFor(() => {
      expect(screen.getByTestId("delete-card-btn-2")).toBeInTheDocument();
    });

    // Trigger delete
    fireEvent.click(screen.getByTestId("delete-card-btn-2"));

    // Confirmation prompt appears
    expect(screen.getByText("Confirm delete?")).toBeInTheDocument();

    // Click confirm delete
    fireEvent.click(screen.getByTestId("confirm-delete-btn-2"));

    await waitFor(() => {
      expect(mediaApi.deleteVideo).toHaveBeenCalledWith(2);
      expect(mediaApi.listMyVideos).toHaveBeenCalledTimes(2);
    });
  });

  it("handles live WebSocket video_moderated event and updates badge", async () => {
    vi.mocked(mediaApi.listMyVideos).mockResolvedValueOnce({
      items: mockVideos,
    });

    render(<VideoResumePage />);

    await waitFor(() => {
      expect(screen.getByTestId("badge-pending")).toBeInTheDocument();
    });

    // Fire WebSocket video_moderated event
    const moderatedHandler = wsListeners.get("video_moderated");
    expect(moderatedHandler).toBeDefined();

    moderatedHandler?.({
      id: 2,
      moderation_status: "approved",
    });

    await waitFor(() => {
      // Both video 1 and video 2 are now approved
      const approvedBadges = screen.getAllByTestId("badge-approved");
      expect(approvedBadges.length).toBeGreaterThanOrEqual(2);
    });
  });
});
