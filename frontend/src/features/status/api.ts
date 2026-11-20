/**
 * INF-16 / M14: health data for the public status page.
 *
 * This module uses its own small fetch instead of the FE-20 `apiClient`: the shared
 * client throws an `ApiError` on any non-2xx answer and keeps only `error`/`detail`
 * from the body, but GET /api/health answers 503 WITH a full health body when the
 * database or Redis is down (BE-31), and that body is exactly what the page shows.
 * The request is anonymous: no Authorization header, no cookies.
 */

export const HEALTH_URL = "/api/health";
/** A check that takes longer than this counts as "API unreachable". */
export const STATUS_REQUEST_TIMEOUT_MS = 5_000;

/** The only components the page ever shows, in display order. */
export const STATUS_COMPONENTS = [
  "api",
  "database",
  "redis",
  "storage",
  "worker",
] as const;
export type StatusComponent = (typeof STATUS_COMPONENTS)[number];
export type ComponentState = "up" | "down" | "unknown";

/**
 * Whitelist: backend key in `components` for each shown component. The API has no
 * key; it is up whenever a parseable health response arrives. Any other key in the
 * response is ignored.
 */
const BACKEND_KEYS: Record<Exclude<StatusComponent, "api">, string> = {
  database: "db",
  redis: "redis",
  storage: "minio",
  worker: "worker",
};

export interface StatusSnapshot {
  /** False on a network error, timeout or a body that is not a health response. */
  reachable: boolean;
  components: { id: StatusComponent; state: ComponentState }[];
  /** Epoch ms when this check completed (success or failure). */
  checkedAt: number;
}

function toState(value: unknown): ComponentState {
  if (value === "ok") return "up";
  if (value === "down") return "down";
  return "unknown";
}

function unreachable(): StatusSnapshot {
  return {
    reachable: false,
    components: STATUS_COMPONENTS.map((id) => ({
      id,
      state: id === "api" ? "down" : "unknown",
    })),
    checkedAt: Date.now(),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Maps a parsed body to the five whitelisted components; null if it is not a health body. */
export function toSnapshot(body: unknown): StatusSnapshot | null {
  if (!isRecord(body) || !isRecord(body.components)) return null;
  const components = body.components;
  return {
    reachable: true,
    components: STATUS_COMPONENTS.map((id) => ({
      id,
      state:
        id === "api"
          ? "up"
          : Object.hasOwn(components, BACKEND_KEYS[id])
            ? toState(components[BACKEND_KEYS[id]])
            : "unknown",
    })),
    checkedAt: Date.now(),
  };
}

/**
 * One health check. Never rejects for a failed check (that is a result to show);
 * rejects only when the caller aborts, so TanStack Query can cancel it cleanly.
 */
export async function fetchHealth(
  signal?: AbortSignal,
): Promise<StatusSnapshot> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), STATUS_REQUEST_TIMEOUT_MS);
  const cancel = () => controller.abort();
  signal?.addEventListener("abort", cancel, { once: true });
  try {
    const response = await fetch(HEALTH_URL, {
      headers: { Accept: "application/json" },
      credentials: "omit",
      cache: "no-store",
      referrerPolicy: "no-referrer",
      signal: controller.signal,
    });
    // Any status code: a 503 still carries a valid health body. A proxy 502/504
    // page is HTML, so JSON.parse fails and the API counts as unreachable.
    const text = await response.text();
    return toSnapshot(JSON.parse(text)) ?? unreachable();
  } catch (error) {
    if (signal?.aborted) throw error;
    return unreachable();
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
  }
}
