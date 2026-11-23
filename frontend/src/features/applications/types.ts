/**
 * Types for Candidate Applications (FE-15)
 */

export type ApplicationStatus =
  | "submitted"
  | "viewed"
  | "shortlisted"
  | "contacted"
  | "hired"
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
  applicant_display_name?: string | null;
  applicant_first_name?: string | null;
  applicant_last_name?: string | null;
  applicant_position?: string | null;
  applicant_avatar_url?: string | null;
  intro_video_url?: string | null;
}

export interface CandidateFeedItem {
  id: number;
  user_id: number;
  duration_sec: number;
  size_bytes: number;
  content_type: string;
  signed_url: string;
  expires_sec: number;
  created_at: string;
  author_name: string | null;
  author_position?: string | null;
}

export interface CandidateFeedPageOut {
  items: CandidateFeedItem[];
  next_cursor: number | null;
}

export const EMPLOYER_TRANSITIONS: Record<
  ApplicationStatus,
  ApplicationStatus[]
> = {
  submitted: ["viewed", "shortlisted", "rejected"],
  viewed: ["shortlisted", "rejected"],
  shortlisted: ["contacted", "hired", "rejected"],
  contacted: ["hired", "rejected"],
  hired: [],
  rejected: [],
  withdrawn: [],
};

export interface ApplicationsPageOut {
  items: ApplicationItem[];
  next_cursor: number | null;
}

export interface ListApplicationsParams {
  status?: ApplicationStatus | string;
  cursor?: number | null;
  limit?: number;
}
