import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
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

let root: Root;
let container: HTMLDivElement;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

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

  it("renders empty state when user has no recordings", async () => {
    vi.mocked(mediaApi.listMyVideos).mockResolvedValueOnce({ items: [] });

    await act(async () => {
      root.render(<VideoResumePage />);
    });

    expect(
      container.querySelector('[data-testid="empty-videos-card"]'),
    ).not.toBeNull();
    expect(container.textContent).toContain("No video résumé yet");
    expect(
      container.querySelector('[data-testid="video-quota-counter"]')
        ?.textContent,
    ).toContain("0 / 3 Videos");
  });

  it("renders active recordings with quota, moderation badges and player", async () => {
    vi.mocked(mediaApi.listMyVideos).mockResolvedValueOnce({
      items: mockVideos,
    });

    await act(async () => {
      root.render(<VideoResumePage />);
    });

    expect(
      container.querySelector('[data-testid="video-quota-counter"]')
        ?.textContent,
    ).toContain("2 / 3 Videos");
    expect(
      container.querySelector('[data-testid="active-posted-section"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="badge-approved"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="badge-pending"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="video-card-1"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="video-card-2"]'),
    ).not.toBeNull();
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

    await act(async () => {
      root.render(<VideoResumePage />);
    });

    expect(
      container.querySelector('[data-testid="video-quota-counter"]')
        ?.textContent,
    ).toContain("3 / 3 Videos");
    const recordBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="record-video-cta"]',
    );
    expect(recordBtn?.disabled).toBe(true);
    expect(container.textContent).toContain(
      "Limit of 3 videos reached. Delete one to record a new one.",
    );
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

    await act(async () => {
      root.render(<VideoResumePage />);
    });

    const postBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="post-card-btn-2"]',
    );
    expect(postBtn).not.toBeNull();

    await act(async () => {
      postBtn?.click();
    });

    expect(mediaApi.postVideo).toHaveBeenCalledWith(2);
    expect(mediaApi.listMyVideos).toHaveBeenCalledTimes(2);
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

    await act(async () => {
      root.render(<VideoResumePage />);
    });

    const unpostBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="unpost-btn-1"]',
    );
    expect(unpostBtn).not.toBeNull();

    await act(async () => {
      unpostBtn?.click();
    });

    expect(mediaApi.unpostVideo).toHaveBeenCalledWith(1);
    expect(mediaApi.listMyVideos).toHaveBeenCalledTimes(2);
  });

  it("deletes a video after user confirmation", async () => {
    vi.mocked(mediaApi.listMyVideos)
      .mockResolvedValueOnce({ items: mockVideos })
      .mockResolvedValueOnce({
        items: [mockVideos[0]],
      });

    vi.mocked(mediaApi.deleteVideo).mockResolvedValueOnce({
      id: 2,
      moderation_status: "pending",
      lifecycle_status: "deleted",
    });

    await act(async () => {
      root.render(<VideoResumePage />);
    });

    const deleteBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="delete-card-btn-2"]',
    );
    expect(deleteBtn).not.toBeNull();

    await act(async () => {
      deleteBtn?.click();
    });

    expect(container.textContent).toContain("Confirm delete?");

    const confirmBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="confirm-delete-btn-2"]',
    );
    expect(confirmBtn).not.toBeNull();

    await act(async () => {
      confirmBtn?.click();
    });

    expect(mediaApi.deleteVideo).toHaveBeenCalledWith(2);
    expect(mediaApi.listMyVideos).toHaveBeenCalledTimes(2);
  });

  it("handles live WebSocket video_moderated event and updates badge", async () => {
    vi.mocked(mediaApi.listMyVideos).mockResolvedValueOnce({
      items: mockVideos,
    });

    await act(async () => {
      root.render(<VideoResumePage />);
    });

    expect(
      container.querySelector('[data-testid="badge-pending"]'),
    ).not.toBeNull();

    const moderatedHandler = wsListeners.get("video_moderated");
    expect(moderatedHandler).toBeDefined();

    await act(async () => {
      moderatedHandler?.({
        id: 2,
        moderation_status: "approved",
      });
    });

    const approvedBadges = container.querySelectorAll(
      '[data-testid="badge-approved"]',
    );
    expect(approvedBadges.length).toBeGreaterThanOrEqual(2);
  });
});
