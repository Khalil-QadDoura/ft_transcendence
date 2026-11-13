/**
 * Types for Candidate Applications (FE-15)
 */

export type ApplicationStatus =
  | "submitted"
  | "viewed"
  | "invited"
  | "rejected"
  | "withdrawn";

export interface ApplicationItem {
  id: number;
  job_id: number;
  applicant_id: number;
  company_id: number;
  intro_video_id: number | null;
  status: ApplicationStatus;
  cover_note: string | null;
  conversation_id: number | null;
  applied_at: string;
  updated_at: string;
  viewed_at: string | null;
  job_title?: string | null;
  company_name?: string | null;
}

export interface ApplicationsPageOut {
  items: ApplicationItem[];
  next_cursor: number | null;
}

export interface ListApplicationsParams {
  status?: ApplicationStatus | string;
  cursor?: number | null;
  limit?: number;
}
