import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useWsEvent } from "../../api/ws";
import { Badge, type BadgeVariant } from "../../components/Badge";
import { Button, type ButtonVariant } from "../../components/Button";
import { Card } from "../../components/Card";
import { Spinner } from "../../components/Spinner";
import { useText } from "../../i18n/useText";
import {
  getCandidateFeed,
  listJobApplications,
  updateApplicationStatus,
} from "./api";
import {
  EMPLOYER_TRANSITIONS,
  type ApplicationItem,
  type ApplicationStatus,
  type CandidateFeedItem,
} from "./types";

type StatusFilter = "all" | ApplicationStatus;
type ActiveTab = "applications" | "feed";

export const EmployerApplicationsPage: React.FC = () => {
  const { t } = useText();
  const { id } = useParams<{ id: string }>();
  const jobId = id ? Number(id) : null;

  const [activeTab, setActiveTab] = useState<ActiveTab>("applications");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  // Applications state
  const [applications, setApplications] = useState<ApplicationItem[]>([]);
  const [selectedApp, setSelectedApp] = useState<ApplicationItem | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadingMore, setLoadingMore] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<number | null>(null);

  // Status update state
  const [updatingStatus, setUpdatingStatus] = useState<boolean>(false);
  const [statusError, setStatusError] = useState<string | null>(null);
  const autoViewedRef = useRef<Set<number>>(new Set());

  // Candidate Feed state
  const [feedItems, setFeedItems] = useState<CandidateFeedItem[]>([]);
  const [feedLoading, setFeedLoading] = useState<boolean>(false);
  const [feedLoadingMore, setFeedLoadingMore] = useState<boolean>(false);
  const [feedError, setFeedError] = useState<string | null>(null);
  const [feedNextCursor, setFeedNextCursor] = useState<number | null>(null);

  const fetchApplications = useCallback(
    async (filter: StatusFilter, cursor?: number | null) => {
      if (!jobId) return;
      try {
        if (!cursor) {
          setLoading(true);
        } else {
          setLoadingMore(true);
        }
        setError(null);

        const apiStatus = filter === "all" ? undefined : filter;
        const res = await listJobApplications(jobId, {
          status: apiStatus,
          cursor: cursor ?? undefined,
          limit: 20,
        });

        if (cursor) {
          setApplications((prev) => [...prev, ...res.items]);
        } else {
          setApplications(res.items);
          if (res.items.length > 0) {
            setSelectedApp((prev) => {
              if (prev) {
                const stillExists = res.items.find(
                  (item) => item.id === prev.id,
                );
                return stillExists || res.items[0];
              }
              return res.items[0];
            });
          } else {
            setSelectedApp(null);
          }
        }
        setNextCursor(res.next_cursor);
      } catch (err: unknown) {
        const e = err as { message?: string };
        setError(e.message || t("employerApplications.failedToLoad"));
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [jobId, t],
  );

  const fetchFeed = useCallback(
    async (cursor?: number | null) => {
      if (!jobId) return;
      try {
        if (!cursor) {
          setFeedLoading(true);
        } else {
          setFeedLoadingMore(true);
        }
        setFeedError(null);

        const res = await getCandidateFeed(jobId, {
          cursor: cursor ?? undefined,
          limit: 20,
        });

        if (cursor) {
          setFeedItems((prev) => [...prev, ...res.items]);
        } else {
          setFeedItems(res.items);
        }
        setFeedNextCursor(res.next_cursor);
      } catch (err: unknown) {
        const e = err as { message?: string };
        setFeedError(e.message || t("employerApplications.failedToLoadFeed"));
      } finally {
        setFeedLoading(false);
        setFeedLoadingMore(false);
      }
    },
    [jobId, t],
  );

  useEffect(() => {
    if (activeTab === "applications") {
      fetchApplications(statusFilter, null);
    } else {
      fetchFeed(null);
    }
  }, [activeTab, statusFilter, fetchApplications, fetchFeed]);

  // Real-time WebSocket listener for newly created applications
  useWsEvent<ApplicationItem>("application_created", (payload) => {
    if (!payload || typeof payload.id !== "number") return;
    if (payload.job_id && jobId && payload.job_id !== jobId) return;

    setApplications((prev) => {
      if (prev.some((app) => app.id === payload.id)) return prev;
      if (statusFilter !== "all" && payload.status !== statusFilter)
        return prev;
      return [payload, ...prev];
    });
  });

  // Real-time WebSocket listener for application status updates
  useWsEvent<ApplicationItem>("application_updated", (payload) => {
    if (!payload || typeof payload.id !== "number") return;
    if (payload.job_id && jobId && payload.job_id !== jobId) return;

    setApplications((prev) =>
      prev.map((app) => (app.id === payload.id ? { ...app, ...payload } : app)),
    );
    setSelectedApp((prev) =>
      prev?.id === payload.id ? { ...prev, ...payload } : prev,
    );
  });

  // Auto-mark "submitted" applications as "viewed" upon selecting/viewing them
  useEffect(() => {
    if (
      selectedApp &&
      selectedApp.status === "submitted" &&
      !autoViewedRef.current.has(selectedApp.id)
    ) {
      autoViewedRef.current.add(selectedApp.id);
      updateApplicationStatus(selectedApp.id, "viewed")
        .then((updated) => {
          setApplications((prev) =>
            prev.map((app) =>
              app.id === updated.id ? { ...app, ...updated } : app,
            ),
          );
          setSelectedApp((prev) =>
            prev?.id === updated.id ? { ...prev, ...updated } : prev,
          );
        })
        .catch(() => {
          // Silent catch for auto-mark background call
        });
    }
  }, [selectedApp]);

  const handleSelectApplication = (app: ApplicationItem) => {
    setStatusError(null);
    setSelectedApp(app);
  };

  const handleStatusTransition = async (targetStatus: ApplicationStatus) => {
    if (!selectedApp) return;
    try {
      setUpdatingStatus(true);
      setStatusError(null);
      const updated = await updateApplicationStatus(
        selectedApp.id,
        targetStatus,
      );
      setApplications((prev) =>
        prev.map((app) =>
          app.id === updated.id ? { ...app, ...updated } : app,
        ),
      );
      setSelectedApp(updated);
    } catch (err: unknown) {
      const e = err as { message?: string };
      setStatusError(
        e.message || t("employerApplications.failedToUpdateStatus"),
      );
    } finally {
      setUpdatingStatus(false);
    }
  };

  const getStatusBadge = (status: ApplicationStatus) => {
    const variants: Record<ApplicationStatus, BadgeVariant> = {
      submitted: "default",
      viewed: "outline",
      shortlisted: "warning",
      contacted: "success",
      hired: "success",
      rejected: "danger",
      withdrawn: "outline",
    };
    const labels: Record<ApplicationStatus, string> = {
      submitted: t("employerApplications.statusSubmitted"),
      viewed: t("employerApplications.statusViewed"),
      shortlisted: t("employerApplications.statusShortlisted"),
      contacted: t("employerApplications.statusContacted"),
      hired: t("employerApplications.statusHired"),
      rejected: t("employerApplications.statusRejected"),
      withdrawn: t("employerApplications.statusWithdrawn"),
    };
    return (
      <Badge
        variant={variants[status] || "default"}
        data-testid={`status-${status}`}
      >
        {labels[status] || status}
      </Badge>
    );
  };

  const getTransitionButtonConfig = (
    nextStatus: ApplicationStatus,
  ): { label: string; variant: ButtonVariant } => {
    switch (nextStatus) {
      case "viewed":
        return {
          label: t("employerApplications.btnMarkViewed"),
          variant: "outline",
        };
      case "shortlisted":
        return {
          label: t("employerApplications.btnShortlist"),
          variant: "primary",
        };
      case "contacted":
        return {
          label: t("employerApplications.btnContact"),
          variant: "primary",
        };
      case "hired":
        return {
          label: t("employerApplications.btnHire"),
          variant: "primary",
        };
      case "rejected":
        return {
          label: t("employerApplications.btnReject"),
          variant: "danger",
        };
      default:
        return {
          label: t("employerApplications.transitionTo", { status: nextStatus }),
          variant: "secondary",
        };
    }
  };

  const statusTabs: Array<{ id: StatusFilter; label: string }> = [
    { id: "all", label: t("employerApplications.tabAll") },
    { id: "submitted", label: t("employerApplications.statusSubmitted") },
    { id: "viewed", label: t("employerApplications.statusViewed") },
    { id: "shortlisted", label: t("employerApplications.statusShortlisted") },
    { id: "contacted", label: t("employerApplications.statusContacted") },
    { id: "hired", label: t("employerApplications.statusHired") },
    { id: "rejected", label: t("employerApplications.statusRejected") },
    { id: "withdrawn", label: t("employerApplications.statusWithdrawn") },
  ];

  const candidateDisplayName = (app: ApplicationItem) => {
    return (
      app.applicant_display_name ||
      (app.applicant_first_name
        ? `${app.applicant_first_name} ${app.applicant_last_name || ""}`.trim()
        : null) ||
      t("employerApplications.deletedUser")
    );
  };

  if (!jobId) {
    return (
      <div
        className="mx-auto max-w-7xl px-4 py-8 text-ink"
        data-testid="employer-applications-page"
      >
        <p className="text-danger">{t("employerApplications.noJobId")}</p>
      </div>
    );
  }

  return (
    <div
      className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 text-ink"
      data-testid="employer-applications-page"
    >
      {/* Header */}
      <div className="mb-6 flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-tight text-ink">
          {t("employerApplications.title")}
        </h1>
        <p className="text-base text-ink-muted">
          {t("employerApplications.subtitle")}
        </p>
      </div>

      {/* Main Tabs: Applications vs Candidate Pitch Feed */}
      <div className="mb-6 flex border-b border-border">
        <button
          type="button"
          onClick={() => setActiveTab("applications")}
          data-testid="tab-applications"
          className={`cursor-pointer border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === "applications"
              ? "border-accent text-accent"
              : "border-transparent text-ink-muted hover:text-ink"
          }`}
        >
          {t("employerApplications.tabApplications")}
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("feed")}
          data-testid="tab-candidate-feed"
          className={`cursor-pointer border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === "feed"
              ? "border-accent text-accent"
              : "border-transparent text-ink-muted hover:text-ink"
          }`}
        >
          {t("employerApplications.tabCandidateFeed")}
        </button>
      </div>

      {activeTab === "applications" ? (
        <>
          {/* Status Filter Tabs */}
          <div className="mb-6 flex flex-wrap gap-2 overflow-x-auto pb-2">
            {statusTabs.map((tab) => (
              <Button
                key={tab.id}
                variant={statusFilter === tab.id ? "primary" : "outline"}
                size="sm"
                onClick={() => setStatusFilter(tab.id)}
                data-testid={`status-tab-${tab.id}`}
              >
                {tab.label}
              </Button>
            ))}
          </div>

          {error && (
            <div
              className="mb-6 rounded-md bg-danger-subtle p-4 text-sm text-danger"
              data-testid="applications-error"
            >
              {error}
            </div>
          )}

          {loading ? (
            <div
              className="flex items-center justify-center py-16"
              data-testid="applications-loading"
            >
              <Spinner size="lg" />
            </div>
          ) : applications.length === 0 ? (
            <Card
              className="flex flex-col items-center justify-center p-12 text-center"
              data-testid="empty-applications-card"
            >
              <h2 className="text-xl font-bold text-ink">
                {t("employerApplications.noApplicationsFound")}
              </h2>
              <p className="mt-2 text-sm text-ink-muted">
                {statusFilter === "all"
                  ? t("employerApplications.noApplicationsEmpty")
                  : t("employerApplications.noApplicationsFilter", {
                      status: statusFilter,
                    })}
              </p>
            </Card>
          ) : (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
              {/* Applications List (Left column) */}
              <div
                className="space-y-3 lg:col-span-5"
                data-testid="applications-list"
              >
                {applications.map((app) => {
                  const isSelected = selectedApp?.id === app.id;
                  return (
                    <Card
                      key={app.id}
                      onClick={() => handleSelectApplication(app)}
                      data-testid={`application-item-${app.id}`}
                      className={`cursor-pointer p-4 transition-all ${
                        isSelected
                          ? "ring-2 ring-accent border-transparent"
                          : "hover:border-border-hover"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <h3
                            className="font-semibold text-ink"
                            data-testid={`candidate-name-${app.id}`}
                          >
                            {candidateDisplayName(app)}
                          </h3>
                          {app.applicant_position && (
                            <p className="text-xs text-ink-muted">
                              {app.applicant_position}
                            </p>
                          )}
                        </div>
                        {getStatusBadge(app.status)}
                      </div>
                      <div className="mt-2 text-xs text-ink-muted">
                        {t("employerApplications.appliedAt", {
                          date: new Date(app.applied_at).toLocaleDateString(),
                        })}
                      </div>
                    </Card>
                  );
                })}

                {nextCursor && (
                  <div className="pt-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        fetchApplications(statusFilter, nextCursor)
                      }
                      disabled={loadingMore}
                      data-testid="load-more-btn"
                      className="w-full"
                    >
                      {loadingMore
                        ? t("employerApplications.loadingMore")
                        : t("employerApplications.loadMore")}
                    </Button>
                  </div>
                )}
              </div>

              {/* Selected Candidate Detail Pane (Right column) */}
              <div className="lg:col-span-7">
                {selectedApp ? (
                  <Card className="p-6" data-testid="candidate-detail-pane">
                    {/* Header info */}
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border pb-4">
                      <div>
                        <div className="flex items-center gap-3">
                          <h2
                            className="text-2xl font-bold text-ink"
                            data-testid="candidate-detail-name"
                          >
                            {candidateDisplayName(selectedApp)}
                          </h2>
                          {getStatusBadge(selectedApp.status)}
                        </div>
                        {selectedApp.applicant_position && (
                          <p
                            className="mt-1 text-sm text-ink-muted"
                            data-testid="candidate-detail-position"
                          >
                            {selectedApp.applicant_position}
                          </p>
                        )}
                        <div className="mt-2">
                          <Link
                            to={`/users/${selectedApp.applicant_id}`}
                            className="text-sm font-medium text-accent hover:underline"
                            data-testid="candidate-profile-link"
                          >
                            {t("employerApplications.viewProfile")}
                          </Link>
                        </div>
                      </div>

                      {/* Conversation Button if Contacted */}
                      {selectedApp.conversation_id && (
                        <Link
                          to={`/chat/${selectedApp.conversation_id}`}
                          data-testid="open-conversation-btn"
                          className="inline-flex items-center justify-center rounded-md px-4 py-2 text-sm font-medium bg-accent text-white hover:opacity-90 transition-opacity"
                        >
                          {t("employerApplications.openConversation")}
                        </Link>
                      )}
                    </div>

                    {/* Status Error Alert */}
                    {statusError && (
                      <div
                        className="mt-4 rounded-md bg-danger-subtle p-3 text-sm text-danger"
                        data-testid="status-error-alert"
                      >
                        {statusError}
                      </div>
                    )}

                    {/* Status Transitions Controls */}
                    <div className="mt-4 border-b border-border pb-4">
                      <span className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                        {t("employerApplications.statusLabel")}
                      </span>
                      <div
                        className="mt-2 flex flex-wrap gap-2"
                        data-testid="status-actions"
                      >
                        {EMPLOYER_TRANSITIONS[selectedApp.status]?.map(
                          (targetStatus) => {
                            const config =
                              getTransitionButtonConfig(targetStatus);
                            return (
                              <Button
                                key={targetStatus}
                                variant={config.variant}
                                size="sm"
                                disabled={updatingStatus}
                                onClick={() =>
                                  handleStatusTransition(targetStatus)
                                }
                                data-testid={`transition-${targetStatus}`}
                              >
                                {updatingStatus
                                  ? t("employerApplications.updatingStatus")
                                  : config.label}
                              </Button>
                            );
                          },
                        )}
                      </div>
                    </div>

                    {/* Intro Video Player */}
                    <div className="mt-6">
                      <h3 className="mb-2 text-sm font-semibold text-ink">
                        {t("employerApplications.introVideoTitle")}
                      </h3>
                      {selectedApp.intro_video_url ? (
                        <div className="aspect-video w-full overflow-hidden rounded-lg bg-black">
                          <video
                            src={selectedApp.intro_video_url}
                            controls
                            playsInline
                            className="h-full w-full object-contain"
                            data-testid="candidate-video-player"
                          />
                        </div>
                      ) : (
                        <div
                          className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-ink-muted"
                          data-testid="no-intro-video"
                        >
                          {t("employerApplications.noIntroVideo")}
                        </div>
                      )}
                    </div>

                    {/* Cover Note */}
                    <div className="mt-6" data-testid="candidate-cover-note">
                      <h3 className="mb-2 text-sm font-semibold text-ink">
                        {t("employerApplications.coverNoteTitle")}
                      </h3>
                      <p
                        className="whitespace-pre-wrap rounded-lg bg-paper-subtle p-4 text-sm text-ink"
                        data-testid="cover-note-text"
                      >
                        {selectedApp.cover_note ||
                          t("employerApplications.noCoverNote")}
                      </p>
                    </div>
                  </Card>
                ) : (
                  <Card className="flex items-center justify-center p-12 text-center text-sm text-ink-muted">
                    {t("employerApplications.selectToReview")}
                  </Card>
                )}
              </div>
            </div>
          )}
        </>
      ) : (
        /* Candidate Pitch Feed View (BE-25 / FE-28) */
        <div>
          {feedError && (
            <div
              className="mb-6 rounded-md bg-danger-subtle p-4 text-sm text-danger"
              data-testid="feed-error"
            >
              {feedError}
            </div>
          )}

          {feedLoading ? (
            <div
              className="flex items-center justify-center py-16"
              data-testid="feed-loading"
            >
              <Spinner size="lg" />
            </div>
          ) : feedItems.length === 0 ? (
            <Card
              className="flex flex-col items-center justify-center p-12 text-center"
              data-testid="empty-feed-card"
            >
              <h2 className="text-xl font-bold text-ink">
                {t("employerApplications.noApplicationsFound")}
              </h2>
              <p className="mt-2 text-sm text-ink-muted">
                {t("employerApplications.noFeedVideos")}
              </p>
            </Card>
          ) : (
            <div
              className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3"
              data-testid="feed-grid"
            >
              {feedItems.map((item) => (
                <Card
                  key={item.id}
                  className="flex flex-col overflow-hidden p-4"
                  data-testid={`feed-item-${item.id}`}
                >
                  <div className="aspect-video w-full overflow-hidden rounded-md bg-black">
                    <video
                      src={item.signed_url}
                      controls
                      playsInline
                      className="h-full w-full object-contain"
                      data-testid="feed-video-player"
                    />
                  </div>
                  <div className="mt-3 flex flex-col gap-1">
                    <h3
                      className="font-semibold text-ink"
                      data-testid="feed-author-name"
                    >
                      {item.author_name ||
                        t("employerApplications.deletedUser")}
                    </h3>
                    {item.author_position && (
                      <p
                        className="text-xs text-ink-muted"
                        data-testid="feed-author-position"
                      >
                        {item.author_position}
                      </p>
                    )}
                    <div className="mt-2 flex items-center justify-between text-xs text-ink-muted">
                      <span>
                        {t("employerApplications.feedDuration", {
                          minutes: Math.floor(item.duration_sec / 60),
                          seconds: String(item.duration_sec % 60).padStart(
                            2,
                            "0",
                          ),
                        })}
                      </span>
                      <Link
                        to={`/users/${item.user_id}`}
                        className="font-medium text-accent hover:underline"
                        data-testid="feed-profile-link"
                      >
                        {t("employerApplications.viewProfile")}
                      </Link>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          )}

          {feedNextCursor && (
            <div className="mt-8 flex justify-center">
              <Button
                variant="outline"
                onClick={() => fetchFeed(feedNextCursor)}
                disabled={feedLoadingMore}
                data-testid="feed-load-more-btn"
              >
                {feedLoadingMore
                  ? t("employerApplications.loadingMore")
                  : t("employerApplications.loadMore")}
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
