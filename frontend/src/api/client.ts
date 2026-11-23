import { activeLanguage } from "../i18n";
/**
 * API Client for WOZU Web (ft_transcendence)
 * FE-20: Build the API client with token refresh and error handling
 *
 * Token Storage Architecture & Trade-off:
 * - Access token: Kept strictly in-memory. This avoids persisting access credentials in browser storage; it does not
 *   protect credentials from JavaScript already executing on this origin. The trade-off is
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

export type ApiErrorDetail =
  string | ApplyGuardDetail | Record<string, unknown>;

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
      } else if (
        "next_step" in detail &&
        typeof detail.next_step === "string"
      ) {
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

// One shared session for auth screens and domain requests. Version changes invalidate
// requests from an older login/logout; ordinary refresh keeps the same session.
let inMemoryAccessToken: string | null = null;
let inMemoryRefreshToken: string | null = null;
let accessTokenExpiresAt: number | null = null;
let refreshTimerId: ReturnType<typeof setTimeout> | null = null;
let sessionVersion = 0;
const authChangeListeners = new Set<(hasToken: boolean) => void>();
type TokenPair = { access_token: string; refresh_token: string };
type RefreshFlight = {
  version: number;
  result: Promise<TokenPair | null>;
  promise: Promise<string | null>;
};
let activeRefresh: RefreshFlight | null = null;

export function getStoredRefreshToken(): string | null {
  try {
    return (
      localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY) || inMemoryRefreshToken
    );
  } catch {
    return inMemoryRefreshToken;
  }
}

export function setStoredRefreshToken(token: string | null): void {
  inMemoryRefreshToken = token;
  try {
    if (token) localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, token);
    else localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
  } catch {
    // Restricted storage retains a tab-only session; reload requires login.
  }
}

export function getAccessToken(): string | null {
  return inMemoryAccessToken;
}
export function getAccessTokenExpiresAt(): number | null {
  return accessTokenExpiresAt;
}
export function getSessionVersion(): number {
  return sessionVersion;
}

export function onAuthChange(
  listener: (hasToken: boolean) => void,
): () => void {
  authChangeListeners.add(listener);
  return () => {
    authChangeListeners.delete(listener);
  };
}
function notifyAuthChange(hasToken: boolean) {
  for (const listener of authChangeListeners) listener(hasToken);
}
export function clearTokens(): void {
  sessionVersion++;
  activeRefresh = null;
  inMemoryAccessToken = null;
  accessTokenExpiresAt = null;
  if (refreshTimerId !== null) clearTimeout(refreshTimerId);
  refreshTimerId = null;
  setStoredRefreshToken(null);
  notifyAuthChange(false);
}

type TokenInput = {
  accessToken: string;
  refreshToken?: string;
  expiresInSeconds?: number;
};
function installTokens(params: TokenInput): void {
  inMemoryAccessToken = params.accessToken;
  const lifetimeMs =
    (params.expiresInSeconds ?? DEFAULT_ACCESS_TOKEN_LIFETIME_MS / 1000) * 1000;
  accessTokenExpiresAt = Date.now() + lifetimeMs;
  if (params.refreshToken) setStoredRefreshToken(params.refreshToken);
  scheduleProactiveRefresh(lifetimeMs);
  notifyAuthChange(true);
}
export function setTokens(params: TokenInput): void {
  sessionVersion++;
  activeRefresh = null;
  setStoredRefreshToken(params.refreshToken ?? null);
  installTokens(params);
}
export function scheduleProactiveRefresh(lifetimeMs: number): void {
  if (refreshTimerId !== null) clearTimeout(refreshTimerId);
  refreshTimerId = setTimeout(
    () => {
      void refreshAccessToken().catch(() => {
        /* A retry is scheduled below. */
      });
    },
    Math.max(1000, lifetimeMs - REFRESH_MARGIN_MS),
  );
}

async function rotateToken(
  refreshToken: string,
  basePath: string,
): Promise<TokenPair | null> {
  const response = await fetch(`${basePath}${REFRESH_PATH}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "Accept-Language": activeLanguage(),
    },
    body: JSON.stringify({ refresh_token: refreshToken }),
    signal: AbortSignal.timeout(15_000),
    cache: "no-store",
    referrerPolicy: "no-referrer",
  });
  if (response.status === 401) return null;
  if (!response.ok) throw await parseErrorResponse(response);
  const data: unknown = await response.json();
  if (
    !data ||
    typeof data !== "object" ||
    !("access_token" in data) ||
    typeof data.access_token !== "string" ||
    !data.access_token ||
    !("refresh_token" in data) ||
    typeof data.refresh_token !== "string" ||
    !data.refresh_token ||
    ("token_type" in data && data.token_type !== "bearer")
  ) {
    throw new ApiError(
      502,
      "invalid_token_response",
      "Invalid session response",
    );
  }
  return { access_token: data.access_token, refresh_token: data.refresh_token };
}

/** Single flight per session, including startup restoration and scheduled refresh. */
export function refreshAccessToken(
  basePath = DEFAULT_BASE_PATH,
): Promise<string | null> {
  if (activeRefresh?.version === sessionVersion) return activeRefresh.promise;
  const token = getStoredRefreshToken();
  if (!token) {
    clearTokens();
    return Promise.resolve(null);
  }
  const flight: RefreshFlight = {
    version: sessionVersion,
    result: rotateToken(token, basePath),
    promise: Promise.resolve(null),
  };
  activeRefresh = flight;
  flight.promise = flight.result
    .then((pair) => {
      if (flight.version !== sessionVersion) return null;
      if (!pair) {
        clearTokens();
        return null;
      }
      installTokens({
        accessToken: pair.access_token,
        refreshToken: pair.refresh_token,
      });
      return pair.access_token;
    })
    .catch((error: unknown) => {
      if (flight.version !== sessionVersion) return null;
      if (
        error instanceof ApiError &&
        error.code === "invalid_token_response"
      ) {
        clearTokens();
        return null;
      }
      // A transport outage/rate limit is not evidence that credentials were revoked.
      // Keep this session and retry later; logout/new login cancels this timer.
      if (refreshTimerId !== null) clearTimeout(refreshTimerId);
      refreshTimerId = setTimeout(() => {
        void refreshAccessToken(basePath).catch(() => {
          /* Keep the retry bounded. */
        });
      }, 30_000);
      throw error instanceof ApiError
        ? error
        : new ApiError(
            0,
            "network_error",
            "Session refresh is temporarily unavailable",
          );
    })
    .finally(() => {
      if (activeRefresh === flight) activeRefresh = null;
    });
  return flight.promise;
}

/** Clear UI state immediately, then revoke both the old token and any in-flight
 * rotation's replacement. Khalil's logout revokes one refresh token, not all sessions.
 */
export async function logoutSession(): Promise<void> {
  const token = getStoredRefreshToken();
  const pending = activeRefresh?.result;
  clearTokens();
  let rotationFailed = false;
  const pair = await pending?.catch(() => {
    rotationFailed = true;
    return null;
  });
  const tokens = new Set(
    [token, pair?.refresh_token].filter((value): value is string =>
      Boolean(value),
    ),
  );
  await Promise.all(
    [...tokens].map((refreshToken) =>
      apiClient("/auth/logout", {
        method: "POST",
        body: { refresh_token: refreshToken },
        skipAuth: true,
        signal: AbortSignal.timeout(15_000),
        cache: "no-store",
        referrerPolicy: "no-referrer",
      }),
    ),
  );
  if (rotationFailed)
    throw new ApiError(
      0,
      "logout_unconfirmed",
      "Session revocation could not be confirmed",
    );
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
export async function parseErrorResponse(
  response: Response,
): Promise<ApiError> {
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
  options: RequestOptions = {},
): Promise<T> {
  const requestVersion = sessionVersion;
  const requestToken = getAccessToken();
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

  if (!headers.has("Accept-Language"))
    headers.set("Accept-Language", activeLanguage());

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
    throw new ApiError(
      0,
      "network_error",
      (networkError as Error).message || "Network request failed",
    );
  }

  const assertCurrentSession = () => {
    if (!options.skipAuth && requestVersion !== sessionVersion)
      throw new ApiError(
        401,
        "session_changed",
        "Session changed during request",
      );
  };
  assertCurrentSession();

  // Handle unexpected 401: attempt single refresh & retry
  if (
    response.status === 401 &&
    !options.skipAuth &&
    endpoint !== REFRESH_PATH
  ) {
    // Another request may already have rotated the token while this response was slow.
    const newToken =
      getAccessToken() && getAccessToken() !== requestToken
        ? getAccessToken()
        : await refreshAccessToken(basePath);
    assertCurrentSession();
    if (newToken) {
      headers.set("Authorization", `Bearer ${newToken}`);
      try {
        response = await fetch(url, {
          ...options,
          headers,
          body,
        });
      } catch (networkError) {
        throw new ApiError(
          0,
          "network_error",
          (networkError as Error).message || "Network request failed on retry",
        );
      }
    } else {
      throw await parseErrorResponse(response);
    }
  }

  assertCurrentSession();
  if (!response.ok) {
    if (response.status === 401 && !options.skipAuth) clearTokens();
    throw await parseErrorResponse(response);
  }

  if (response.status === 204) {
    return undefined as unknown as T;
  }

  const contentType = response.headers.get("content-type");
  if (contentType && contentType.includes("application/json")) {
    const data = (await response.json()) as T;
    assertCurrentSession();
    return data;
  }

  const data = await response.text();
  assertCurrentSession();
  return data as unknown as T;
}

/**
 * Standard Query Key Convention for TanStack Query
 */
export const queryKeys = {
  auth: {
    me: ["auth", "me"] as const,
  },
  companies: {
    me: ["companies", "me"] as const,
  },
  jobs: {
    all: ["jobs"] as const,
    list: (filters: Record<string, unknown> = {}) =>
      ["jobs", "list", filters] as const,
    detail: (id: number | string) => ["jobs", "detail", String(id)] as const,
  },
  applications: {
    all: ["applications"] as const,
    my: ["applications", "my"] as const,
    forJob: (jobId: number | string) =>
      ["applications", "job", String(jobId)] as const,
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
          if (
            error instanceof ApiError &&
            error.status >= 400 &&
            error.status < 500
          ) {
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
