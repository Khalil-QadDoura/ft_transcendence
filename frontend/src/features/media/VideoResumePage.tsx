import React, { useEffect, useState } from "react";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { Spinner } from "../../components/Spinner";
import { useText } from "../../i18n/useText";
import { deleteVideo, listMyVideos, postVideo, unpostVideo } from "./api";
import type { MyVideoItem } from "./types";
import { VideoRecorderModal } from "./VideoRecorderModal";

export const VideoResumePage: React.FC = () => {
  const { t } = useText();
  const [videos, setVideos] = useState<MyVideoItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [actionLoading, setActionLoading] = useState<number | null>(null);

  const fetchVideos = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await listMyVideos();
      setVideos(res.items || []);
    } catch {
      // In development or when user has no videos yet
      setVideos([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchVideos();
  }, []);

  const handlePost = async (id: number) => {
    setActionLoading(id);
    try {
      await postVideo(id);
      await fetchVideos();
    } catch (err: unknown) {
      const error = err as { message?: string };
      setError(error.message || t("media.uploadFailed"));
    } finally {
      setActionLoading(null);
    }
  };

  const handleUnpost = async (id: number) => {
    setActionLoading(id);
    try {
      await unpostVideo(id);
      await fetchVideos();
    } catch (err: unknown) {
      const error = err as { message?: string };
      setError(error.message || t("media.uploadFailed"));
    } finally {
      setActionLoading(null);
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm("Are you sure you want to delete this video résumé?")) {
      return;
    }
    setActionLoading(id);
    try {
      await deleteVideo(id);
      await fetchVideos();
    } catch (err: unknown) {
      const error = err as { message?: string };
      setError(error.message || t("media.uploadFailed"));
    } finally {
      setActionLoading(null);
    }
  };

  const activeVideo = videos.find((v) => v.lifecycle_status !== "deleted");

  const getModerationBadge = (status: string) => {
    switch (status) {
      case "approved":
        return <Badge variant="success">{t("media.approved")}</Badge>;
      case "pending":
        return <Badge variant="warning">{t("media.inReview")}</Badge>;
      case "rejected":
        return <Badge variant="danger">{t("media.needsAttention")}</Badge>;
      default:
        return <Badge variant="default">{status}</Badge>;
    }
  };

  return (
    <div
      className="mx-auto max-w-4xl px-4 py-8 sm:px-6 lg:px-8"
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
        </div>
        <Button
          onClick={() => setIsModalOpen(true)}
          variant="primary"
          data-testid="record-video-cta"
        >
          {activeVideo ? t("media.recordNewVideo") : t("media.recordYourPitch")}
        </Button>
      </div>

      {error && (
        <div className="mb-6 rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-16">
          <Spinner size="lg" />
        </div>
      ) : activeVideo ? (
        <Card className="mb-10 overflow-hidden">
          <div className="p-6">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center space-x-3">
                <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
                  {t("media.currentPitch")}
                </h2>
                {getModerationBadge(activeVideo.moderation_status)}
                {activeVideo.lifecycle_status === "posted" && (
                  <Badge variant="lime">{t("media.publishedInFeed")}</Badge>
                )}
              </div>
              <span className="text-xs text-gray-400 font-mono">
                {t("media.durationSec", { duration: activeVideo.duration_sec })}
              </span>
            </div>

            <div className="relative mb-6 aspect-video w-full overflow-hidden rounded-lg bg-black">
              <video
                src={activeVideo.signed_url}
                controls
                playsInline
                className="h-full w-full object-contain"
                data-testid="active-video-player"
              />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-gray-100 pt-4 dark:border-gray-800">
              <div className="text-xs text-gray-500 dark:text-gray-400">
                {t("media.createdDate", {
                  date: new Date(activeVideo.created_at).toLocaleDateString(),
                })}
              </div>
              <div className="flex items-center space-x-2">
                {activeVideo.lifecycle_status === "posted" ? (
                  <Button
                    onClick={() => handleUnpost(activeVideo.id)}
                    variant="secondary"
                    size="sm"
                    disabled={actionLoading === activeVideo.id}
                  >
                    {t("media.unpostFromFeed")}
                  </Button>
                ) : (
                  <Button
                    onClick={() => handlePost(activeVideo.id)}
                    variant="secondary"
                    size="sm"
                    disabled={
                      activeVideo.moderation_status !== "approved" ||
                      actionLoading === activeVideo.id
                    }
                  >
                    {t("media.postToFeed")}
                  </Button>
                )}
                <Button
                  onClick={() => handleDelete(activeVideo.id)}
                  variant="ghost"
                  size="sm"
                  className="text-red-600 hover:text-red-700 dark:text-red-400"
                  disabled={actionLoading === activeVideo.id}
                >
                  {t("media.delete")}
                </Button>
              </div>
            </div>
          </div>
        </Card>
      ) : (
        <Card className="mb-10 p-10 text-center">
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
          fetchVideos();
        }}
      />
    </div>
  );
};
