import { apiClient, clearTokens } from "../../api/client";
const options = { signal: () => AbortSignal.timeout(15000) };
export const accountApi = {
  forgot: (email: string) =>
    apiClient("/auth/forgot-password", {
      method: "POST",
      body: { email },
      skipAuth: true,
      signal: options.signal(),
      referrerPolicy: "no-referrer",
      cache: "no-store",
    }),
  async reset(token: string, new_password: string) {
    await apiClient("/auth/reset-password", {
      method: "POST",
      body: { token, new_password },
      skipAuth: true,
      signal: options.signal(),
      referrerPolicy: "no-referrer",
      cache: "no-store",
    });
    clearTokens();
  },
  async change(current_password: string, new_password: string) {
    await apiClient("/auth/change-password", {
      method: "POST",
      body: { current_password, new_password },
      signal: options.signal(),
    });
    clearTokens();
  },
  async remove() {
    await apiClient("/users/me", {
      method: "DELETE",
      signal: options.signal(),
    });
    clearTokens();
  },
};
