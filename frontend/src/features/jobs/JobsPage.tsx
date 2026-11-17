import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { Spinner } from "../../components/Spinner";
import { useText } from "../../i18n/useText";
import { fetchOpenJobs } from "./api";
import { JobCard } from "./JobCard";
import { JobFilters } from "./JobFilters";
import type {
  Job,
  JobSchedule,
  JobSearchFilters,
  JobSortBy,
  JobUrgency,
} from "./types";

export function JobsPage() {
  const { t } = useText();
  const [searchParams, setSearchParams] = useSearchParams();

  // Parse filters from URL search parameters
  const filters: JobSearchFilters = useMemo(() => {
    const keyword = searchParams.get("keyword") || undefined;
    const position = searchParams.get("position") || undefined;
    const schedule = (searchParams.get("schedule") as JobSchedule) || undefined;
    const urgency = (searchParams.get("urgency") as JobUrgency) || undefined;
    const salaryMinStr = searchParams.get("salary_min");
    const salaryMaxStr = searchParams.get("salary_max");
    const salary_min = salaryMinStr ? Number(salaryMinStr) : undefined;
    const salary_max = salaryMaxStr ? Number(salaryMaxStr) : undefined;
    const latStr = searchParams.get("lat");
    const lngStr = searchParams.get("lng");
    const radiusStr = searchParams.get("radius_km");
    const lat = latStr ? Number(latStr) : undefined;
    const lng = lngStr ? Number(lngStr) : undefined;
    const radius_km = radiusStr ? Number(radiusStr) : undefined;
    const sort_by = (searchParams.get("sort_by") as JobSortBy) || "newest";

    return {
      keyword,
      position,
      schedule,
      urgency,
      salary_min,
      salary_max,
      lat,
      lng,
      radius_km,
      sort_by,
    };
  }, [searchParams]);

  const [jobs, setJobs] = useState<Job[]>([]);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // Geolocation state
  const [locationLoading, setLocationLoading] = useState(false);
  const [locationError, setLocationError] = useState<string | null>(null);

  const userLocation = useMemo(() => {
    if (filters.lat !== undefined && filters.lng !== undefined) {
      return { lat: filters.lat, lng: filters.lng };
    }
    return null;
  }, [filters.lat, filters.lng]);

  // Sync state to URL search parameters
  const updateFilters = (newFilters: JobSearchFilters) => {
    const params = new URLSearchParams();

    if (newFilters.keyword) params.set("keyword", newFilters.keyword);
    if (newFilters.position) params.set("position", newFilters.position);
    if (newFilters.schedule) params.set("schedule", newFilters.schedule);
    if (newFilters.urgency) params.set("urgency", newFilters.urgency);
    if (newFilters.salary_min !== undefined)
      params.set("salary_min", String(newFilters.salary_min));
    if (newFilters.salary_max !== undefined)
      params.set("salary_max", String(newFilters.salary_max));
    if (newFilters.lat !== undefined) params.set("lat", String(newFilters.lat));
    if (newFilters.lng !== undefined) params.set("lng", String(newFilters.lng));
    if (newFilters.radius_km !== undefined)
      params.set("radius_km", String(newFilters.radius_km));
    if (newFilters.sort_by && newFilters.sort_by !== "newest") {
      params.set("sort_by", newFilters.sort_by);
    }

    setSearchParams(params, { replace: true });
  };

  const handleResetFilters = () => {
    setSearchParams(new URLSearchParams(), { replace: true });
    setLocationError(null);
  };

  const handleRequestLocation = () => {
    if (!navigator.geolocation) {
      setLocationError(t("jobs.geoNotSupported"));
      return;
    }

    setLocationLoading(true);
    setLocationError(null);

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocationLoading(false);
        updateFilters({
          ...filters,
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          radius_km: filters.radius_km || 50,
          sort_by: "nearest",
        });
      },
      (err) => {
        setLocationLoading(false);
        if (err.code === err.PERMISSION_DENIED) {
          setLocationError(t("jobs.locationPermissionDenied"));
        } else {
          setLocationError(t("jobs.locationUnavailable"));
        }
      },
      { timeout: 10000, enableHighAccuracy: false },
    );
  };

  const handleClearLocation = () => {
    updateFilters({
      ...filters,
      lat: undefined,
      lng: undefined,
      radius_km: undefined,
      sort_by: "newest",
    });
    setLocationError(null);
  };

  // Initial load or filter change: fetch page 1
  useEffect(() => {
    let isCancelled = false;

    const loadInitialJobs = async () => {
      setIsLoading(true);
      setError(null);
      setLoadMoreError(null);

      try {
        const response = await fetchOpenJobs(filters);
        if (!isCancelled) {
          setJobs(response.items);
          setNextCursor(response.next_cursor);
        }
      } catch (err) {
        if (!isCancelled) {
          setError(
            err instanceof Error ? err.message : t("jobs.failedToLoadJobs"),
          );
        }
      } finally {
        if (!isCancelled) {
          setIsLoading(false);
        }
      }
    };

    loadInitialJobs();

    return () => {
      isCancelled = true;
    };
  }, [filters, reloadKey, t]);

  // Load more cursor pagination
  const handleLoadMore = async () => {
    if (!nextCursor || isLoadingMore) return;

    setIsLoadingMore(true);
    setLoadMoreError(null);
    try {
      const response = await fetchOpenJobs({
        ...filters,
        cursor: nextCursor,
      });

      setJobs((prev) => [...prev, ...response.items]);
      setNextCursor(response.next_cursor);
    } catch (err) {
      setLoadMoreError(
        err instanceof Error ? err.message : t("jobs.failedToLoadMore"),
      );
    } finally {
      setIsLoadingMore(false);
    }
  };

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-6">
      {/* Page Heading */}
      <div className="space-y-1 text-start">
        <span className="eyebrow text-xs font-mono uppercase tracking-wider text-ink-muted">
          {t("jobs.eyebrow")}
        </span>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-ink">
          {t("jobs.title")}
        </h1>
        <p className="text-sm text-ink-muted max-w-2xl leading-relaxed">
          {t("jobs.subtitle")}
        </p>
      </div>

      {/* Filter Controls */}
      <JobFilters
        filters={filters}
        onChange={updateFilters}
        onReset={handleResetFilters}
        userLocation={userLocation}
        onRequestLocation={handleRequestLocation}
        onClearLocation={handleClearLocation}
        locationLoading={locationLoading}
        locationError={locationError}
      />

      {/* Results Header */}
      {!isLoading && !error && (
        <div className="flex items-center justify-between text-xs sm:text-sm text-ink-muted pt-2 border-b border-border-subtle pb-2">
          <span>{t("jobs.showingRoles", { count: jobs.length })}</span>
          {filters.sort_by === "nearest" && userLocation && (
            <span className="text-lime-dark font-medium">
              {t("jobs.sortedByDistance")}
            </span>
          )}
        </div>
      )}

      {/* Error Alert */}
      {error && (
        <div
          role="alert"
          className="p-4 rounded-lg bg-danger-subtle border border-danger/30 text-danger text-sm flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-start"
        >
          <div>
            <strong className="block font-semibold">
              {t("jobs.errorLoading")}
            </strong>
            <span>{error}</span>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setReloadKey((k) => k + 1)}
          >
            {t("jobs.retry")}
          </Button>
        </div>
      )}

      {/* Loading Spinner */}
      {isLoading && (
        <div className="py-16 flex flex-col items-center justify-center gap-3">
          <Spinner size="lg" aria-label={t("jobs.loadingAvailable")} />
          <p className="text-xs text-ink-muted">{t("jobs.fetchingLatest")}</p>
        </div>
      )}

      {/* Empty State */}
      {!isLoading && !error && jobs.length === 0 && (
        <div className="py-8">
          <EmptyState
            title={t("jobs.noRolesFound")}
            description={t("jobs.noRolesDescription")}
            action={
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={handleResetFilters}
              >
                {t("jobs.resetAllFilters")}
              </Button>
            }
          />
        </div>
      )}

      {/* Job Cards List */}
      {!isLoading && !error && jobs.length > 0 && (
        <div className="space-y-3.5" data-testid="jobs-list">
          {jobs.map((job) => (
            <JobCard key={job.id} job={job} userLocation={userLocation} />
          ))}
        </div>
      )}

      {/* Load More Error Alert */}
      {loadMoreError && (
        <div
          role="alert"
          className="p-3.5 rounded-lg bg-danger-subtle border border-danger/30 text-danger text-sm flex items-center justify-between gap-3 text-start"
        >
          <span>{loadMoreError}</span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleLoadMore}
            disabled={isLoadingMore}
          >
            {t("jobs.retry")}
          </Button>
        </div>
      )}

      {/* Load More Button */}
      {!isLoading && !error && nextCursor !== null && !loadMoreError && (
        <div className="pt-4 pb-8 flex justify-center">
          <Button
            type="button"
            variant="secondary"
            size="md"
            onClick={handleLoadMore}
            disabled={isLoadingMore}
            className="min-w-44"
          >
            {isLoadingMore ? (
              <span className="flex items-center gap-2">
                <Spinner size="sm" />
                {t("jobs.loadingMore")}
              </span>
            ) : (
              t("jobs.loadMoreJobs")
            )}
          </Button>
        </div>
      )}
    </div>
  );
}
