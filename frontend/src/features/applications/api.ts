/**
 * Candidate Applications API Client (FE-15)
 */

import { apiClient } from "../../api/client";
import type {
  ApplicationItem,
  ApplicationsPageOut,
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
