import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as mediaApi from "./api";
import { VideoRecorder } from "./VideoRecorder";

// Mock the API module
vi.mock("./api", () => ({
  requestVideoUploadUrl: vi.fn(),
  uploadVideoWithProgress: vi.fn(),
  confirmVideoUpload: vi.fn(),
}));

describe("VideoRecorder Component (FE-25)", () => {
  let mockMediaStream: MediaStream;
  let mockTracks: Array<{ stop: ReturnType<typeof vi.fn> }>;

  beforeEach(() => {
    vi.clearAllMocks();

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

    global.MediaRecorder = MockMediaRecorder as unknown as typeof MediaRecorder;
    global.URL.createObjectURL = vi.fn().mockReturnValue("blob:mock-video-url");
    global.URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders idle state with start camera prompt", () => {
    render(<VideoRecorder />);
    expect(screen.getByText("Video Resume Recorder")).toBeInTheDocument();
    expect(screen.getByTestId("start-camera-button")).toBeInTheDocument();
  });

  it("handles camera access grant and displays live preview", async () => {
    render(<VideoRecorder />);
    const startCamBtn = screen.getByTestId("start-camera-button");
    fireEvent.click(startCamBtn);

    await waitFor(() => {
      expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith(
        expect.objectContaining({ audio: true, video: expect.any(Object) }),
      );
      expect(screen.getByTestId("live-camera-preview")).toBeInTheDocument();
      expect(screen.getByTestId("start-recording-button")).toBeInTheDocument();
    });
  });

  it("handles camera permission denied with helpful error message", async () => {
    const permError = new Error("Permission denied");
    permError.name = "NotAllowedError";
    vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValueOnce(
      permError,
    );

    render(<VideoRecorder />);
    fireEvent.click(screen.getByTestId("start-camera-button"));

    await waitFor(() => {
      expect(screen.getByTestId("error-message")).toBeInTheDocument();
      expect(
        screen.getByText(/Camera or microphone permission was denied/i),
      ).toBeInTheDocument();
      expect(screen.getByTestId("retry-camera-button")).toBeInTheDocument();
    });
  });

  it("starts recording, tracks elapsed time, and stops", async () => {
    vi.useFakeTimers();
    render(<VideoRecorder maxDurationSec={10} />);

    // Enable camera
    fireEvent.click(screen.getByTestId("start-camera-button"));
    await vi.runAllTicks();

    // Start recording
    const recordBtn = await screen.findByTestId("start-recording-button");
    fireEvent.click(recordBtn);

    expect(screen.getByTestId("stop-recording-button")).toBeInTheDocument();
    expect(screen.getByTestId("recording-timer")).toHaveTextContent(
      "00:00 / 00:10",
    );

    // Advance 3 seconds
    vi.advanceTimersByTime(3000);
    expect(screen.getByTestId("recording-timer")).toHaveTextContent(
      "00:03 / 00:10",
    );

    // Click stop recording
    fireEvent.click(screen.getByTestId("stop-recording-button"));

    expect(screen.getByTestId("recorded-video-playback")).toBeInTheDocument();
    expect(screen.getByTestId("retake-button")).toBeInTheDocument();
    expect(screen.getByTestId("upload-button")).toBeInTheDocument();

    vi.useRealTimers();
  });

  it("allows retaking a video by clearing recorded blob and reopening camera", async () => {
    render(<VideoRecorder />);
    fireEvent.click(screen.getByTestId("start-camera-button"));

    const recordBtn = await screen.findByTestId("start-recording-button");
    fireEvent.click(recordBtn);

    const stopBtn = await screen.findByTestId("stop-recording-button");
    fireEvent.click(stopBtn);

    const retakeBtn = await screen.findByTestId("retake-button");
    fireEvent.click(retakeBtn);

    await waitFor(() => {
      expect(global.URL.revokeObjectURL).toHaveBeenCalledWith(
        "blob:mock-video-url",
      );
      expect(screen.getByTestId("live-camera-preview")).toBeInTheDocument();
    });
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

    render(<VideoRecorder onUploadSuccess={mockOnSuccess} />);

    // Start camera -> record -> stop
    fireEvent.click(screen.getByTestId("start-camera-button"));
    const recordBtn = await screen.findByTestId("start-recording-button");
    fireEvent.click(recordBtn);

    const stopBtn = await screen.findByTestId("stop-recording-button");
    fireEvent.click(stopBtn);

    // Upload
    const uploadBtn = await screen.findByTestId("upload-button");
    fireEvent.click(uploadBtn);

    await waitFor(() => {
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
      expect(screen.getByText("Upload Complete!")).toBeInTheDocument();
    });
  });

  it("handles upload failure and allows retrying upload", async () => {
    vi.mocked(mediaApi.requestVideoUploadUrl).mockRejectedValueOnce(
      new Error("Storage server unreachable"),
    );

    render(<VideoRecorder />);
    fireEvent.click(screen.getByTestId("start-camera-button"));

    const recordBtn = await screen.findByTestId("start-recording-button");
    fireEvent.click(recordBtn);

    const stopBtn = await screen.findByTestId("stop-recording-button");
    fireEvent.click(stopBtn);

    const uploadBtn = await screen.findByTestId("upload-button");
    fireEvent.click(uploadBtn);

    await waitFor(() => {
      expect(
        screen.getByText(/Storage server unreachable/i),
      ).toBeInTheDocument();
      expect(screen.getByText("Retry Upload")).toBeInTheDocument();
    });
  });
});
