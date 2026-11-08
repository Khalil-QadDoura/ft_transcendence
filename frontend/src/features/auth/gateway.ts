import { z } from "zod";

export type Credentials = { email: string; password: string };
export type AuthStatus = "loading" | "anonymous" | "authenticated";
export interface AuthGateway {
  register(data: Credentials): Promise<void>;
  verify(token: string): Promise<void>;
  login(data: Credentials): Promise<void>;
  logout(): Promise<void>;
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

/** Auth-only HTTP bridge until FE-20 supplies the shared client. No persistence,
 * refresh/retry policy or general API wrapper: those belong to Ahmad's FE-20.
 * A reload requires login. Only a successful backend login establishes a session.
 */
export function createAuthGateway(): AuthGateway {
  let status: AuthStatus = "anonymous";
  let refresh: string | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let revision = 0;
  const listeners = new Set<() => void>();
  const clear = () => {
    revision++;
    refresh = undefined;
    clearTimeout(timer);
    status = "anonymous";
    listeners.forEach((listener) => listener());
  };
  async function request(path: string, data?: unknown) {
    const response = await fetch(`/api/auth/${path}`, {
      method: data === undefined ? "GET" : "POST",
      headers:
        data === undefined ? undefined : { "Content-Type": "application/json" },
      body: data === undefined ? undefined : JSON.stringify(data),
      signal: AbortSignal.timeout(15_000),
      cache: "no-store",
      referrerPolicy: "no-referrer",
    });
    const payload: unknown =
      response.status === 204 ? null : await response.json();
    if (!response.ok) throw new AuthError(response.status, payload);
    return payload;
  }
  return {
    getStatus: () => status,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
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
      const attempt = ++revision;
      const pair = pairSchema.parse(
        await request("login", { email, password }),
      );
      if (attempt !== revision) return;
      refresh = pair.refresh_token;
      clearTimeout(timer);
      // BE-03 access TTL is 15 minutes. FE-20 replaces this with refresh rotation.
      timer = setTimeout(clear, 15 * 60_000);
      status = "authenticated";
      listeners.forEach((listener) => listener());
    },
    async logout() {
      const token = refresh;
      clear(); // Never retain local authentication when revocation is offline.
      if (token) await request("logout", { refresh_token: token });
    },
  };
}
