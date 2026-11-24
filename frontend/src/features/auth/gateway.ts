import { z } from "zod";
import {
  ApiError,
  apiClient,
  clearTokens,
  getAccessToken,
  getSessionVersion,
  getStoredRefreshToken,
  logoutSession,
  onAuthChange,
  refreshAccessToken,
  setTokens,
} from "../../api/client";

export type Credentials = { email: string; password: string };
export type AuthStatus = "loading" | "anonymous" | "authenticated";
export interface AuthGateway {
  register(data: Credentials): Promise<void>;
  verify(token: string): Promise<void>;
  login(data: Credentials): Promise<void>;
  // Login with 42 (BE-11): the backend's callback hands the pair to /oauth/callback.
  loginWithTokens(pair: TokenPair): void;
  logout(): Promise<void>;
  restore(): Promise<void>;
  getSessionVersion(): number;
  getStatus(): AuthStatus;
  subscribe(listener: () => void): () => void;
}
export class AuthError extends Error {
  status: number;
  payload: unknown;
  constructor(status: number, payload: unknown) {
    super("Authentication request failed");
    this.status = status;
    this.payload = payload;
  }
}
const pairSchema = z.object({
  access_token: z.string().min(1),
  refresh_token: z.string().min(1),
  token_type: z.literal("bearer"),
});
export type TokenPair = z.infer<typeof pairSchema>;
// The pair the 42 callback put after "#" in the address, or null when it is not a valid one.
export function parseTokenPair(value: unknown): TokenPair | null {
  const result = pairSchema.safeParse(value);
  return result.success ? result.data : null;
}

// Domain adapter only: FE-20 owns tokens, persistence, rotation and bearer requests.
export function createAuthGateway(): AuthGateway {
  let restoring = !getAccessToken() && Boolean(getStoredRefreshToken());
  let restoration: Promise<void> | undefined;
  const listeners = new Set<() => void>();
  const notify = () => listeners.forEach((listener) => listener());
  async function request(path: string, data?: unknown) {
    try {
      return await apiClient(`/auth/${path}`, {
        method: data === undefined ? "GET" : "POST",
        body: data,
        skipAuth: true,
        signal: AbortSignal.timeout(15_000),
        cache: "no-store",
        referrerPolicy: "no-referrer",
      });
    } catch (error) {
      if (error instanceof ApiError)
        throw new AuthError(error.status, {
          error: { code: error.code, detail: error.detail },
        });
      throw error;
    }
  }
  return {
    getStatus: () =>
      getAccessToken() ? "authenticated" : restoring ? "loading" : "anonymous",
    getSessionVersion,
    subscribe(listener) {
      listeners.add(listener);
      const unsubscribe = onAuthChange(() => {
        restoring = false;
        listener();
      });
      return () => {
        listeners.delete(listener);
        unsubscribe();
      };
    },
    restore() {
      if (!restoring) return Promise.resolve();
      restoration ??= refreshAccessToken()
        .then(() => {
          restoring = false;
          notify();
        })
        .finally(() => {
          restoration = undefined;
        });
      return restoration;
    },
    async register({ email, password }) {
      await request("register", { email, password });
    },
    async verify(token) {
      const result = z
        .object({ verified: z.literal(true) })
        .safeParse(await request(`verify?token=${encodeURIComponent(token)}`));
      if (!result.success) throw new Error("Invalid verification response");
    },
    async login({ email, password }) {
      restoring = false;
      clearTokens();
      const attempt = getSessionVersion();
      const pair = pairSchema.parse(
        await request("login", { email, password }),
      );
      if (attempt !== getSessionVersion()) return;
      setTokens({
        accessToken: pair.access_token,
        refreshToken: pair.refresh_token,
      });
    },
    loginWithTokens(pair) {
      // Stored exactly as after a password login: access token in memory, refresh token saved.
      restoring = false;
      clearTokens();
      setTokens({
        accessToken: pair.access_token,
        refreshToken: pair.refresh_token,
      });
    },
    async logout() {
      restoring = false;
      await logoutSession();
    },
  };
}
