import React, { useCallback, useEffect, useRef, useState } from "react";
import { useWsEvent } from "../../api/ws";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { Spinner } from "../../components/Spinner";
import { useText } from "../../i18n/useText";
import { deleteVideo, listMyVideos, postVideo, unpostVideo } from "./api";
import type { MyVideoItem, WsVideoModeratedPayload } from "./types";
import { VideoRecorderModal } from "./VideoRecorderModal";

const MAX_VIDEOS = 3;
const POLLING_INTERVAL_MS = 5000;

export const VideoResumePage: React.FC = () => {
  const { t } = useText();
  const [videos, setVideos] = useState<MyVideoItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [actionLoading, setActionLoading] = useState<number | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const pollingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchVideos = useCallback(
    async (silent = false) => {
      try {
        if (!silent) setLoading(true);
        setError(null);
        const res = await listMyVideos();
        setVideos(res.items || []);
      } catch (err: unknown) {
        const e = err as { message?: string };
        if (!silent) {
          setError(e.message || t("media.failedToLoad"));
          setVideos([]);
        }
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [t],
  );

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
      setError(e.message || t("media.failedToPost"));
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
      setError(e.message || t("media.failedToUnpost"));
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
      setError(e.message || t("media.failedToDelete"));
    } finally {
      setActionLoading(null);
    }
  };

  const getModerationBadge = (status: string) => {
    switch (status) {
      case "approved":
        return (
          <Badge variant="success" data-testid="badge-approved">
            {t("media.approvedBadge")}
          </Badge>
        );
      case "pending":
        return (
          <span
            className="inline-flex items-center space-x-1.5 rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-950/50 dark:text-amber-300"
            data-testid="badge-pending"
          >
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500"></span>
            <span>{t("media.inReviewBadge")}</span>
          </span>
        );
      case "rejected":
        return (
          <Badge variant="danger" data-testid="badge-rejected">
            {t("media.needsAttentionBadge")}
          </Badge>
        );
      case "moderation_error":
        return (
          <Badge variant="warning" data-testid="badge-moderation-error">
            {t("media.reviewIncompleteBadge")}
          </Badge>
        );
      default:
        return <Badge variant="default">{status}</Badge>;
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
      <div className="mb-8 flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-gray-900 dark:text-gray-100">
            {t("media.videoResume")}
          </h1>
          <p className="mt-1 text-base text-gray-600 dark:text-gray-400">
            {t("media.pageSubtitle")}
          </p>
          <div className="mt-2 flex items-center space-x-2 text-xs text-gray-500 dark:text-gray-400">
            <span
              className="font-medium text-gray-700 dark:text-gray-300"
              data-testid="video-quota-counter"
            >
              {t("media.quotaVideos", {
                count: activeVideos.length,
                max: MAX_VIDEOS,
              })}
            </span>
          </div>
        </div>

        <div className="flex flex-col items-end">
          <Button
            onClick={() => setIsModalOpen(true)}
            variant="primary"
            disabled={isAtLimit}
            data-testid="record-video-cta"
          >
            {activeVideos.length === 0
              ? t("media.recordYourPitch")
              : t("media.recordNewVideo")}
          </Button>
          {isAtLimit && (
            <span className="mt-1 text-xs text-amber-600 dark:text-amber-400">
              {t("media.limitReached", { limit: MAX_VIDEOS })}
            </span>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-6 rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-16" data-testid="videos-loading">
          <Spinner size="lg" />
        </div>
      ) : activeVideos.length === 0 ? (
        <Card
          className="mb-10 p-10 text-center"
          data-testid="empty-videos-card"
        >
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-primary-50 text-primary-600 dark:bg-primary-950/50 dark:text-primary-400">
            <svg
              className="h-8 w-8"
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
          </div>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            {t("media.noVideoYet")}
          </h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-gray-500 dark:text-gray-400">
            {t("media.noVideoDesc")}
          </p>
          <div className="mt-6">
            <Button onClick={() => setIsModalOpen(true)} variant="primary">
              {t("media.recordVideoNow")}
            </Button>
          </div>
        </Card>
      ) : (
        <div className="space-y-8 mb-10">
          {/* Active Featured Pitch Card */}
          {postedVideo && (
            <div data-testid="active-posted-section">
              <div className="mb-3 flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                    {t("media.activePitchTitle")}
                  </h2>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {t("media.activePitchDesc")}
                  </p>
                </div>
                <Badge variant="primary">{t("media.publishedInFeed")}</Badge>
              </div>

              <Card className="overflow-hidden border-primary-200 dark:border-primary-900 shadow-sm">
                <div className="p-6">
                  <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center space-x-3">
                      {getModerationBadge(postedVideo.moderation_status)}
                      <span className="text-xs text-gray-400 font-mono">
                        {t("media.durationSec", {
                          duration: postedVideo.duration_sec,
                        })}
                        {postedVideo.size_bytes
                          ? ` • ${formatFileSize(postedVideo.size_bytes)}`
                          : ""}
                      </span>
                    </div>
                  </div>

                  <div className="relative mb-6 aspect-video w-full overflow-hidden rounded-lg bg-black">
                    <video
                      src={postedVideo.signed_url}
                      controls
                      playsInline
                      className="h-full w-full object-contain"
                      data-testid="active-video-player"
                    />
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-3 border-t border-gray-100 pt-4 dark:border-gray-800">
                    <div className="text-xs text-gray-500 dark:text-gray-400">
                      {t("media.createdDate", {
                        date: new Date(
                          postedVideo.created_at,
                        ).toLocaleDateString(),
                      })}
                    </div>
                    <div className="flex items-center space-x-2">
                      <Button
                        onClick={() => handleUnpost(postedVideo.id)}
                        variant="secondary"
                        size="sm"
                        disabled={actionLoading === postedVideo.id}
                        data-testid={`unpost-btn-${postedVideo.id}`}
                      >
                        {t("media.unpostFromFeed")}
                      </Button>
                      <Button
                        onClick={() => handleDelete(postedVideo.id)}
                        variant="ghost"
                        size="sm"
                        className="text-red-600 hover:text-red-700 dark:text-red-400"
                        disabled={actionLoading === postedVideo.id}
                        data-testid={`delete-btn-${postedVideo.id}`}
                      >
                        {t("media.delete")}
                      </Button>
                    </div>
                  </div>
                </div>
              </Card>
            </div>
          )}

          {/* All Videos List / Grid */}
          <div>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                {t("media.allVideosTitle")}
              </h2>
              <span className="text-xs text-gray-500 dark:text-gray-400">
                {t("media.allVideosQuota", {
                  count: activeVideos.length,
                  max: MAX_VIDEOS,
                })}
              </span>
            </div>

            <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
              {activeVideos.map((video) => {
                const isPosted = video.lifecycle_status === "posted";
                const isApproved = video.moderation_status === "approved";
                const isPending = video.moderation_status === "pending";

                return (
                  <Card
                    key={video.id}
                    className="flex flex-col justify-between overflow-hidden shadow-sm"
                    data-testid={`video-card-${video.id}`}
                  >
                    <div className="p-5">
                      <div className="mb-3 flex items-center justify-between">
                        {getModerationBadge(video.moderation_status)}
                        {isPosted && (
                          <Badge variant="primary" size="sm">
                            {t("media.publishedInFeed")}
                          </Badge>
                        )}
                      </div>

                      <div className="relative mb-4 aspect-video w-full overflow-hidden rounded bg-black">
                        <video
                          src={video.signed_url}
                          controls
                          playsInline
                          className="h-full w-full object-contain"
                        />
                      </div>

                      <div className="space-y-1 text-xs text-gray-500 dark:text-gray-400">
                        <div className="flex justify-between font-mono">
                          <span>
                            {t("media.durationSec", {
                              duration: video.duration_sec,
                            })}
                          </span>
                          <span>{formatFileSize(video.size_bytes)}</span>
                        </div>
                        <div>
                          {t("media.createdDate", {
                            date: new Date(
                              video.created_at,
                            ).toLocaleDateString(),
                          })}
                        </div>
                      </div>
                    </div>

                    <div className="border-t border-gray-100 bg-gray-50/50 p-4 dark:border-gray-800 dark:bg-gray-900/50">
                      <div className="space-y-2">
                        {confirmDeleteId === video.id ? (
                          <div
                            className="flex items-center justify-between rounded bg-red-50 p-2 text-xs text-red-700 dark:bg-red-950/50 dark:text-red-300"
                            data-testid={`delete-confirmation-${video.id}`}
                          >
                            <span>{t("media.confirmDeletePrompt")}</span>
                            <div className="space-x-1.5">
                              <button
                                type="button"
                                onClick={() => handleDelete(video.id)}
                                disabled={actionLoading === video.id}
                                className="font-bold underline hover:text-red-900"
                                data-testid={`confirm-delete-btn-${video.id}`}
                              >
                                {t("media.delete")}
                              </button>
                              <button
                                type="button"
                                onClick={() => setConfirmDeleteId(null)}
                                className="text-gray-500 hover:text-gray-700 dark:text-gray-400"
                              >
                                {t("media.cancel")}
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
                                {t("media.unpost")}
                              </Button>
                            ) : (
                              <Button
                                onClick={() => handlePost(video.id)}
                                variant="secondary"
                                size="sm"
                                disabled={
                                  !isApproved || actionLoading === video.id
                                }
                                title={
                                  !isApproved
                                    ? isPending
                                      ? t("media.pendingTitle")
                                      : t("media.approvedOnlyTitle")
                                    : t("media.publishTitle")
                                }
                                data-testid={`post-card-btn-${video.id}`}
                              >
                                {t("media.postToFeed")}
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
                              {t("media.delete")}
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
          <h3 className="font-medium text-gray-900 dark:text-gray-100">
            {t("media.tip1Title")}
          </h3>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            {t("media.tip1Desc")}
          </p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-gray-50/50 p-5 dark:border-gray-800 dark:bg-gray-900/50">
          <h3 className="font-medium text-gray-900 dark:text-gray-100">
            {t("media.tip2Title")}
          </h3>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            {t("media.tip2Desc")}
          </p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-gray-50/50 p-5 dark:border-gray-800 dark:bg-gray-900/50">
          <h3 className="font-medium text-gray-900 dark:text-gray-100">
            {t("media.tip3Title")}
          </h3>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            {t("media.tip3Desc")}
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
