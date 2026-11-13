import { Link } from "react-router-dom";
import { Avatar } from "../../components/Avatar";
import { Badge } from "../../components/Badge";
import { Card, CardContent, CardHeader } from "../../components/Card";
import { useText } from "../../i18n/useText";
import { calculateDistanceKm, formatSalary } from "./api";
import type { Job } from "./types";

export interface JobCardProps {
  job: Job;
  userLocation?: { lat: number; lng: number } | null;
  className?: string;
}

export function JobCard({ job, userLocation, className = "" }: JobCardProps) {
  const { t } = useText();
  const companyName = job.company_name || t("jobs.confidentialCompany");
  const salaryText = formatSalary(
    job.salary_amount,
    job.salary_currency,
    job.salary_type,
  );

  // Compute distance if user location is available
  const distance =
    job.distance_km ??
    (userLocation && job.latitude && job.longitude
      ? calculateDistanceKm(
          userLocation.lat,
          userLocation.lng,
          job.latitude,
          job.longitude,
        )
      : null);

  const scheduleLabels: Record<string, string> = {
    full_time: t("jobs.scheduleFullTime"),
    part_time: t("jobs.schedulePartTime"),
    internship: t("jobs.scheduleInternship"),
  };

  const urgencyVariants = {
    hot: { variant: "danger" as const, label: t("jobs.urgencyHot") },
    urgent: { variant: "warning" as const, label: t("jobs.urgencyUrgent") },
    normal: { variant: "outline" as const, label: t("jobs.urgencyNormal") },
  }[job.urgency] || { variant: "outline" as const, label: job.urgency };

  return (
    <Card
      data-testid={`job-card-${job.id}`}
      className={`hover:border-ink-muted/50 transition-colors shadow-xs group ${className}`}
    >
      <CardHeader className="p-4 sm:p-5 pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0">
            <Avatar
              alt={companyName}
              fallbackText={companyName}
              size="md"
              className="mt-0.5 shrink-0 bg-surface-muted border border-border"
            />
            <div className="min-w-0">
              <Link
                to={`/jobs/${job.id}`}
                className="text-base sm:text-lg font-semibold text-ink hover:underline focus:outline-none focus:ring-2 focus:ring-lime rounded-xs block truncate"
              >
                {job.title}
              </Link>
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-ink-muted mt-0.5">
                <span className="font-medium text-ink-base truncate max-w-[200px]">
                  {companyName}
                </span>
                {job.location && (
                  <>
                    <span aria-hidden="true">•</span>
                    <span className="truncate">{job.location}</span>
                  </>
                )}
              </div>
            </div>
          </div>

          <Link
            to={`/jobs/${job.id}`}
            aria-label={t("jobs.viewDetails", { title: job.title })}
            className="text-xs font-semibold text-ink-muted group-hover:text-ink shrink-0 p-1 rounded-sm focus:outline-none focus:ring-2 focus:ring-lime"
          >
            <span aria-hidden="true">↗</span>
          </Link>
        </div>
      </CardHeader>

      <CardContent className="p-4 sm:p-5 pt-1 space-y-3">
        {job.description && (
          <p className="text-xs sm:text-sm text-ink-muted line-clamp-2 leading-relaxed">
            {job.description}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-1.5 pt-1 border-t border-border-subtle/60">
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

          {distance !== null && distance !== undefined && (
            <Badge variant="outline" size="sm" className="font-mono">
              📍 {distance} {t("jobs.kmAway")}
            </Badge>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
