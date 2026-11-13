import React, { useCallback, useEffect, useRef, useState } from "react";
import { useWsEvent } from "../../api/ws";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { Spinner } from "../../components/Spinner";
import { deleteVideo, listMyVideos, postVideo, unpostVideo } from "./api";
import type { MyVideoItem, WsVideoModeratedPayload } from "./types";
import { VideoRecorderModal } from "./VideoRecorderModal";

const MAX_VIDEOS = 3;
const POLLING_INTERVAL_MS = 5000;

export const VideoResumePage: React.FC = () => {
  const [videos, setVideos] = useState<MyVideoItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [actionLoading, setActionLoading] = useState<number | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const pollingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchVideos = useCallback(async (silent = false) => {
    try {
      if (!silent) setLoading(true);
      setError(null);
      const res = await listMyVideos();
      setVideos(res.items || []);
    } catch (err: unknown) {
      const e = err as { message?: string };
      if (!silent) {
        setError(e.message || "Failed to load video résumés.");
        setVideos([]);
      }
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchVideos();
  }, [fetchVideos]);

  // Real-time WebSocket listener for AI video moderation status
  useWsEvent<WsVideoModeratedPayload>("video_moderated", (payload) => {
    if (!payload || !payload.id) return;
    setVideos((prevList) =>
      prevList.map((video) =>
        video.id === payload.id
          ? { ...video, moderation_status: payload.moderation_status }
          : video,
      ),
    );
  });

  // Polling fallback when any video is still pending moderation
  const activeVideos = videos.filter((v) => v.lifecycle_status !== "deleted");
  const hasPendingVideos = activeVideos.some(
    (v) => v.moderation_status === "pending",
  );

  useEffect(() => {
    if (hasPendingVideos) {
      pollingTimerRef.current = setTimeout(() => {
        void fetchVideos(true);
      }, POLLING_INTERVAL_MS);
    }

    return () => {
      if (pollingTimerRef.current) {
        clearTimeout(pollingTimerRef.current);
      }
    };
  }, [hasPendingVideos, fetchVideos]);

  const handlePost = async (id: number) => {
    setActionLoading(id);
    try {
      await postVideo(id);
      await fetchVideos(true);
    } catch (err: unknown) {
      const e = err as { message?: string };
      setError(e.message || "Failed to post video.");
    } finally {
      setActionLoading(null);
    }
  };

  const handleUnpost = async (id: number) => {
    setActionLoading(id);
    try {
      await unpostVideo(id);
      await fetchVideos(true);
    } catch (err: unknown) {
      const e = err as { message?: string };
      setError(e.message || "Failed to unpost video.");
    } finally {
      setActionLoading(null);
    }
  };

  const handleDelete = async (id: number) => {
    setActionLoading(id);
    try {
      await deleteVideo(id);
      setConfirmDeleteId(null);
      await fetchVideos(true);
    } catch (err: unknown) {
      const e = err as { message?: string };
      setError(e.message || "Failed to delete video.");
    } finally {
      setActionLoading(null);
    }
  };

  const getModerationBadge = (status: string) => {
    switch (status) {
      case "approved":
        return (
          <Badge variant="success" data-testid="badge-approved">
            ✓ Approved
          </Badge>
        );
      case "pending":
        return (
          <span
            className="inline-flex items-center space-x-1.5 rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-950/50 dark:text-amber-300"
            data-testid="badge-pending"
          >
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500"></span>
            <span>In Review</span>
          </span>
        );
      case "rejected":
        return (
          <Badge variant="danger" data-testid="badge-rejected">
            Needs Attention
          </Badge>
        );
      case "moderation_error":
        return (
          <Badge variant="warning" data-testid="badge-moderation-error">
            Review Incomplete
          </Badge>
        );
      default:
        return <Badge variant="neutral">{status}</Badge>;
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (!bytes || bytes <= 0) return "";
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const postedVideo = activeVideos.find((v) => v.lifecycle_status === "posted");
  const isAtLimit = activeVideos.length >= MAX_VIDEOS;

  return (
    <div
      className="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8"
      data-testid="video-resume-page"
    >
      {/* Header section with quota and action button */}
      <div className="mb-8 flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <div className="flex items-center space-x-3">
            <h1 className="text-3xl font-bold tracking-tight text-gray-900 dark:text-gray-100">
              My Video Résumés
            </h1>
            <span
              className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-semibold text-gray-600 dark:bg-gray-800 dark:text-gray-300"
              data-testid="video-quota-counter"
            >
              {activeVideos.length} / {MAX_VIDEOS} Videos
            </span>
          </div>
          <p className="mt-1 text-base text-gray-600 dark:text-gray-400">
            A 30-second introduction that brings your story, skills, and personality to life.
          </p>
        </div>

        <div className="flex flex-col items-end">
          <Button
            onClick={() => setIsModalOpen(true)}
            variant="primary"
            disabled={isAtLimit}
            data-testid="record-video-cta"
          >
            {activeVideos.length === 0 ? "Record Your Pitch" : "Record New Video"}
          </Button>
          {isAtLimit && (
            <span className="mt-1 text-xs text-amber-600 dark:text-amber-400">
              Limit of {MAX_VIDEOS} videos reached. Delete one to record a new one.
            </span>
          )}
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-6 flex items-center justify-between rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300"
        >
          <span>{error}</span>
          <button
            type="button"
            onClick={() => setError(null)}
            className="text-xs font-semibold underline hover:no-underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-16" data-testid="videos-loading">
          <Spinner size="lg" />
        </div>
      ) : activeVideos.length === 0 ? (
        <Card className="mb-10 p-10 text-center" data-testid="empty-videos-card">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-primary-50 text-primary-600 dark:bg-primary-950/50 dark:text-primary-400">
            <svg className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
              />
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            No video résumé yet
          </h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-gray-500 dark:text-gray-400">
            Companies receive dozens of identical text CVs. A short 30-second video introduction
            dramatically increases your interview callback rate.
          </p>
          <div className="mt-6">
            <Button onClick={() => setIsModalOpen(true)} variant="primary">
              Record Your Video Now
            </Button>
          </div>
        </Card>
      ) : (
        <div className="mb-10 space-y-6">
          {/* Active Featured Video */}
          {postedVideo && (
            <div className="mb-8" data-testid="active-posted-section">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                  Featured in Employer Feed
                </h2>
                <Badge variant="primary">Active Pitch</Badge>
              </div>

              <Card className="overflow-hidden ring-2 ring-primary-500/30">
                <div className="grid grid-cols-1 gap-6 p-6 md:grid-cols-12">
                  <div className="relative aspect-video w-full overflow-hidden rounded-lg bg-black md:col-span-7">
                    <video
                      src={postedVideo.signed_url}
                      controls
                      playsInline
                      className="h-full w-full object-contain"
                      data-testid={`video-player-${postedVideo.id}`}
                    />
                  </div>

                  <div className="flex flex-col justify-between md:col-span-5">
                    <div>
                      <div className="flex items-center space-x-2">
                        {getModerationBadge(postedVideo.moderation_status)}
                        <span className="text-xs font-mono text-gray-400">
                          {postedVideo.duration_sec}s · {formatFileSize(postedVideo.size_bytes)}
                        </span>
                      </div>

                      <h3 className="mt-3 text-base font-medium text-gray-900 dark:text-gray-100">
                        Primary Introduction
                      </h3>
                      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                        This video is currently visible to prospective employers on the discovery feed.
                      </p>
                      <p className="mt-2 text-xs text-gray-400">
                        Recorded on {new Date(postedVideo.created_at).toLocaleDateString()}
                      </p>
                    </div>

                    <div className="mt-6 flex items-center space-x-3 border-t border-gray-100 pt-4 dark:border-gray-800">
                      <Button
                        onClick={() => handleUnpost(postedVideo.id)}
                        variant="secondary"
                        size="sm"
                        disabled={actionLoading === postedVideo.id}
                        data-testid={`unpost-btn-${postedVideo.id}`}
                      >
                        {actionLoading === postedVideo.id ? "Unposting..." : "Unpost from Feed"}
                      </Button>
                      <Button
                        onClick={() => setConfirmDeleteId(postedVideo.id)}
                        variant="ghost"
                        size="sm"
                        className="text-red-600 hover:text-red-700 dark:text-red-400"
                        disabled={actionLoading === postedVideo.id}
                        data-testid={`delete-trigger-${postedVideo.id}`}
                      >
                        Delete
                      </Button>
                    </div>
                  </div>
                </div>
              </Card>
            </div>
          )}

          {/* All Videos List / Grid */}
          <div>
            <h2 className="mb-4 text-lg font-semibold text-gray-900 dark:text-gray-100">
              All Saved Recordings
            </h2>

            <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
              {activeVideos.map((video) => {
                const isPosted = video.lifecycle_status === "posted";
                const isApproved = video.moderation_status === "approved";
                const isPending = video.moderation_status === "pending";

                return (
                  <Card
                    key={video.id}
                    className={`flex flex-col overflow-hidden transition-all ${
                      isPosted ? "border-primary-300 dark:border-primary-700" : ""
                    }`}
                    data-testid={`video-card-${video.id}`}
                  >
                    <div className="relative aspect-video w-full bg-black">
                      <video
                        src={video.signed_url}
                        controls
                        playsInline
                        className="h-full w-full object-contain"
                        data-testid={`card-player-${video.id}`}
                      />
                      {isPosted && (
                        <span className="absolute top-2 left-2 rounded-full bg-primary-600/90 px-2 py-0.5 text-[11px] font-semibold text-white shadow-xs backdrop-blur-xs">
                          Active in Feed
                        </span>
                      )}
                    </div>

                    <div className="flex flex-1 flex-col justify-between p-4">
                      <div>
                        <div className="flex items-center justify-between">
                          {getModerationBadge(video.moderation_status)}
                          <span className="text-xs font-mono text-gray-400">
                            {video.duration_sec}s
                          </span>
                        </div>

                        <div className="mt-3 flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
                          <span>{formatFileSize(video.size_bytes)}</span>
                          <span>{new Date(video.created_at).toLocaleDateString()}</span>
                        </div>
                      </div>

                      {/* Actions */}
                      <div className="mt-4 border-t border-gray-100 pt-3 dark:border-gray-800">
                        {confirmDeleteId === video.id ? (
                          <div className="flex items-center justify-between rounded-md bg-red-50 p-2 text-xs text-red-700 dark:bg-red-950/60 dark:text-red-300">
                            <span>Confirm delete?</span>
                            <div className="space-x-1.5">
                              <button
                                type="button"
                                onClick={() => handleDelete(video.id)}
                                disabled={actionLoading === video.id}
                                className="font-bold underline hover:text-red-900"
                                data-testid={`confirm-delete-btn-${video.id}`}
                              >
                                Delete
                              </button>
                              <button
                                type="button"
                                onClick={() => setConfirmDeleteId(null)}
                                className="text-gray-500 hover:text-gray-700 dark:text-gray-400"
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div className="flex items-center justify-between">
                            {isPosted ? (
                              <Button
                                onClick={() => handleUnpost(video.id)}
                                variant="secondary"
                                size="sm"
                                disabled={actionLoading === video.id}
                                data-testid={`unpost-card-btn-${video.id}`}
                              >
                                Unpost
                              </Button>
                            ) : (
                              <Button
                                onClick={() => handlePost(video.id)}
                                variant="secondary"
                                size="sm"
                                disabled={!isApproved || actionLoading === video.id}
                                title={
                                  !isApproved
                                    ? isPending
                                      ? "Video is currently undergoing AI moderation review"
                                      : "Only approved videos can be published"
                                    : "Publish to employer discovery feed"
                                }
                                data-testid={`post-card-btn-${video.id}`}
                              >
                                Post to Feed
                              </Button>
                            )}

                            <Button
                              onClick={() => setConfirmDeleteId(video.id)}
                              variant="ghost"
                              size="sm"
                              className="text-red-600 hover:text-red-700 dark:text-red-400"
                              disabled={actionLoading === video.id}
                              data-testid={`delete-card-btn-${video.id}`}
                            >
                              Delete
                            </Button>
                          </div>
                        )}
                      </div>
                    </div>
                  </Card>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Recording Best Practices Guide */}
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
        <div className="rounded-lg border border-gray-200 bg-gray-50/50 p-5 dark:border-gray-800 dark:bg-gray-900/50">
          <h3 className="font-medium text-gray-900 dark:text-gray-100">1. Good Lighting & Sound</h3>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            Face a window or lamp, position your camera at eye level, and ensure minimal background noise.
          </p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-gray-50/50 p-5 dark:border-gray-800 dark:bg-gray-900/50">
          <h3 className="font-medium text-gray-900 dark:text-gray-100">2. The 30-Second Formula</h3>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            Who you are (5s), your core expertise & favorite technologies (15s), and what exciting challenges you seek (10s).
          </p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-gray-50/50 p-5 dark:border-gray-800 dark:bg-gray-900/50">
          <h3 className="font-medium text-gray-900 dark:text-gray-100">3. Be Authentic</h3>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            Speak naturally like you're talking to a future colleague. You can retake as many times as you like before submitting!
          </p>
        </div>
      </div>

      <VideoRecorderModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onUploadSuccess={() => {
          fetchVideos(true);
        }}
      />
    </div>
  );
};
