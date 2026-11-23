/**
 * Candidate Applications API Client (FE-15)
 */

import { apiClient } from "../../api/client";
import type {
  ApplicationItem,
  ApplicationStatus,
  ApplicationsPageOut,
  CandidateFeedPageOut,
  ListApplicationsParams,
} from "./types";

/**
 * Fetch applications submitted by the logged-in candidate.
 */
export async function listMyApplications(
  params: ListApplicationsParams = {},
): Promise<ApplicationsPageOut> {
  const queryParams: Record<string, string | number> = {};
  if (params.status) queryParams.status = params.status;
  if (params.cursor !== undefined && params.cursor !== null) {
    queryParams.cursor = params.cursor;
  }
  if (params.limit) queryParams.limit = params.limit;

  return await apiClient<ApplicationsPageOut>("/applications/mine", {
    method: "GET",
    params: queryParams,
  });
}

/**
 * Fetch a single application detail.
 */
export async function getApplication(id: number): Promise<ApplicationItem> {
  return await apiClient<ApplicationItem>(`/applications/${id}`, {
    method: "GET",
  });
}

/**
 * Withdraw an application (DELETE /api/applications/{id} -> 204).
 * Transitions application status to 'withdrawn'.
 */
export async function withdrawApplication(id: number): Promise<void> {
  await apiClient<void>(`/applications/${id}`, {
    method: "DELETE",
  });
}

/**
 * Fetch applications submitted to a job owned by the caller's company (FE-28 / BE-28).
 */
export async function listJobApplications(
  jobId: number | string,
  params: ListApplicationsParams = {},
): Promise<ApplicationsPageOut> {
  const queryParams: Record<string, string | number> = {};
  if (params.status) queryParams.status = params.status;
  if (params.cursor !== undefined && params.cursor !== null) {
    queryParams.cursor = params.cursor;
  }
  if (params.limit) queryParams.limit = params.limit;

  return await apiClient<ApplicationsPageOut>(`/jobs/${jobId}/applications`, {
    method: "GET",
    params: queryParams,
  });
}

/**
 * Update an application's status as an employer (FE-28 / BE-28).
 * Allowed transitions are governed by EMPLOYER_TRANSITIONS.
 * On transition to 'contacted', creates a conversation and sets conversation_id.
 */
export async function updateApplicationStatus(
  appId: number,
  status: ApplicationStatus,
  note?: string | null,
): Promise<ApplicationItem> {
  return await apiClient<ApplicationItem>(`/applications/${appId}/status`, {
    method: "PATCH",
    body: {
      status,
      note: note ?? null,
    },
  });
}

/**
 * Fetch candidate pitch videos for a job feed (FE-28 / BE-25).
 */
export async function getCandidateFeed(
  jobId: number | string,
  params: { cursor?: number | null; limit?: number } = {},
): Promise<CandidateFeedPageOut> {
  const queryParams: Record<string, string | number> = {
    job_id: jobId,
  };
  if (params.cursor !== undefined && params.cursor !== null) {
    queryParams.cursor = params.cursor;
  }
  if (params.limit) queryParams.limit = params.limit;

  return await apiClient<CandidateFeedPageOut>("/media/feed", {
    method: "GET",
    params: queryParams,
  });
}
