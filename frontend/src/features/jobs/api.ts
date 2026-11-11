/**
 * API fetching functions for Jobs
 * Card FE-23: Build the jobs search page with filters, sorting and load more
 */

import { apiClient } from "../../api/client";
import type { Job, JobListResponse, JobSearchFilters } from "./types";

/**
 * Fetch open jobs from GET /api/jobs/open with query filters.
 */
export async function fetchOpenJobs(
  filters: JobSearchFilters = {},
): Promise<JobListResponse> {
  const params: Record<string, string | number | boolean | undefined | null> = {
    keyword: filters.keyword || undefined,
    position: filters.position || undefined,
    schedule: filters.schedule || undefined,
    salary_min:
      filters.salary_min !== undefined && filters.salary_min !== null
        ? filters.salary_min
        : undefined,
    salary_max:
      filters.salary_max !== undefined && filters.salary_max !== null
        ? filters.salary_max
        : undefined,
    urgency: filters.urgency || undefined,
    lat:
      filters.lat !== undefined && filters.lat !== null
        ? filters.lat
        : undefined,
    lng:
      filters.lng !== undefined && filters.lng !== null
        ? filters.lng
        : undefined,
    radius_km:
      filters.radius_km !== undefined && filters.radius_km !== null
        ? filters.radius_km
        : undefined,
    sort_by: filters.sort_by || undefined,
    cursor:
      filters.cursor !== undefined && filters.cursor !== null
        ? filters.cursor
        : undefined,
    limit: filters.limit ?? 20,
  };

  return apiClient<JobListResponse>("/jobs/open", {
    method: "GET",
    params,
  });
}

/**
 * Calculates distance between two coordinates in kilometers using the Haversine formula.
 */
export function calculateDistanceKm(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  const R = 6371; // Earth's radius in km
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(toRad(lat1)) *
      Math.cos(toRad(lat2)) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return Math.round(R * c * 10) / 10;
}

function toRad(degrees: number): number {
  return (degrees * Math.PI) / 180;
}

/**
 * Fetch a single job by id from GET /api/jobs/{id}.
 */
export async function fetchJobDetail(id: number | string): Promise<Job> {
  return apiClient<Job>(`/jobs/${id}`, {
    method: "GET",
  });
}

/**
 * Record a view for a job: POST /api/jobs/{id}/view (counted once per user per 24h).
 */
export async function recordJobView(id: number | string): Promise<void> {
  try {
    await apiClient<void>(`/jobs/${id}/view`, {
      method: "POST",
    });
  } catch {
    // Silently fail view recording without interrupting the user experience
  }
}

/**
 * Apply to a job: POST /api/jobs/{id}/apply with optional cover note (<= 1000 chars).
 */
export async function applyToJob(
  id: number | string,
  coverNote?: string,
): Promise<{ id: number; status: string }> {
  return apiClient<{ id: number; status: string }>(`/jobs/${id}/apply`, {
    method: "POST",
    body: coverNote ? { cover_note: coverNote } : {},
  });
}

/**
 * Formats salary amount, currency, and type into human-friendly string.
 */
export function formatSalary(
  amount: string | number | null | undefined,
  currency: string | null | undefined,
  type: string | null | undefined,
): string | null {
  if (amount === null || amount === undefined || amount === "") {
    return null;
  }

  const num = typeof amount === "number" ? amount : parseFloat(amount);
  if (isNaN(num)) return null;

  const formattedNum = new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 0,
  }).format(num);

  const curr = currency ? currency.toUpperCase() : "$";
  const period = type ? ` / ${type}` : "";

  return `${curr} ${formattedNum}${period}`;
}
