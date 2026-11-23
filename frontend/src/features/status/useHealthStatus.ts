import { useQuery } from "@tanstack/react-query";
import { fetchHealth, type StatusSnapshot } from "./api";

/** The status page checks GET /api/health this often while its tab is visible. */
export const STATUS_POLL_INTERVAL_MS = 15_000;
export const statusQueryKey = ["status", "health"] as const;

export type OverallStatus =
  "checking" | "operational" | "degraded" | "unreachable";

export function overallStatus(
  snapshot: StatusSnapshot | undefined,
): OverallStatus {
  if (!snapshot) return "checking";
  if (!snapshot.reachable) return "unreachable";
  return snapshot.components.every(({ state }) => state === "up")
    ? "operational"
    : "degraded";
}

export function useHealthStatus() {
  return useQuery({
    queryKey: statusQueryKey,
    queryFn: ({ signal }) => fetchHealth(signal),
    refetchInterval: STATUS_POLL_INTERVAL_MS,
    // Hidden tabs do not poll; coming back to the tab checks at once.
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: "always",
    staleTime: 0,
    // A failed check is already a result (fetchHealth resolves); no retry storms.
    retry: false,
  });
}
