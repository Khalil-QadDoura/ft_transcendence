import { useCallback, useContext, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError, getAccessToken } from "../../api/client";
import { SessionContext } from "../../app/session";
import { Avatar } from "../../components/Avatar";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { Modal } from "../../components/Modal";
import { Spinner } from "../../components/Spinner";
import { Textarea } from "../../components/Textarea";
import { useText } from "../../i18n/useText";
import { applyToJob, fetchJobDetail, formatSalary, recordJobView } from "./api";
import type { Job } from "./types";

export interface JobDetailPageProps {
  currentUserId?: number;
}

export function JobDetailPage({ currentUserId }: JobDetailPageProps) {
  const { t } = useText();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const session = useContext(SessionContext);

  const [job, setJob] = useState<Job | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Apply dialog state
  const [isApplyOpen, setIsApplyOpen] = useState(false);
  const [coverNote, setCoverNote] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [applySuccess, setApplySuccess] = useState(false);
  const [applyError, setApplyError] = useState<{
    message: string;
    nextStep?: string;
  } | null>(null);

  useEffect(() => {
    if (!id) return;

    let isMounted = true;
    setIsLoading(true);
    setError(null);

    // 1. Fetch Job details
    fetchJobDetail(id)
      .then((data) => {
        if (isMounted) {
          setJob(data);
          // 2. Record view (counted once per 24h)
          recordJobView(id);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(
            err instanceof Error ? err.message : t("jobs.jobNotFoundDesc"),
          );
        }
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [id, t]);

  const isOwnJob = Boolean(
    job && currentUserId && job.owner_id === currentUserId,
  );

  const handleOpenApply = () => {
    const isAuthenticated =
      session === "authenticated" || Boolean(getAccessToken());
    if (!isAuthenticated) {
      navigate(
        `/login?next=${encodeURIComponent(location.pathname + location.search)}`,
      );
      return;
    }
    setIsApplyOpen(true);
    setApplyError(null);
  };

  const handleCloseApply = useCallback(() => {
    setIsApplyOpen(false);
    setApplyError(null);
  }, []);

  const handleSubmitApply = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!id) return;

    setIsSubmitting(true);
    setApplyError(null);

    try {
      await applyToJob(id, coverNote);
      setApplySuccess(true);
      setIsApplyOpen(false);
      if (job) {
        setJob({ ...job, applications_count: job.applications_count + 1 });
      }
    } catch (err) {
      if (err instanceof ApiError) {
        const detailCode =
          typeof err.detail === "object" &&
          err.detail !== null &&
          "code" in err.detail
            ? String((err.detail as { code?: unknown }).code)
            : undefined;

        // Handle apply guards: profile_incomplete or no_video
        if (
          err.nextStep === "profile" ||
          detailCode === "profile_incomplete" ||
          err.code === "profile_incomplete"
        ) {
          setApplyError({
            message: t("jobs.profileIncomplete"),
            nextStep: "/profile",
          });
        } else if (
          err.nextStep === "video" ||
          err.nextStep === "videos" ||
          detailCode === "no_video" ||
          err.code === "no_video"
        ) {
          setApplyError({
            message: t("jobs.videoRequired"),
            nextStep: "/videos",
          });
        } else if (err.status === 409) {
          setApplyError({
            message: t("jobs.alreadyAppliedError"),
          });
          setApplySuccess(true);
        } else if (err.status === 403) {
          setApplyError({
            message: t("jobs.cannotApplyOwnJob"),
          });
        } else {
          setApplyError({
            message: err.message || t("jobs.failedToSubmit"),
          });
        }
      } else {
        setApplyError({
          message:
            err instanceof Error ? err.message : t("jobs.unexpectedApplyError"),
        });
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="py-24 flex flex-col items-center justify-center gap-3">
        <h1 className="sr-only">{t("jobs.loadingJobDetails")}</h1>
        <Spinner size="lg" aria-label={t("jobs.loadingJobDetails")} />
        <p className="text-sm text-ink-muted">{t("jobs.loadingJobInfo")}</p>
      </div>
    );
  }

  if (error || !job) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-16 text-center space-y-4">
        <h1 className="text-2xl font-bold text-ink">
          {t("jobs.jobNotFoundTitle")}
        </h1>
        <p className="text-sm text-ink-muted leading-relaxed">
          {error || t("jobs.jobNotFoundDesc")}
        </p>
        <Link
          to="/jobs"
          className="inline-flex items-center justify-center font-medium transition-colors select-none rounded-md text-sm px-4 py-2 gap-2 bg-paper-subtle text-ink hover:bg-border active:bg-border/90 border border-border"
        >
          {t("jobs.backToJobs")}
        </Link>
      </div>
    );
  }

  const companyName = job.company_name || t("jobs.confidentialCompany");
  const salaryText = formatSalary(
    job.salary_amount,
    job.salary_currency,
    job.salary_type,
  );

  const urgencyVariants = {
    hot: { variant: "danger" as const, label: t("jobs.urgencyHot") },
    urgent: { variant: "warning" as const, label: t("jobs.urgencyUrgent") },
    normal: { variant: "outline" as const, label: t("jobs.urgencyNormal") },
  }[job.urgency] || { variant: "outline" as const, label: job.urgency };

  const scheduleLabels: Record<string, string> = {
    full_time: t("jobs.scheduleFullTime"),
    part_time: t("jobs.schedulePartTime"),
    internship: t("jobs.scheduleInternship"),
  };

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-6 text-start">
      {/* Back button / breadcrumb */}
      <div>
        <Link
          to="/jobs"
          className="text-xs sm:text-sm font-medium text-ink-muted hover:text-ink flex items-center gap-1.5 focus:outline-none focus:underline"
        >
          <span aria-hidden="true">←</span> {t("jobs.backToAllJobs")}
        </Link>
      </div>

      {/* Success Notification */}
      {applySuccess && (
        <div
          role="status"
          className="p-4 rounded-lg bg-success-subtle border border-success/30 text-success text-sm flex items-center justify-between gap-3"
        >
          <span>
            ✓ <strong>{t("jobs.applicationSubmitted")}</strong>{" "}
            {t("jobs.employerWillReview")}
          </span>
        </div>
      )}

      {/* Main Job Header Card */}
      <Card className="p-6 sm:p-8 space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
          <div className="flex items-start gap-4">
            <Avatar
              alt={companyName}
              fallbackText={companyName}
              size="lg"
              className="mt-1 shrink-0 bg-surface-muted border border-border"
            />
            <div className="space-y-1">
              <h1 className="text-xl sm:text-2xl font-bold text-ink leading-tight">
                {job.title}
              </h1>
              <p className="text-sm font-medium text-ink-muted">
                {companyName} {job.location && `• ${job.location}`}
              </p>
              <div className="flex flex-wrap items-center gap-2 pt-2">
                <Badge variant={urgencyVariants.variant} size="sm">
                  {urgencyVariants.label}
                </Badge>
                <Badge variant="info" size="sm">
                  {scheduleLabels[job.schedule] || job.schedule}
                </Badge>
                {salaryText && (
                  <Badge variant="lime" size="sm">
                    {salaryText}
                  </Badge>
                )}
              </div>
            </div>
          </div>

          {/* Action Button: Apply or Manage Applications */}
          <div className="shrink-0 pt-2 sm:pt-0">
            {isOwnJob ? (
              <Link
                to={`/employer/jobs/${job.id}/applications`}
                className="inline-flex items-center justify-center font-medium transition-colors select-none rounded-md text-sm px-4 py-2 gap-2 bg-paper-subtle text-ink hover:bg-border active:bg-border/90 border border-border"
              >
                {t("jobs.viewApplications", {
                  count: job.applications_count,
                })}
              </Link>
            ) : applySuccess ? (
              <Button variant="secondary" size="md" disabled>
                {t("jobs.appliedCheck")}
              </Button>
            ) : (
              <Button
                variant="primary"
                size="md"
                onClick={handleOpenApply}
                className="w-full sm:w-auto"
              >
                {t("jobs.applyWithVideo")}
              </Button>
            )}
          </div>
        </div>

        {/* Job Stats Bar */}
        <div className="flex flex-wrap items-center gap-6 text-xs text-ink-muted pt-4 border-t border-border-subtle">
          <span>
            👁 <strong>{job.views_count}</strong> {t("jobs.viewsCount")}
          </span>
          <span>
            📝 <strong>{job.applications_count}</strong>{" "}
            {t("jobs.candidatesApplied")}
          </span>
          {job.created_at && (
            <span>
              📅{" "}
              {t("jobs.postedDate", {
                date: new Date(job.created_at).toLocaleDateString(),
              })}
            </span>
          )}
        </div>
      </Card>

      {/* Description Section */}
      <Card className="p-6 sm:p-8 space-y-4">
        <h2 className="text-lg font-semibold text-ink border-b border-border-subtle pb-2">
          {t("jobs.aboutTheRole")}
        </h2>
        <div className="prose prose-sm max-w-none text-ink leading-relaxed whitespace-pre-wrap text-xs sm:text-sm">
          {job.description}
        </div>
      </Card>

      {/* Apply Modal Dialog */}
      <Modal
        isOpen={isApplyOpen}
        onClose={handleCloseApply}
        title={t("jobs.applyToTitle", { title: job.title })}
        description={t("jobs.applyModalDesc", { company: companyName })}
        size="md"
      >
        <form onSubmit={handleSubmitApply} className="space-y-4 pt-2">
          {applyError && (
            <div
              role="alert"
              className="p-3.5 rounded-md bg-danger-subtle border border-danger/30 text-danger text-xs sm:text-sm space-y-2"
            >
              <p className="font-medium">{applyError.message}</p>
              {applyError.nextStep && (
                <Button
                  type="button"
                  variant="primary"
                  size="sm"
                  onClick={() => {
                    handleCloseApply();
                    navigate(applyError.nextStep!);
                  }}
                >
                  {applyError.nextStep === "/profile"
                    ? t("jobs.completeProfileNow")
                    : t("jobs.goToVideos")}
                </Button>
              )}
            </div>
          )}

          <Textarea
            id="apply-cover-note"
            label={t("jobs.coverNoteLabel")}
            placeholder={t("jobs.coverNotePlaceholder")}
            value={coverNote}
            onChange={(e) => setCoverNote(e.target.value)}
            maxLength={1000}
            showCount
            rows={5}
            helperText={t("jobs.coverNoteHelper")}
          />

          <div className="flex items-center justify-end gap-2.5 pt-3 border-t border-border-subtle">
            <Button
              type="button"
              variant="ghost"
              onClick={handleCloseApply}
              disabled={isSubmitting}
            >
              {t("jobs.cancel")}
            </Button>
            <Button type="submit" variant="primary" disabled={isSubmitting}>
              {isSubmitting ? (
                <span className="flex items-center gap-2">
                  <Spinner size="sm" />
                  {t("jobs.submitting")}
                </span>
              ) : (
                t("jobs.submitApplication")
              )}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
