/**
 * Types and interfaces for the Jobs feature
 * Card FE-23: Build the jobs search page with filters, sorting and load more
 */

export type JobSchedule = "full_time" | "part_time" | "internship";
export type JobUrgency = "normal" | "urgent" | "hot";
export type JobSalaryType = "hourly" | "daily" | "weekly" | "monthly";
export type JobSortBy = "newest" | "nearest";

export interface Job {
  id: number;
  owner_id: number;
  company_name?: string | null;
  company_logo_url?: string | null;
  title: string;
  description: string;
  status: "active" | "open" | "deleted";
  latitude: number;
  longitude: number;
  location: string;
  salary_amount?: string | number | null;
  salary_type: JobSalaryType;
  salary_currency?: string | null;
  schedule: JobSchedule;
  urgency: JobUrgency;
  views_count: number;
  applications_count: number;
  new_applications_count?: number;
  created_at: string;
  updated_at?: string;
  distance_km?: number | null;
}

export interface JobListResponse {
  items: Job[];
  next_cursor: number | null;
}

export interface JobSearchFilters {
  keyword?: string;
  position?: string;
  schedule?: JobSchedule;
  salary_min?: number;
  salary_max?: number;
  urgency?: JobUrgency;
  lat?: number;
  lng?: number;
  radius_km?: number;
  sort_by?: JobSortBy;
  cursor?: number;
  limit?: number;
}
