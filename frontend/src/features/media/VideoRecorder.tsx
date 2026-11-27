import { localizeMessage } from "../../i18n/copy";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "../../components/Button";
import { Spinner } from "../../components/Spinner";
import { useText } from "../../i18n/useText";
import {
  confirmVideoUpload,
  requestVideoUploadUrl,
  uploadVideoWithProgress,
} from "./api";
import type { VideoRecorderState, VideoStatusOut } from "./types";

export interface VideoRecorderProps {
  maxDurationSec?: number;
  onUploadSuccess?: (result: VideoStatusOut) => void;
  onCancel?: () => void;
  className?: string;
}

export const VideoRecorder: React.FC<VideoRecorderProps> = ({
  maxDurationSec = 30,
  onUploadSuccess,
  onCancel,
  className = "",
}) => {
  const { t } = useText();
  const [state, setState] = useState<VideoRecorderState>("idle");
  const [elapsedSec, setElapsedSec] = useState<number>(0);
  const [uploadPercent, setUploadPercent] = useState<number>(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const [mediaStream, setMediaStream] = useState<MediaStream | null>(null);
  const [recordedBlob, setRecordedBlob] = useState<Blob | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  const previewVideoRef = useRef<HTMLVideoElement | null>(null);
  const playbackVideoRef = useRef<HTMLVideoElement | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const timerIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  mediaStreamRef.current = mediaStream;

  const stopTracks = useCallback(() => {
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
      setMediaStream(null);
    }
  }, []);

  // Cleanup media tracks and object URLs on unmount
  useEffect(() => {
    return () => {
      stopTracks();
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
      if (timerIntervalRef.current) {
        clearInterval(timerIntervalRef.current);
      }
    };
  }, [previewUrl, stopTracks]);

  /**
   * Request webcam and microphone access
   */
  const startCamera = async () => {
    setErrorMessage(null);
    setState("requesting_permission");

    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error(t("media.browserNotSupported"));
      }

      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          width: { ideal: 1280 },
          height: { ideal: 720 },
          facingMode: "user",
        },
        audio: true,
      });

      setMediaStream(stream);
      setState("ready");

      if (previewVideoRef.current) {
        previewVideoRef.current.srcObject = stream;
      }
    } catch (err: unknown) {
      stopTracks();
      setState("error");
      const error = err as { name?: string; message?: string };
      if (
        error.name === "NotAllowedError" ||
        error.name === "PermissionDeniedError"
      ) {
        setErrorMessage(t("media.permissionDenied"));
      } else if (
        error.name === "NotFoundError" ||
        error.name === "DevicesNotFoundError"
      ) {
        setErrorMessage(t("media.deviceNotFound"));
      } else {
        setErrorMessage(error.message || t("media.unableToAccess"));
      }
    }
  };

  /**
   * Start recording from the active MediaStream
   */
  const startRecording = () => {
    if (!mediaStream) return;

    setErrorMessage(null);
    chunksRef.current = [];
    setElapsedSec(0);

    try {
      // Find supported mime type
      let mimeType = "video/mp4";
      if (!MediaRecorder.isTypeSupported("video/mp4")) {
        if (MediaRecorder.isTypeSupported("video/webm;codecs=h264")) {
          mimeType = "video/webm;codecs=h264";
        } else if (MediaRecorder.isTypeSupported("video/webm")) {
          mimeType = "video/webm";
        }
      }

      const recorder = new MediaRecorder(mediaStream, {
        mimeType: MediaRecorder.isTypeSupported(mimeType)
          ? mimeType
          : undefined,
      });

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      recorder.onstop = () => {
        if (timerIntervalRef.current) {
          clearInterval(timerIntervalRef.current);
          timerIntervalRef.current = null;
        }

        const blob = new Blob(chunksRef.current, { type: "video/mp4" });
        setRecordedBlob(blob);

        if (previewUrl) {
          URL.revokeObjectURL(previewUrl);
        }
        const newUrl = URL.createObjectURL(blob);
        setPreviewUrl(newUrl);

        // Turn off camera tracks now that we have recorded
        stopTracks();
        setState("recorded");
      };

      mediaRecorderRef.current = recorder;
      recorder.start(500); // 500ms timeslices
      setState("recording");

      let seconds = 0;
      timerIntervalRef.current = setInterval(() => {
        seconds += 1;
        setElapsedSec(seconds);

        if (seconds >= maxDurationSec) {
          stopRecording();
        }
      }, 1000);
    } catch (err: unknown) {
      setState("error");
      const error = err as { message?: string };
      setErrorMessage(error.message || t("media.initFailed"));
    }
  };

  /**
   * Stop active recording
   */
  const stopRecording = () => {
    if (
      mediaRecorderRef.current &&
      mediaRecorderRef.current.state === "recording"
    ) {
      mediaRecorderRef.current.stop();
    }
  };

  /**
   * Discard current take and restart camera preview
   */
  const handleRetake = () => {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      setPreviewUrl(null);
    }
    setRecordedBlob(null);
    setElapsedSec(0);
    setUploadPercent(0);
    setErrorMessage(null);
    startCamera();
  };

  /**
   * Upload recorded blob to storage via presigned URL and confirm
   */
  const handleUpload = async () => {
    if (!recordedBlob) return;

    setState("uploading");
    setUploadPercent(0);
    setErrorMessage(null);

    try {
      // 1. Get presigned upload URL from API
      const uploadDetails = await requestVideoUploadUrl({
        content_type: "video/mp4",
        ext: "mp4",
      });

      // 2. Upload file directly to presigned storage endpoint with progress updates
      await uploadVideoWithProgress(
        uploadDetails.put_url,
        recordedBlob,
        (percent) => {
          setUploadPercent(percent);
        },
      );

      // 3. Confirm with backend
      const duration = Math.max(1, Math.min(maxDurationSec, elapsedSec || 1));
      const confirmedStatus = await confirmVideoUpload({
        object_key: uploadDetails.object_key,
        duration_sec: duration,
        size_bytes: recordedBlob.size,
        content_type: "video/mp4",
      });

      setState("success");
      if (onUploadSuccess) {
        onUploadSuccess(confirmedStatus);
      }
    } catch (err: unknown) {
      setState("error");
      const error = err as { message?: string };
      setErrorMessage(error.message || t("media.uploadFailed"));
    }
  };

  const formatTime = (totalSeconds: number) => {
    const mins = Math.floor(totalSeconds / 60);
    const secs = totalSeconds % 60;
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  return (
    <div
      className={`rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-gray-900 ${className}`}
      data-testid="video-recorder"
    >
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            {t("media.recorderTitle")}
          </h3>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {t("media.recorderSubtitle", { maxDuration: maxDurationSec })}
          </p>
        </div>
        {state === "recording" && (
          <div className="flex items-center gap-2 text-red-600 dark:text-red-400">
            <span className="relative flex h-3 w-3">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-75"></span>
              <span className="relative inline-flex h-3 w-3 rounded-full bg-red-500"></span>
            </span>
            <span
              className="font-mono text-sm font-bold"
              data-testid="recording-timer"
            >
              {formatTime(elapsedSec)} / {formatTime(maxDurationSec)}
            </span>
          </div>
        )}
      </div>

      {/* Video Viewport */}
      <div className="relative mb-6 flex aspect-video w-full items-center justify-center overflow-hidden rounded-lg bg-black text-white">
        {state === "idle" && (
          <div className="flex flex-col items-center justify-center p-6 text-center">
            <svg
              className="mb-3 h-12 w-12 text-gray-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
              />
            </svg>
            <p className="mb-4 text-sm text-gray-300">
              {t("media.cameraRequired")}
            </p>
            <Button
              onClick={startCamera}
              variant="primary"
              data-testid="start-camera-button"
            >
              {t("media.enableCamera")}
            </Button>
          </div>
        )}

        {state === "requesting_permission" && (
          <div className="flex flex-col items-center justify-center space-y-3">
            <Spinner size="lg" />
            <p className="text-sm text-gray-300">
              {t("media.requestingCamera")}
            </p>
          </div>
        )}

        {(state === "ready" || state === "recording") && (
          <video
            ref={(el) => {
              previewVideoRef.current = el;
              if (el && mediaStream && el.srcObject !== mediaStream) {
                el.srcObject = mediaStream;
              }
            }}
            autoPlay
            playsInline
            muted
            className="h-full w-full object-cover"
            data-testid="live-camera-preview"
          />
        )}

        {(state === "recorded" ||
          state === "uploading" ||
          state === "success") &&
          previewUrl && (
            <video
              ref={playbackVideoRef}
              src={previewUrl}
              controls
              playsInline
              className="h-full w-full object-cover"
              data-testid="recorded-video-playback"
            />
          )}

        {state === "error" && !mediaStream && (
          <div className="flex flex-col items-center justify-center p-6 text-center">
            <svg
              className="mb-3 h-12 w-12 text-red-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
              />
            </svg>
            <p
              className="mb-4 max-w-sm text-sm text-red-200"
              data-testid="error-message"
            >
              {localizeMessage(
                "screens",
                errorMessage ?? undefined,
                recordedBlob ? "media.uploadFailed" : "media.errorDefault",
              ) || t("media.errorDefault")}
            </p>
            <Button
              onClick={startCamera}
              variant="secondary"
              data-testid="retry-camera-button"
            >
              {t("media.tryAgain")}
            </Button>
          </div>
        )}

        {/* Uploading progress overlay */}
        {state === "uploading" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/80 p-6">
            <Spinner size="lg" className="mb-4 text-primary-500" />
            <p className="mb-2 text-sm font-medium text-white">
              {t("media.uploadingVideo")}
            </p>
            <div className="h-2.5 w-64 rounded-full bg-gray-700">
              <div
                className="h-2.5 rounded-full bg-primary-500 transition-all duration-300"
                style={{ width: `${uploadPercent}%` }}
                data-testid="upload-progress-bar"
              />
            </div>
            <span
              className="mt-2 text-xs text-gray-300 font-mono"
              data-testid="upload-percent"
            >
              {uploadPercent}%
            </span>
          </div>
        )}

        {/* Success overlay */}
        {state === "success" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/80 p-6 text-center">
            <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-green-500/20 text-green-400">
              <svg
                className="h-6 w-6"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M5 13l4 4L19 7"
                />
              </svg>
            </div>
            <h4 className="mb-1 text-base font-semibold text-white">
              {t("media.uploadComplete")}
            </h4>
            <p className="text-xs text-gray-300">
              {t("media.uploadCompleteDesc")}
            </p>
          </div>
        )}
      </div>

      {/* Error alert when in error state while video is visible */}
      {state === "error" && errorMessage && mediaStream && (
        <div className="mb-4 rounded-md bg-red-50 p-4 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">
          {localizeMessage(
            "screens",
            errorMessage ?? undefined,
            "media.uploadFailed",
          )}
        </div>
      )}

      {/* Control Buttons Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {onCancel && state !== "uploading" && (
            <Button
              onClick={onCancel}
              variant="ghost"
              data-testid="cancel-button"
            >
              {t("media.cancel")}
            </Button>
          )}
        </div>

        <div className="flex items-center gap-3">
          {state === "ready" && (
            <Button
              onClick={startRecording}
              variant="primary"
              className="bg-red-600 hover:bg-red-700 text-white"
              data-testid="start-recording-button"
            >
              {t("media.startRecording")}
            </Button>
          )}

          {state === "recording" && (
            <Button
              onClick={stopRecording}
              variant="danger"
              data-testid="stop-recording-button"
            >
              {t("media.stopRecording")}
            </Button>
          )}

          {state === "recorded" && (
            <>
              <Button
                onClick={handleRetake}
                variant="secondary"
                data-testid="retake-button"
              >
                {t("media.retake")}
              </Button>
              <Button
                onClick={handleUpload}
                variant="primary"
                data-testid="upload-button"
              >
                {t("media.uploadVideo")}
              </Button>
            </>
          )}

          {state === "error" && recordedBlob && (
            <>
              <Button onClick={handleRetake} variant="secondary">
                {t("media.retake")}
              </Button>
              <Button onClick={handleUpload} variant="primary">
                {t("media.retryUpload")}
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
