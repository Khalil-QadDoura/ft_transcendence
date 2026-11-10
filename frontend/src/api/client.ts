/**
 * API Client for WOZU Web (ft_transcendence)
 * FE-20: Build the API client with token refresh and error handling
 *
 * Token Storage Architecture & Trade-off:
 * - Access token: Kept strictly in-memory. This prevents XSS attacks from reading
 *   active bearer credentials from localStorage/sessionStorage. The trade-off is
 *   that the access token is cleared upon page reload.
 * - Refresh token: Stored in localStorage wrapped in try/catch blocks. This allows
 *   session restoration across browser reloads without requiring re-authentication,
 *   while safely handling browser environments where localStorage access is restricted
 *   (e.g., incognito modes, strict iframe sandboxes).
 */

import { QueryClient, type QueryClientConfig } from "@tanstack/react-query";

const DEFAULT_BASE_PATH = "/api";
const REFRESH_PATH = "/auth/refresh";
const REFRESH_MARGIN_MS = 60_000; // 1 minute before expiry
const DEFAULT_ACCESS_TOKEN_LIFETIME_MS = 15 * 60 * 1000; // 15 minutes

const REFRESH_TOKEN_STORAGE_KEY = "wozu_refresh_token";

export interface ApplyGuardDetail {
  code: string;
  next_step: string;
  [key: string]: unknown;
}

export type ApiErrorDetail = string | ApplyGuardDetail | Record<string, unknown>;

export interface RawApiErrorPayload {
  error?: {
    code?: string;
    detail?: ApiErrorDetail;
  };
  detail?: ApiErrorDetail;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: ApiErrorDetail;
  readonly nextStep?: string;

  constructor(status: number, code: string, detail: ApiErrorDetail) {
    let message = code;
    if (typeof detail === "string") {
      message = detail;
    } else if (detail && typeof detail === "object") {
      if ("code" in detail && typeof detail.code === "string") {
        message = detail.code;
      } else if ("next_step" in detail && typeof detail.next_step === "string") {
        message = `next_step: ${detail.next_step}`;
      }
    }
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;

    if (detail && typeof detail === "object" && "next_step" in detail) {
      this.nextStep = String(detail.next_step);
    }
  }
}

// In-memory token state
let inMemoryAccessToken: string | null = null;
let accessTokenExpiresAt: number | null = null;
let refreshTimerId: ReturnType<typeof setTimeout> | null = null;
let activeRefreshPromise: Promise<string | null> | null = null;
let authChangeListeners: Array<(hasToken: boolean) => void> = [];

export function getStoredRefreshToken(): string | null {
  try {
    return localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setStoredRefreshToken(token: string | null): void {
  try {
    if (token) {
      localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, token);
    } else {
      localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
    }
  } catch {
    // Ignore storage quota/permission failures in restricted environments
  }
}

export function getAccessToken(): string | null {
  return inMemoryAccessToken;
}

export function getAccessTokenExpiresAt(): number | null {
  return accessTokenExpiresAt;
}

export function onAuthChange(listener: (hasToken: boolean) => void): () => void {
  authChangeListeners.push(listener);
  return () => {
    authChangeListeners = authChangeListeners.filter((l) => l !== listener);
  };
}

function notifyAuthChange(hasToken: boolean) {
  for (const listener of authChangeListeners) {
    try {
      listener(hasToken);
    } catch (err) {
      console.error("Auth change listener error:", err);
    }
  }
}

export function clearTokens(): void {
  inMemoryAccessToken = null;
  accessTokenExpiresAt = null;
  if (refreshTimerId !== null) {
    clearTimeout(refreshTimerId);
    refreshTimerId = null;
  }
  setStoredRefreshToken(null);
  notifyAuthChange(false);
}

export function setTokens(params: {
  accessToken: string;
  refreshToken?: string;
  expiresInSeconds?: number;
}): void {
  inMemoryAccessToken = params.accessToken;
  const lifetimeMs = params.expiresInSeconds
    ? params.expiresInSeconds * 1000
    : DEFAULT_ACCESS_TOKEN_LIFETIME_MS;
  accessTokenExpiresAt = Date.now() + lifetimeMs;

  if (params.refreshToken) {
    setStoredRefreshToken(params.refreshToken);
  }

  scheduleProactiveRefresh(lifetimeMs);
  notifyAuthChange(true);
}

/**
 * Proactively refreshes the token ~1 minute before expiration
 * to avoid 401 console errors in Chrome during regular user navigation.
 */
export function scheduleProactiveRefresh(lifetimeMs: number): void {
  if (refreshTimerId !== null) {
    clearTimeout(refreshTimerId);
    refreshTimerId = null;
  }

  const delayMs = Math.max(1000, lifetimeMs - REFRESH_MARGIN_MS);
  refreshTimerId = setTimeout(() => {
    refreshAccessToken().catch((err) => {
      console.warn("Proactive token refresh failed:", err);
    });
  }, delayMs);
}

/**
 * Performs token rotation via POST /api/auth/refresh.
 * Deduplicates multiple concurrent refresh requests.
 */
export async function refreshAccessToken(basePath: string = DEFAULT_BASE_PATH): Promise<string | null> {
  if (activeRefreshPromise) {
    return activeRefreshPromise;
  }

  const refreshToken = getStoredRefreshToken();
  if (!refreshToken) {
    clearTokens();
    return null;
  }

  activeRefreshPromise = (async () => {
    try {
      const url = `${basePath}${REFRESH_PATH}`;
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (!response.ok) {
        clearTokens();
        return null;
      }

      const data = (await response.json()) as {
        access_token: string;
        refresh_token: string;
        token_type?: string;
      };

      setTokens({
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
      });

      return data.access_token;
    } catch {
      clearTokens();
      return null;
    } finally {
      activeRefreshPromise = null;
    }
  })();

  return activeRefreshPromise;
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  params?: Record<string, string | number | boolean | undefined | null>;
  skipAuth?: boolean;
  basePath?: string;
}

/**
 * Parses response errors adhering to ft_transcendence API contract:
 * {"error": {"code": "<status string>", "detail": <string or object>}}
 * with fallback to FastAPI standard {"detail": ...}.
 */
export async function parseErrorResponse(response: Response): Promise<ApiError> {
  const status = response.status;
  let code = String(status);
  let detail: ApiErrorDetail = response.statusText || "Request failed";

  try {
    const json = (await response.json()) as RawApiErrorPayload;
    if (json.error) {
      if (json.error.code) code = String(json.error.code);
      if (json.error.detail !== undefined) detail = json.error.detail;
    } else if (json.detail !== undefined) {
      detail = json.detail;
    }
  } catch {
    // If body is not JSON, retain default status text
  }

  return new ApiError(status, code, detail);
}

/**
 * Universal fetch wrapper for API calls with Bearer auth, proactive refresh,
 * 401 retry, and typed error handling.
 */
export async function apiClient<T = unknown>(
  endpoint: string,
  options: RequestOptions = {}
): Promise<T> {
  const basePath = options.basePath ?? DEFAULT_BASE_PATH;
  let url = endpoint.startsWith("http")
    ? endpoint
    : `${basePath}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;

  if (options.params) {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(options.params)) {
      if (value !== undefined && value !== null) {
        searchParams.append(key, String(value));
      }
    }
    const queryString = searchParams.toString();
    if (queryString) {
      url += (url.includes("?") ? "&" : "?") + queryString;
    }
  }

  const headers = new Headers(options.headers || {});
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }

  // Attach body if present
  let body: BodyInit | undefined;
  if (options.body !== undefined) {
    if (
      typeof options.body === "string" ||
      options.body instanceof FormData ||
      options.body instanceof Blob ||
      options.body instanceof URLSearchParams
    ) {
      body = options.body as BodyInit;
    } else {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(options.body);
    }
  }

  // Attach Bearer token if not skipped
  if (!options.skipAuth) {
    const token = getAccessToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }

  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      headers,
      body,
    });
  } catch (networkError) {
    throw new ApiError(0, "network_error", (networkError as Error).message || "Network request failed");
  }

  // Handle unexpected 401: attempt single refresh & retry
  if (response.status === 401 && !options.skipAuth && endpoint !== REFRESH_PATH) {
    const newToken = await refreshAccessToken(basePath);
    if (newToken) {
      headers.set("Authorization", `Bearer ${newToken}`);
      try {
        response = await fetch(url, {
          ...options,
          headers,
          body,
        });
      } catch (networkError) {
        throw new ApiError(0, "network_error", (networkError as Error).message || "Network request failed on retry");
      }
    } else {
      clearTokens();
      throw await parseErrorResponse(response);
    }
  }

  if (!response.ok) {
    throw await parseErrorResponse(response);
  }

  if (response.status === 204) {
    return undefined as unknown as T;
  }

  const contentType = response.headers.get("content-type");
  if (contentType && contentType.includes("application/json")) {
    return (await response.json()) as T;
  }

  return (await response.text()) as unknown as T;
}

/**
 * Standard Query Key Convention for TanStack Query
 */
export const queryKeys = {
  auth: {
    me: ["auth", "me"] as const,
  },
  jobs: {
    all: ["jobs"] as const,
    list: (filters: Record<string, unknown> = {}) => ["jobs", "list", filters] as const,
    detail: (id: number | string) => ["jobs", "detail", String(id)] as const,
  },
  applications: {
    all: ["applications"] as const,
    my: ["applications", "my"] as const,
    forJob: (jobId: number | string) => ["applications", "job", String(jobId)] as const,
  },
  videos: {
    all: ["videos"] as const,
    my: ["videos", "my"] as const,
  },
  chat: {
    conversations: ["chat", "conversations"] as const,
    thread: (id: number | string) => ["chat", "thread", String(id)] as const,
  },
  game: {
    room: (id: string) => ["game", "room", id] as const,
  },
  users: {
    profile: (id: number | string) => ["users", "profile", String(id)] as const,
  },
} as const;

/**
 * TanStack Query Client Configuration
 * Rule: Default retry is OFF for 4xx client errors.
 */
export function createQueryClientConfig(): QueryClientConfig {
  return {
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: (failureCount, error) => {
          // Never retry 4xx errors
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
            return false;
          }
          return failureCount < 2;
        },
      },
      mutations: {
        retry: false,
      },
    },
  };
}

export function createQueryClient(): QueryClient {
  return new QueryClient(createQueryClientConfig());
}
