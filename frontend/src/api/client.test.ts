import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  apiClient,
  refreshAccessToken,
  ApiError,
  setTokens,
  clearTokens,
  getAccessToken,
  getStoredRefreshToken,
  setStoredRefreshToken,
  createQueryClientConfig,
  queryKeys,
  WAF_BLOCKED_CODE,
} from "./client";
import i18next from "../i18n";
import en from "../i18n/en/common.json";
import ru from "../i18n/ru/common.json";

describe("FE-20 API Client & Token Management", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    clearTokens();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    clearTokens();
    globalThis.fetch = originalFetch;
  });

  it.each([429, 503])(
    "keeps credentials when refresh returns %s and retries later",
    async (status) => {
      vi.useFakeTimers();
      try {
        setTokens({ accessToken: "existing", refreshToken: "keep-me" });
        globalThis.fetch = vi
          .fn()
          .mockResolvedValueOnce(new Response("{}", { status }))
          .mockResolvedValueOnce(
            new Response(
              JSON.stringify({
                access_token: "renewed",
                refresh_token: "rotated",
              }),
              { headers: { "Content-Type": "application/json" } },
            ),
          );
        await expect(refreshAccessToken()).rejects.toMatchObject({ status });
        expect(getAccessToken()).toBe("existing");
        expect(getStoredRefreshToken()).toBe("keep-me");
        await vi.advanceTimersByTimeAsync(30_000);
        expect(getAccessToken()).toBe("renewed");
        expect(getStoredRefreshToken()).toBe("rotated");
      } finally {
        clearTokens();
        vi.useRealTimers();
      }
    },
  );

  it("keeps credentials offline, but logout cancels the scheduled retry", async () => {
    vi.useFakeTimers();
    try {
      setTokens({ accessToken: "existing", refreshToken: "keep-me" });
      globalThis.fetch = vi.fn().mockRejectedValue(new TypeError("offline"));
      await expect(refreshAccessToken()).rejects.toMatchObject({ status: 0 });
      expect(getStoredRefreshToken()).toBe("keep-me");
      clearTokens();
      await vi.advanceTimersByTimeAsync(60_000);
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(getStoredRefreshToken()).toBeNull();
    } finally {
      clearTokens();
      vi.useRealTimers();
    }
  });

  describe("Token Storage & In-Memory Model", () => {
    it("keeps access token in-memory and refresh token in localStorage", () => {
      setTokens({
        accessToken: "test_access_token",
        refreshToken: "test_refresh_token",
      });

      expect(getAccessToken()).toBe("test_access_token");
      expect(getStoredRefreshToken()).toBe("test_refresh_token");
      expect(localStorage.getItem("wozu_refresh_token")).toBe(
        "test_refresh_token",
      );
    });

    it("clears both tokens and stops pending refresh on clearTokens", () => {
      setTokens({
        accessToken: "access_123",
        refreshToken: "refresh_123",
      });

      clearTokens();

      expect(getAccessToken()).toBeNull();
      expect(getStoredRefreshToken()).toBeNull();
      expect(localStorage.getItem("wozu_refresh_token")).toBeNull();
    });

    it("gracefully survives localStorage exceptions (e.g. strict sandbox)", () => {
      vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
        throw new Error("QuotaExceeded or SecurityError");
      });

      expect(() => setStoredRefreshToken("fail_token")).not.toThrow();
    });
  });

  describe("Proactive Refresh Scheduling", () => {
    it("schedules proactive refresh ~1 minute before 15-minute expiry", () => {
      vi.useFakeTimers();

      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          access_token: "new_proactive_token",
          refresh_token: "new_refresh_token",
        }),
      });
      globalThis.fetch = fetchMock;

      // 15 minutes lifetime = 900,000 ms. Proactive refresh should trigger at 900,000 - 60,000 = 840,000 ms (14 mins)
      setTokens({
        accessToken: "old_token",
        refreshToken: "valid_refresh",
        expiresInSeconds: 900,
      });

      // Advance by 13 minutes (780,000 ms) -> refresh should NOT have occurred yet
      vi.advanceTimersByTime(13 * 60 * 1000);
      expect(fetchMock).not.toHaveBeenCalled();

      // Advance by another 1 minute and 1 second (total 14m 1s) -> proactive refresh triggers
      vi.advanceTimersByTime(61 * 1000);
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/auth/refresh",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ refresh_token: "valid_refresh" }),
        }),
      );

      vi.useRealTimers();
    });
  });

  describe("Request Authorization & Headers", () => {
    it("attaches Authorization: Bearer when access token is present", async () => {
      setTokens({ accessToken: "secret_bearer_token" });

      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ message: "success" }),
      });
      globalThis.fetch = fetchMock;

      const result = await apiClient<{ message: string }>("/users/me");

      expect(result).toEqual({ message: "success" });
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/users/me",
        expect.objectContaining({
          headers: expect.any(Headers),
        }),
      );

      const calledHeaders = fetchMock.mock.calls[0][1].headers as Headers;
      expect(calledHeaders.get("Authorization")).toBe(
        "Bearer secret_bearer_token",
      );
      expect(calledHeaders.get("Accept")).toBe("application/json");
    });

    it("skips Authorization header when skipAuth is true", async () => {
      setTokens({ accessToken: "secret_bearer_token" });

      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ status: "public" }),
      });
      globalThis.fetch = fetchMock;

      await apiClient("/health", { skipAuth: true });

      const calledHeaders = fetchMock.mock.calls[0][1].headers as Headers;
      expect(calledHeaders.get("Authorization")).toBeNull();
    });
  });

  describe("Typed Error Handling & Apply Guard", () => {
    it("parses standard contract error body {'error': {'code', 'detail'}}", async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        statusText: "Unprocessable Entity",
        json: async () => ({
          error: {
            code: "422",
            detail: "body → email: invalid email format",
          },
        }),
      });

      await expect(apiClient("/auth/register")).rejects.toThrowError(
        "body → email: invalid email format",
      );

      try {
        await apiClient("/auth/register");
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError);
        const apiErr = err as ApiError;
        expect(apiErr.status).toBe(422);
        expect(apiErr.code).toBe("422");
        expect(apiErr.detail).toBe("body → email: invalid email format");
      }
    });

    it("parses apply guard detail object with code and next_step", async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        statusText: "Unprocessable Entity",
        json: async () => ({
          error: {
            code: "422",
            detail: {
              code: "no_video",
              next_step: "video",
            },
          },
        }),
      });

      try {
        await apiClient("/jobs/1/apply");
        expect.unreachable();
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError);
        const apiErr = err as ApiError;
        expect(apiErr.status).toBe(422);
        expect(apiErr.code).toBe("422");
        expect(apiErr.nextStep).toBe("video");
        expect(apiErr.detail).toEqual({
          code: "no_video",
          next_step: "video",
        });
      }
    });

    // INF-11: the WAF answers with nginx's HTML page, the API with JSON.
    it("turns the WAF's HTML 403 into a translated message", async () => {
      const wafPage =
        "<html><head><title>403 Forbidden</title></head><body></body></html>";
      globalThis.fetch = vi.fn().mockImplementation(
        async () =>
          new Response(wafPage, {
            status: 403,
            statusText: "Forbidden",
            headers: { "Content-Type": "text/html" },
          }),
      );
      try {
        await i18next.changeLanguage("ru");
        const err = await apiClient("/conversations/1/messages", {
          method: "POST",
          body: { content: "I'm free at 10 or 11" },
        }).catch((e: unknown) => e);
        expect(err).toBeInstanceOf(ApiError);
        expect(err).toMatchObject({
          status: 403,
          code: WAF_BLOCKED_CODE,
          message: ru.wafBlocked,
        });
        await i18next.changeLanguage("en");
        await expect(apiClient("/users/me")).rejects.toThrowError(
          en.wafBlocked,
        );
      } finally {
        await i18next.changeLanguage("en");
      }
    });

    it("keeps the API's own JSON 403", async () => {
      globalThis.fetch = vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({ error: { code: "403", detail: "Not your job" } }),
            { status: 403, headers: { "Content-Type": "application/json" } },
          ),
        );
      await expect(apiClient("/jobs/1")).rejects.toMatchObject({
        status: 403,
        code: "403",
        message: "Not your job",
      });
    });
  });

  describe("Unexpected 401: Refresh & Single Retry", () => {
    it("retries once on 401 after successfully refreshing the access token", async () => {
      setTokens({
        accessToken: "expired_token",
        refreshToken: "valid_refresh_token",
      });

      let callCount = 0;
      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        if (url === "/api/auth/refresh") {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              access_token: "refreshed_access_token",
              refresh_token: "new_refresh_token",
            }),
          };
        }

        callCount++;
        if (callCount === 1) {
          // First attempt fails with 401
          return {
            ok: false,
            status: 401,
            statusText: "Unauthorized",
            json: async () => ({
              error: { code: "401", detail: "Token expired" },
            }),
          };
        }

        // Retry succeeds
        return {
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ data: "authorized content" }),
        };
      });

      const data = await apiClient<{ data: string }>("/protected/resource");

      expect(data).toEqual({ data: "authorized content" });
      expect(callCount).toBe(2);
      expect(getAccessToken()).toBe("refreshed_access_token");
    });

    it("logs out and clears tokens if 401 refresh fails", async () => {
      setTokens({
        accessToken: "invalid_token",
        refreshToken: "revoked_refresh_token",
      });

      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        if (url === "/api/auth/refresh") {
          return {
            ok: false,
            status: 401,
            statusText: "Unauthorized",
            json: async () => ({
              error: { code: "401", detail: "Refresh token revoked" },
            }),
          };
        }

        return {
          ok: false,
          status: 401,
          statusText: "Unauthorized",
          json: async () => ({
            error: { code: "401", detail: "Unauthorized" },
          }),
        };
      });

      await expect(apiClient("/protected/resource")).rejects.toThrow();
      expect(getAccessToken()).toBeNull();
      expect(getStoredRefreshToken()).toBeNull();
    });
  });

  describe("TanStack Query Configuration", () => {
    it("disables retries for 4xx ApiErrors", () => {
      const config = createQueryClientConfig();
      const retryFn = config.defaultOptions?.queries?.retry as (
        failureCount: number,
        error: unknown,
      ) => boolean;

      expect(retryFn).toBeDefined();

      const notFoundError = new ApiError(404, "404", "Not Found");
      const validationError = new ApiError(422, "422", "Invalid input");
      const serverError = new ApiError(500, "500", "Server Error");
      const networkError = new Error("Network timeout");

      // 4xx client errors should never be retried
      expect(retryFn(0, notFoundError)).toBe(false);
      expect(retryFn(0, validationError)).toBe(false);

      // 5xx and network errors can be retried up to limit
      expect(retryFn(0, serverError)).toBe(true);
      expect(retryFn(1, serverError)).toBe(true);
      expect(retryFn(2, serverError)).toBe(false);

      expect(retryFn(0, networkError)).toBe(true);
    });

    it("defines consistent queryKeys conventions", () => {
      expect(queryKeys.auth.me).toEqual(["auth", "me"]);
      expect(queryKeys.jobs.detail(42)).toEqual(["jobs", "detail", "42"]);
      expect(queryKeys.applications.forJob(99)).toEqual([
        "applications",
        "job",
        "99",
      ]);
    });
  });
});
