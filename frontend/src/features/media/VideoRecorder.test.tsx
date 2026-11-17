import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as mediaApi from "./api";
import { VideoRecorder } from "./VideoRecorder";

// Mock the API module
vi.mock("./api", () => ({
  requestVideoUploadUrl: vi.fn(),
  uploadVideoWithProgress: vi.fn(),
  confirmVideoUpload: vi.fn(),
}));

let root: Root;
let container: HTMLDivElement;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe("VideoRecorder Component (FE-25)", () => {
  let mockMediaStream: MediaStream;
  let mockTracks: Array<{ stop: ReturnType<typeof vi.fn> }>;

  beforeEach(() => {
    vi.clearAllMocks();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);

    mockTracks = [{ stop: vi.fn() }, { stop: vi.fn() }];
    mockMediaStream = {
      getTracks: vi.fn(() => mockTracks),
    } as unknown as MediaStream;

    // Mock navigator.mediaDevices.getUserMedia
    Object.defineProperty(navigator, "mediaDevices", {
      value: {
        getUserMedia: vi.fn().mockResolvedValue(mockMediaStream),
      },
      writable: true,
      configurable: true,
    });

    // Mock MediaRecorder
    class MockMediaRecorder {
      state = "inactive";
      ondataavailable: ((e: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;
      static isTypeSupported = vi.fn().mockReturnValue(true);

      start() {
        this.state = "recording";
      }
      stop() {
        this.state = "inactive";
        if (this.ondataavailable) {
          this.ondataavailable({
            data: new Blob(["dummy-video-data"], { type: "video/mp4" }),
          });
        }
        if (this.onstop) {
          this.onstop();
        }
      }
    }

    Object.assign(globalThis, {
      MediaRecorder: MockMediaRecorder as unknown as typeof MediaRecorder,
    });
    globalThis.URL.createObjectURL = vi
      .fn()
      .mockReturnValue("blob:mock-video-url");
    globalThis.URL.revokeObjectURL = vi.fn();
  });

  afterEach(async () => {
    await act(async () => {
      root.unmount();
    });
    container.remove();
    vi.restoreAllMocks();
  });

  it("renders idle state with start camera prompt", async () => {
    await act(async () => {
      root.render(<VideoRecorder />);
    });
    expect(container.textContent).toContain("Video Resume Recorder");
    expect(
      container.querySelector('[data-testid="start-camera-button"]'),
    ).not.toBeNull();
  });

  it("handles camera access grant and displays live preview", async () => {
    await act(async () => {
      root.render(<VideoRecorder />);
    });
    const startCamBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="start-camera-button"]',
    );
    await act(async () => {
      startCamBtn?.click();
    });

    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith(
      expect.objectContaining({ audio: true, video: expect.any(Object) }),
    );
    expect(
      container.querySelector('[data-testid="live-camera-preview"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="start-recording-button"]'),
    ).not.toBeNull();
  });

  it("handles camera permission denied with helpful error message", async () => {
    const permError = new Error("Permission denied");
    permError.name = "NotAllowedError";
    vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValueOnce(
      permError,
    );

    await act(async () => {
      root.render(<VideoRecorder />);
    });
    const startCamBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="start-camera-button"]',
    );
    await act(async () => {
      startCamBtn?.click();
    });

    expect(
      container.querySelector('[data-testid="error-message"]'),
    ).not.toBeNull();
    expect(container.textContent).toMatch(
      /Camera or microphone permission was denied/i,
    );
    expect(
      container.querySelector('[data-testid="retry-camera-button"]'),
    ).not.toBeNull();
  });

  it("starts recording, tracks elapsed time, and stops", async () => {
    vi.useFakeTimers();
    await act(async () => {
      root.render(<VideoRecorder maxDurationSec={10} />);
    });

    // Enable camera
    const startCamBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="start-camera-button"]',
    );
    await act(async () => {
      startCamBtn?.click();
    });

    // Start recording
    const recordBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="start-recording-button"]',
    );
    await act(async () => {
      recordBtn?.click();
    });

    expect(
      container.querySelector('[data-testid="stop-recording-button"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="recording-timer"]')?.textContent,
    ).toContain("00:00 / 00:10");

    // Advance 3 seconds
    await act(async () => {
      vi.advanceTimersByTime(3000);
    });
    expect(
      container.querySelector('[data-testid="recording-timer"]')?.textContent,
    ).toContain("00:03 / 00:10");

    // Click stop recording
    const stopBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="stop-recording-button"]',
    );
    await act(async () => {
      stopBtn?.click();
    });

    expect(
      container.querySelector('[data-testid="recorded-video-playback"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="retake-button"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="upload-button"]'),
    ).not.toBeNull();

    vi.useRealTimers();
  });

  it("allows retaking a video by clearing recorded blob and reopening camera", async () => {
    await act(async () => {
      root.render(<VideoRecorder />);
    });
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('[data-testid="start-camera-button"]')
        ?.click();
    });
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>(
          '[data-testid="start-recording-button"]',
        )
        ?.click();
    });
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>(
          '[data-testid="stop-recording-button"]',
        )
        ?.click();
    });
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('[data-testid="retake-button"]')
        ?.click();
    });

    expect(globalThis.URL.revokeObjectURL).toHaveBeenCalledWith(
      "blob:mock-video-url",
    );
    expect(
      container.querySelector('[data-testid="live-camera-preview"]'),
    ).not.toBeNull();
  });

  it("uploads recorded video with progress bar and calls confirm API", async () => {
    const mockOnSuccess = vi.fn();
    vi.mocked(mediaApi.requestVideoUploadUrl).mockResolvedValueOnce({
      object_key: "users/1/intro/test-uuid.mp4",
      put_url: "https://storage.local/files/upload",
      get_url: "https://storage.local/files/get",
      expires_sec: 900,
      max_bytes: 52428800,
    });

    vi.mocked(mediaApi.uploadVideoWithProgress).mockImplementationOnce(
      async (_url, _blob, onProgress) => {
        if (onProgress) {
          onProgress(50);
          onProgress(100);
        }
      },
    );

    vi.mocked(mediaApi.confirmVideoUpload).mockResolvedValueOnce({
      id: 42,
      moderation_status: "pending",
      lifecycle_status: "loaded",
    });

    await act(async () => {
      root.render(<VideoRecorder onUploadSuccess={mockOnSuccess} />);
    });

    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('[data-testid="start-camera-button"]')
        ?.click();
    });
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>(
          '[data-testid="start-recording-button"]',
        )
        ?.click();
    });
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>(
          '[data-testid="stop-recording-button"]',
        )
        ?.click();
    });
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('[data-testid="upload-button"]')
        ?.click();
    });

    expect(mediaApi.requestVideoUploadUrl).toHaveBeenCalled();
    expect(mediaApi.uploadVideoWithProgress).toHaveBeenCalledWith(
      "https://storage.local/files/upload",
      expect.any(Blob),
      expect.any(Function),
    );
    expect(mediaApi.confirmVideoUpload).toHaveBeenCalledWith({
      object_key: "users/1/intro/test-uuid.mp4",
      duration_sec: expect.any(Number),
      size_bytes: expect.any(Number),
      content_type: "video/mp4",
    });
    expect(mockOnSuccess).toHaveBeenCalledWith({
      id: 42,
      moderation_status: "pending",
      lifecycle_status: "loaded",
    });
    expect(container.textContent).toContain("Upload Complete!");
  });

  it("handles upload failure and allows retrying upload", async () => {
    vi.mocked(mediaApi.requestVideoUploadUrl).mockRejectedValueOnce(
      new Error("Storage server unreachable"),
    );

    await act(async () => {
      root.render(<VideoRecorder />);
    });
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('[data-testid="start-camera-button"]')
        ?.click();
    });
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>(
          '[data-testid="start-recording-button"]',
        )
        ?.click();
    });
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>(
          '[data-testid="stop-recording-button"]',
        )
        ?.click();
    });
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('[data-testid="upload-button"]')
        ?.click();
    });

    expect(container.textContent).toMatch(/Storage server unreachable/i);
    expect(container.textContent).toContain("Retry Upload");
  });
});
