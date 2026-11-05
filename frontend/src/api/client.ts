import type { components } from "./schema";
export type Schema = components["schemas"];
export type User = Schema["UserOut"];
export type Job = Schema["JobOut"];
export type Company = Schema["CompanyOut"];
export type Conversation = Schema["ConversationOut"];
export type Message = Schema["app__conversations__schemas__MessageOut"];
export type Application = Schema["ApplicationOut"];
export type Tokens = Schema["TokenPairResponse"];
export const backendMode = import.meta.env.VITE_BACKEND_MODE || "reference";
const base = (import.meta.env.VITE_API_BASE || "/api").replace(/\/$/, "");
const key = "wozu.session.v1";
let tokens: Tokens | null = null;
try {
  tokens = JSON.parse(sessionStorage.getItem(key) || "null") as Tokens | null;
} catch {
  /* invalid stored session */
}
let refreshing: Promise<Tokens> | null = null;
let epoch = 0;
export function setTokens(value: Tokens | null) {
  epoch++;
  tokens = value;
  if (value) sessionStorage.setItem(key, JSON.stringify(value));
  else {
    sessionStorage.removeItem(key);
    sessionStorage.removeItem("wozu.room");
    sessionStorage.removeItem("wozu.queued");
  }
  window.dispatchEvent(new Event("wozu:session"));
}
export const hasSession = () => !!tokens?.refresh_token;
export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(
      typeof detail === "string"
        ? detail
        : typeof detail === "object" && detail && "code" in detail
          ? String(detail.code).replaceAll("_", " ")
          : `Request failed (${status})`,
    );
    this.status = status;
    this.detail = detail;
  }
}
export function safeNext(next: string | null) {
  return next?.startsWith("/") && !next.startsWith("//") && !next.includes("\\")
    ? next
    : "/jobs";
}
async function decode(response: Response) {
  if (response.status === 204) return undefined;
  const data = await response.json().catch(() => null);
  if (!response.ok)
    throw new ApiError(
      response.status,
      data?.error?.detail ?? data?.detail ?? response.statusText,
    );
  return data;
}
export async function refreshSession(): Promise<Tokens> {
  if (refreshing) return refreshing;
  const refreshToken = tokens?.refresh_token;
  const currentEpoch = epoch;
  if (!refreshToken) throw new ApiError(401, "Please sign in to continue.");
  refreshing = (async () => {
    try {
      const response = await fetch(`${base}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
        signal: AbortSignal.timeout(15000),
      });
      const result = (await decode(response)) as Tokens;
      if (epoch !== currentEpoch)
        throw new ApiError(401, "Session changed. Please sign in again.");
      setTokens(result);
      return result;
    } catch (error) {
      if (
        epoch === currentEpoch &&
        error instanceof ApiError &&
        error.status === 401
      )
        setTokens(null);
      throw error;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}
export async function accessToken(): Promise<string | undefined> {
  if (!tokens) return undefined;
  let expiry = 0;
  try {
    expiry =
      (
        JSON.parse(
          atob(
            tokens.access_token
              .split(".")[1]
              .replaceAll("-", "+")
              .replaceAll("_", "/"),
          ),
        ) as { exp: number }
      ).exp * 1000;
  } catch {
    /* server will validate token */
  }
  if (expiry && expiry < Date.now() + 60000) await refreshSession();
  return tokens?.access_token;
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
  retry = true,
): Promise<T> {
  const publicAuth =
    /^\/auth\/(login|register|refresh|logout|verify|forgot-password|reset-password)(\?|$)/.test(
      path,
    );
  const token = publicAuth ? tokens?.access_token : await accessToken();
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      ...options,
      signal: options.signal ?? AbortSignal.timeout(20000),
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        "Accept-Language": localStorage.getItem("wozu.language") || "en",
        ...options.headers,
      },
    });
  } catch {
    throw new ApiError(
      0,
      "We could not reach the server. Check your connection and try again.",
    );
  }
  if (
    response.status === 401 &&
    tokens?.refresh_token &&
    retry &&
    !publicAuth
  ) {
    await refreshSession();
    return api<T>(path, options, false);
  }
  return decode(response) as Promise<T>;
}
export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, {
    method: "POST",
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
export const patch = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
export const remove = (path: string) => api<void>(path, { method: "DELETE" });
export async function logout() {
  const refresh_token = tokens?.refresh_token;
  try {
    if (refresh_token) await post("/auth/logout", { refresh_token });
  } finally {
    setTokens(null);
  }
}
export function query(
  params: Record<string, string | number | undefined | null>,
) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params))
    if (value !== undefined && value !== null && value !== "")
      search.set(key, String(value));
  return search.toString();
}
export function uploadFile(
  url: string,
  file: File,
  progress: (percent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.timeout = 120000;
    xhr.setRequestHeader("Content-Type", file.type);
    xhr.upload.onprogress = (e) =>
      e.lengthComputable && progress(Math.round((e.loaded / e.total) * 100));
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(
            new Error(
              "Upload failed. Please request a fresh upload link and retry.",
            ),
          );
    xhr.onerror = () =>
      reject(
        new Error(
          "Upload connection failed. Storage must be reachable from your browser.",
        ),
      );
    xhr.ontimeout = () =>
      reject(new Error("Upload timed out. Please try again."));
    xhr.send(file);
  });
}
