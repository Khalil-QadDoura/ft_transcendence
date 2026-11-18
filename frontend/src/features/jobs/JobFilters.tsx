import { useEffect, useRef, useState } from "react";
import { Button } from "../../components/Button";
import { Input } from "../../components/Input";
import { Select } from "../../components/Select";
import { useText } from "../../i18n/useText";
import type {
  JobSchedule,
  JobSearchFilters,
  JobSortBy,
  JobUrgency,
} from "./types";

export interface JobFiltersProps {
  filters: JobSearchFilters;
  onChange: (filters: JobSearchFilters) => void;
  onReset: () => void;
  userLocation: { lat: number; lng: number } | null;
  onRequestLocation: () => void;
  onClearLocation: () => void;
  locationLoading?: boolean;
  locationError?: string | null;
  className?: string;
}

export function JobFilters({
  filters,
  onChange,
  onReset,
  userLocation,
  onRequestLocation,
  onClearLocation,
  locationLoading = false,
  locationError = null,
  className = "",
}: JobFiltersProps) {
  const { t } = useText();
  const [isMobileExpanded, setIsMobileExpanded] = useState(false);
  const [keywordInput, setKeywordInput] = useState(filters.keyword || "");
  const latestFiltersRef = useRef(filters);
  latestFiltersRef.current = filters;
  const latestOnChangeRef = useRef(onChange);
  latestOnChangeRef.current = onChange;

  useEffect(() => {
    setKeywordInput(filters.keyword || "");
  }, [filters.keyword]);

  useEffect(() => {
    if ((latestFiltersRef.current.keyword || "") === keywordInput) return;
    const timer = setTimeout(() => {
      latestOnChangeRef.current({
        ...latestFiltersRef.current,
        keyword: keywordInput === "" ? undefined : keywordInput,
        cursor: undefined,
      });
    }, 300);
    return () => clearTimeout(timer);
  }, [keywordInput]);

  const handleFieldChange = (key: keyof JobSearchFilters, value: unknown) => {
    onChange({
      ...filters,
      [key]: value === "" || value === undefined ? undefined : value,
      cursor: undefined, // Reset pagination cursor when filters change
    });
  };

  const scheduleOptions = [
    { value: "", label: t("jobs.allSchedules") },
    { value: "full_time", label: t("jobs.scheduleFullTime") },
    { value: "part_time", label: t("jobs.schedulePartTime") },
    { value: "internship", label: t("jobs.scheduleInternship") },
  ];

  const urgencyOptions = [
    { value: "", label: t("jobs.allUrgencies") },
    { value: "hot", label: t("jobs.urgencyHot") },
    { value: "urgent", label: t("jobs.urgencyUrgent") },
    { value: "normal", label: t("jobs.urgencyNormal") },
  ];

  const sortOptions = [
    { value: "newest", label: t("jobs.newestFirst") },
    {
      value: "nearest",
      label: userLocation
        ? t("jobs.nearestToMe")
        : t("jobs.nearestRequiresLocation"),
      disabled: !userLocation,
    },
  ];

  const radiusOptions = [
    { value: "10", label: "10 km" },
    { value: "25", label: "25 km" },
    { value: "50", label: "50 km" },
    { value: "100", label: "100 km" },
    { value: "250", label: "250 km" },
    { value: "500", label: "500 km" },
  ];

  const hasActiveFilters = Boolean(
    filters.keyword ||
    filters.position ||
    filters.schedule ||
    filters.urgency ||
    filters.salary_min ||
    filters.salary_max ||
    userLocation ||
    filters.sort_by === "nearest",
  );

  return (
    <div
      className={`bg-surface border border-border rounded-lg p-4 sm:p-5 shadow-xs ${className}`}
      data-testid="job-filters"
    >
      {/* Top Search Bar: Keyword & Quick Controls */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="flex-1">
          <Input
            id="job-keyword-filter"
            aria-label={t("jobs.searchJobs")}
            placeholder={t("jobs.searchPlaceholder")}
            value={keywordInput}
            onChange={(e) => setKeywordInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                handleFieldChange("keyword", keywordInput);
              }
            }}
            startAddon={<span aria-hidden="true">🔍</span>}
          />
        </div>

        <div className="w-full sm:w-48">
          <Select
            id="job-sort-filter"
            aria-label={t("jobs.sortBy")}
            options={sortOptions}
            value={filters.sort_by || "newest"}
            onChange={(e) =>
              handleFieldChange("sort_by", e.target.value as JobSortBy)
            }
          />
        </div>

        <Button
          type="button"
          variant="secondary"
          className="sm:hidden"
          onClick={() => setIsMobileExpanded(!isMobileExpanded)}
          aria-expanded={isMobileExpanded}
          aria-controls="expanded-filters-panel"
        >
          {isMobileExpanded ? t("jobs.hideFilters") : t("jobs.moreFilters")}
        </Button>
      </div>

      {/* Expandable/Desktop Filters Grid */}
      <div
        id="expanded-filters-panel"
        className={`space-y-4 pt-4 border-t border-border-subtle mt-4 sm:block ${
          isMobileExpanded ? "block" : "hidden sm:block"
        }`}
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
          {/* Position / Title filter */}
          <Input
            id="job-position-filter"
            label={t("jobs.positionRole")}
            placeholder={t("jobs.positionPlaceholder")}
            value={filters.position || ""}
            onChange={(e) => handleFieldChange("position", e.target.value)}
          />

          {/* Schedule */}
          <Select
            id="job-schedule-filter"
            label={t("jobs.schedule")}
            options={scheduleOptions}
            value={filters.schedule || ""}
            onChange={(e) =>
              handleFieldChange("schedule", e.target.value as JobSchedule)
            }
          />

          {/* Urgency */}
          <Select
            id="job-urgency-filter"
            label={t("jobs.urgency")}
            options={urgencyOptions}
            value={filters.urgency || ""}
            onChange={(e) =>
              handleFieldChange("urgency", e.target.value as JobUrgency)
            }
          />

          {/* Salary Range */}
          <div>
            <label className="block text-sm font-medium text-ink mb-1 select-none">
              {t("jobs.salaryRange")}
            </label>
            <div className="flex items-center gap-2">
              <input
                id="job-salary-min-filter"
                type="number"
                placeholder={t("jobs.salaryMin")}
                min="0"
                value={filters.salary_min ?? ""}
                onChange={(e) =>
                  handleFieldChange(
                    "salary_min",
                    e.target.value ? Number(e.target.value) : undefined,
                  )
                }
                className="w-full h-10 px-2.5 rounded-sm border border-border bg-surface text-ink text-sm focus:outline-none focus:ring-2 focus:ring-lime"
                aria-label={t("jobs.salaryMinAria")}
              />
              <span className="text-ink-muted text-xs shrink-0">—</span>
              <input
                id="job-salary-max-filter"
                type="number"
                placeholder={t("jobs.salaryMax")}
                min="0"
                value={filters.salary_max ?? ""}
                onChange={(e) =>
                  handleFieldChange(
                    "salary_max",
                    e.target.value ? Number(e.target.value) : undefined,
                  )
                }
                className="w-full h-10 px-2.5 rounded-sm border border-border bg-surface text-ink text-sm focus:outline-none focus:ring-2 focus:ring-lime"
                aria-label={t("jobs.salaryMaxAria")}
              />
            </div>
          </div>
        </div>

        {/* Location & Radius Geolocation Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-border-subtle/60 text-xs sm:text-sm">
          <div className="flex flex-wrap items-center gap-2">
            {!userLocation ? (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={onRequestLocation}
                disabled={locationLoading}
                aria-label={t("jobs.useMyLocationAria")}
              >
                {locationLoading
                  ? t("jobs.detectingLocation")
                  : t("jobs.useMyLocation")}
              </Button>
            ) : (
              <div className="flex flex-wrap items-center gap-2 bg-surface-muted px-2.5 py-1 rounded-sm border border-border">
                <span className="font-medium text-ink">
                  {t("jobs.locationActive", {
                    lat: userLocation.lat.toFixed(2),
                    lng: userLocation.lng.toFixed(2),
                  })}
                </span>

                <div className="flex items-center gap-1.5 ms-2">
                  <label
                    htmlFor="job-radius-filter"
                    className="text-ink-muted text-xs font-medium"
                  >
                    {t("jobs.radius")}
                  </label>
                  <select
                    id="job-radius-filter"
                    value={filters.radius_km || "50"}
                    onChange={(e) =>
                      handleFieldChange("radius_km", Number(e.target.value))
                    }
                    className="h-7 text-xs rounded-xs border border-border bg-surface px-1 text-ink focus:ring-1 focus:ring-lime focus:outline-none"
                  >
                    {radiusOptions.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>

                <button
                  type="button"
                  onClick={onClearLocation}
                  className="text-xs text-danger hover:underline ms-2"
                  aria-label={t("jobs.clearLocation")}
                >
                  {t("jobs.clear")}
                </button>
              </div>
            )}

            {locationError && (
              <span className="text-danger text-xs font-medium" role="alert">
                {locationError}
              </span>
            )}
          </div>

          {hasActiveFilters && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onReset}
              className="text-danger hover:text-danger hover:bg-danger-subtle ms-auto"
            >
              {t("jobs.resetFilters")}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
