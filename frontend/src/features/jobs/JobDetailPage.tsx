import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../../api/client";
import { Avatar } from "../../components/Avatar";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { Modal } from "../../components/Modal";
import { Spinner } from "../../components/Spinner";
import { Textarea } from "../../components/Textarea";
import { applyToJob, fetchJobDetail, formatSalary, recordJobView } from "./api";
import type { Job } from "./types";

export interface JobDetailPageProps {
  currentUserId?: number;
}

export function JobDetailPage({ currentUserId }: JobDetailPageProps) {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

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
            err instanceof Error
              ? err.message
              : "Unable to load job details. The job may no longer be available.",
          );
        }
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [id]);

  const isOwnJob = Boolean(
    job && currentUserId && job.owner_id === currentUserId,
  );

  const handleOpenApply = () => {
    setIsApplyOpen(true);
    setApplyError(null);
  };

  const handleCloseApply = () => {
    setIsApplyOpen(false);
    setApplyError(null);
  };

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
        // Handle apply guards: profile_incomplete or no_video
        if (err.nextStep === "profile") {
          setApplyError({
            message:
              "Your candidate profile is incomplete. Please complete your profile to apply.",
            nextStep: "/profile",
          });
        } else if (err.nextStep === "videos" || err.code === "no_video") {
          setApplyError({
            message:
              "WOZU requires a video introduction before applying. Please record or upload a video resume.",
            nextStep: "/videos",
          });
        } else if (err.status === 409) {
          setApplyError({
            message: "You have already applied for this job.",
          });
          setApplySuccess(true);
        } else if (err.status === 403) {
          setApplyError({
            message: "You cannot apply to your own job listing.",
          });
        } else {
          setApplyError({
            message: err.message || "Failed to submit application.",
          });
        }
      } else {
        setApplyError({
          message:
            err instanceof Error
              ? err.message
              : "An unexpected error occurred while submitting your application.",
        });
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="py-24 flex flex-col items-center justify-center gap-3">
        <h1 className="sr-only">Loading job details</h1>
        <Spinner size="lg" aria-label="Loading job details" />
        <p className="text-sm text-ink-muted">Loading job information...</p>
      </div>
    );
  }

  if (error || !job) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-16 text-center space-y-4">
        <h1 className="text-2xl font-bold text-ink">Job Not Found</h1>
        <p className="text-sm text-ink-muted leading-relaxed">
          {error ||
            "The job you are looking for does not exist or has been removed."}
        </p>
        <Link to="/jobs">
          <Button variant="secondary">Back to Jobs</Button>
        </Link>
      </div>
    );
  }

  const companyName = job.company_name || "Confidential Company";
  const salaryText = formatSalary(
    job.salary_amount,
    job.salary_currency,
    job.salary_type,
  );

  const urgencyVariants = {
    hot: { variant: "danger" as const, label: "Hot 🔥" },
    urgent: { variant: "warning" as const, label: "Urgent ⚡" },
    normal: { variant: "outline" as const, label: "Normal" },
  }[job.urgency] || { variant: "outline" as const, label: job.urgency };

  const scheduleLabels: Record<string, string> = {
    full_time: "Full time",
    part_time: "Part time",
    internship: "Internship",
  };

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-6 text-start">
      {/* Back button / breadcrumb */}
      <div>
        <Link
          to="/jobs"
          className="text-xs sm:text-sm font-medium text-ink-muted hover:text-ink flex items-center gap-1.5 focus:outline-none focus:underline"
        >
          <span aria-hidden="true">←</span> Back to all jobs
        </Link>
      </div>

      {/* Success Notification */}
      {applySuccess && (
        <div
          role="status"
          className="p-4 rounded-lg bg-success-subtle border border-success/30 text-success text-sm flex items-center justify-between gap-3"
        >
          <span>
            ✓ <strong>Application submitted!</strong> The employer will review
            your profile and video introduction.
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
              <Link to={`/employer/jobs/${job.id}/applications`}>
                <Button variant="secondary" size="md">
                  View Applications ({job.applications_count}) ↗
                </Button>
              </Link>
            ) : applySuccess ? (
              <Button variant="secondary" size="md" disabled>
                Applied ✓
              </Button>
            ) : (
              <Button
                variant="primary"
                size="md"
                onClick={handleOpenApply}
                className="w-full sm:w-auto"
              >
                Apply with Video ↗
              </Button>
            )}
          </div>
        </div>

        {/* Job Stats Bar */}
        <div className="flex flex-wrap items-center gap-6 text-xs text-ink-muted pt-4 border-t border-border-subtle">
          <span>
            👁 <strong>{job.views_count}</strong> views
          </span>
          <span>
            📝 <strong>{job.applications_count}</strong> candidates applied
          </span>
          {job.created_at && (
            <span>
              📅 Posted {new Date(job.created_at).toLocaleDateString()}
            </span>
          )}
        </div>
      </Card>

      {/* Description Section */}
      <Card className="p-6 sm:p-8 space-y-4">
        <h2 className="text-lg font-semibold text-ink border-b border-border-subtle pb-2">
          About the Role
        </h2>
        <div className="prose prose-sm max-w-none text-ink leading-relaxed whitespace-pre-wrap text-xs sm:text-sm">
          {job.description}
        </div>
      </Card>

      {/* Apply Modal Dialog */}
      <Modal
        isOpen={isApplyOpen}
        onClose={handleCloseApply}
        title={`Apply to ${job.title}`}
        description={`Submit your application to ${companyName}. WOZU applications prioritize your video resume and profile.`}
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
                    ? "Complete Profile Now →"
                    : "Go to Video Resumes →"}
                </Button>
              )}
            </div>
          )}

          <Textarea
            id="apply-cover-note"
            label="Cover Note (Optional)"
            placeholder="Tell the team why you are excited about this role and how your skills align (max 1000 characters)..."
            value={coverNote}
            onChange={(e) => setCoverNote(e.target.value)}
            maxLength={1000}
            showCount
            rows={5}
            helperText="Keep it brief and conversational. Your video resume does the heavy lifting!"
          />

          <div className="flex items-center justify-end gap-2.5 pt-3 border-t border-border-subtle">
            <Button
              type="button"
              variant="ghost"
              onClick={handleCloseApply}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={isSubmitting}>
              {isSubmitting ? (
                <span className="flex items-center gap-2">
                  <Spinner size="sm" />
                  Submitting...
                </span>
              ) : (
                "Submit Application"
              )}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
