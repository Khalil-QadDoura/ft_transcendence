import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { Spinner } from "../../components/Spinner";
import { useText } from "../../i18n/useText";
import { ApplicationCard } from "./ApplicationCard";
import { listMyApplications, withdrawApplication } from "./api";
import type { ApplicationItem, ApplicationStatus } from "./types";

type StatusFilter = "all" | ApplicationStatus;

export const MyApplicationsPage: React.FC = () => {
  const { t } = useText();
  const [applications, setApplications] = useState<ApplicationItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadingMore, setLoadingMore] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const fetchApplications = useCallback(
    async (filter: StatusFilter, cursor?: number | null) => {
      try {
        if (!cursor) {
          setLoading(true);
        } else {
          setLoadingMore(true);
        }
        setError(null);

        const apiStatus = filter === "all" ? undefined : filter;
        const res = await listMyApplications({
          status: apiStatus,
          cursor: cursor ?? undefined,
          limit: 20,
        });

        if (cursor) {
          setApplications((prev) => [...prev, ...res.items]);
        } else {
          setApplications(res.items);
        }
        setNextCursor(res.next_cursor);
      } catch (err: unknown) {
        const e = err as { message?: string };
        setError(e.message || t("applications.failedToLoad"));
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [t],
  );

  useEffect(() => {
    fetchApplications(statusFilter, null);
  }, [statusFilter, fetchApplications]);

  const handleWithdraw = async (id: number) => {
    await withdrawApplication(id);
    setApplications((prev) =>
      prev.map((app) =>
        app.id === id ? { ...app, status: "withdrawn" as const } : app,
      ),
    );
  };

  const tabs: Array<{ id: StatusFilter; label: string }> = [
    { id: "all", label: t("applications.tabAll") },
    { id: "submitted", label: t("applications.statusSubmitted") },
    { id: "viewed", label: t("applications.statusViewed") },
    { id: "shortlisted", label: t("applications.statusShortlisted") },
    { id: "contacted", label: t("applications.statusContacted") },
    { id: "hired", label: t("applications.statusHired") },
    { id: "rejected", label: t("applications.statusRejected") },
    { id: "withdrawn", label: t("applications.statusWithdrawn") },
  ];

  return (
    <div
      className="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8 text-ink"
      data-testid="my-applications-page"
    >
      {/* Header */}
      <div className="mb-8 flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-ink">
            {t("applications.title")}
          </h1>
          <p className="mt-1 text-base text-ink-muted">
            {t("applications.subtitle")}
          </p>
        </div>
        <Link to="/jobs">
          <Button variant="primary">{t("applications.browseOpenJobs")}</Button>
        </Link>
      </div>

      {/* Status filter tabs */}
      <div className="mb-6 flex space-x-2 overflow-x-auto border-b border-border pb-2">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setStatusFilter(tab.id)}
            className={`rounded-lg px-3.5 py-1.5 text-xs font-semibold whitespace-nowrap transition-colors ${
              statusFilter === tab.id
                ? "bg-ink text-paper shadow-xs"
                : "text-ink-muted hover:bg-surface-muted"
            }`}
            data-testid={`filter-tab-${tab.id}`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {error && (
        <div
          role="alert"
          className="mb-6 rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300"
        >
          {error}
        </div>
      )}

      {loading ? (
        <div
          className="flex justify-center py-20"
          data-testid="applications-loading"
        >
          <Spinner size="lg" />
        </div>
      ) : applications.length === 0 ? (
        <Card
          className="p-10 text-center"
          data-testid="empty-applications-card"
        >
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-gray-100 text-gray-400 dark:bg-gray-800 dark:text-gray-500">
            <svg
              className="h-7 w-7"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
          </div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            {t("applications.noApplicationsFound")}
          </h2>
          <p className="mx-auto mt-1 max-w-sm text-xs text-gray-500 dark:text-gray-400">
            {statusFilter === "all"
              ? t("applications.noApplicationsEmpty")
              : t("applications.noApplicationsFilter", {
                  status: statusFilter,
                })}
          </p>
          <div className="mt-5">
            <Link to="/jobs">
              <Button variant="primary" size="sm">
                {t("applications.exploreOpenJobs")}
              </Button>
            </Link>
          </div>
        </Card>
      ) : (
        <div className="space-y-4">
          {applications.map((app) => (
            <ApplicationCard
              key={app.id}
              application={app}
              onWithdraw={handleWithdraw}
            />
          ))}

          {/* Load More Button */}
          {nextCursor !== null && (
            <div className="pt-6 text-center">
              <Button
                variant="secondary"
                size="md"
                onClick={() => fetchApplications(statusFilter, nextCursor)}
                disabled={loadingMore}
                data-testid="load-more-btn"
              >
                {loadingMore
                  ? t("applications.loadingMore")
                  : t("applications.loadMoreApplications")}
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
