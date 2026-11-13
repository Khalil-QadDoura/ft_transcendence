/**
 * Media & Video Resume API Client (FE-25)
 */

import { apiClient } from "../../api/client";
import type {
  MyVideosOut,
  VideoConfirmIn,
  VideoStatusOut,
  VideoUploadUrlIn,
  VideoUploadUrlOut,
} from "./types";

/**
 * Step 1: Request presigned upload URL from the backend.
 * Uses POST /api/media/intro-video/upload-url with fallback to /api/videos/upload-url.
 */
export async function requestVideoUploadUrl(
  params: VideoUploadUrlIn = {},
): Promise<VideoUploadUrlOut> {
  const body = {
    content_type: params.content_type ?? "video/mp4",
    ext: params.ext ?? "mp4",
    expires_sec: params.expires_sec ?? 900,
  };

  try {
    return await apiClient<VideoUploadUrlOut>("/media/intro-video/upload-url", {
      method: "POST",
      body,
    });
  } catch (err: unknown) {
    // Graceful fallback for alternate backend route mount
    if (
      typeof err === "object" &&
      err !== null &&
      "status" in err &&
      (err as { status: number }).status === 404
    ) {
      return await apiClient<VideoUploadUrlOut>("/videos/upload-url", {
        method: "POST",
        body,
      });
    }
    throw err;
  }
}

/**
 * Step 2: Upload recorded video Blob directly to presigned storage URL with progress reporting.
 * Must NOT send Authorization Bearer header to avoid 403 SignatureDoesNotMatch on MinIO.
 */
export function uploadVideoWithProgress(
  putUrl: string,
  blob: Blob,
  onProgress?: (percent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", putUrl);
    xhr.setRequestHeader("Content-Type", "video/mp4");

    if (xhr.upload && onProgress) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          const percent = Math.min(
            100,
            Math.round((event.loaded / event.total) * 100),
          );
          onProgress(percent);
        }
      };
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        if (onProgress) onProgress(100);
        resolve();
      } else {
        reject(
          new Error(
            `Upload failed with storage status ${xhr.status}: ${xhr.statusText}`,
          ),
        );
      }
    };

    xhr.onerror = () => {
      reject(
        new Error(
          "Network error during video upload. Please check connection and retry.",
        ),
      );
    };

    xhr.ontimeout = () => {
      reject(new Error("Video upload timed out. Please try again."));
    };

    xhr.send(blob);
  });
}

/**
 * Step 3: Confirm video upload with backend to verify file, save record and queue moderation.
 */
export async function confirmVideoUpload(
  payload: VideoConfirmIn,
): Promise<VideoStatusOut> {
  try {
    return await apiClient<VideoStatusOut>("/media/intro-video/confirm", {
      method: "POST",
      body: payload,
    });
  } catch (err: unknown) {
    if (
      typeof err === "object" &&
      err !== null &&
      "status" in err &&
      (err as { status: number }).status === 404
    ) {
      return await apiClient<VideoStatusOut>("/videos/confirm", {
        method: "POST",
        body: payload,
      });
    }
    throw err;
  }
}

/**
 * Fetch candidate's intro videos with signed playback URLs and moderation statuses.
 */
export async function listMyVideos(): Promise<MyVideosOut> {
  try {
    return await apiClient<MyVideosOut>("/media/intro-video/mine", {
      method: "GET",
    });
  } catch (err: unknown) {
    if (
      typeof err === "object" &&
      err !== null &&
      "status" in err &&
      (err as { status: number }).status === 404
    ) {
      return await apiClient<MyVideosOut>("/videos/mine", {
        method: "GET",
      });
    }
    throw err;
  }
}

/**
 * Post an approved video to the public employer feed.
 */
export async function postVideo(videoId: number): Promise<VideoStatusOut> {
  return await apiClient<VideoStatusOut>(`/media/intro-video/${videoId}/post`, {
    method: "POST",
  });
}

/**
 * Unpost a video from the feed.
 */
export async function unpostVideo(videoId: number): Promise<VideoStatusOut> {
  return await apiClient<VideoStatusOut>(
    `/media/intro-video/${videoId}/unpost`,
    {
      method: "POST",
    },
  );
}

/**
 * Soft delete an intro video.
 */
export async function deleteVideo(videoId: number): Promise<VideoStatusOut> {
  return await apiClient<VideoStatusOut>(
    `/media/intro-video/${videoId}/delete`,
    {
      method: "POST",
    },
  );
}
