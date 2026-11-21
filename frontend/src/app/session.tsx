import { useText } from "../i18n/useText";
import { createContext, useContext } from "react";
import {
  Navigate,
  Outlet,
  useLocation,
  useSearchParams,
} from "react-router-dom";
// FE-04 supplies the verified session from FE-20. Never infer auth from a URL or local flag.
export const SessionContext = createContext<
  "loading" | "anonymous" | "authenticated"
>("anonymous");
export function safeNext(value: string | null): string {
  if (
    !value ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    /[\\\s]/.test(value)
  )
    return "/profile";
  const url = new URL(value, "https://wozu.invalid");
  const path = url.pathname.replace(/\/+$/, "");
  return [
    "/login",
    "/register",
    "/verify-email",
    "/forgot-password",
    "/reset-password",
    "/oauth/callback",
  ].includes(path)
    ? "/profile"
    : url.pathname + url.search + url.hash;
}
export function RequireSession() {
  const { t } = useText();
  const session = useContext(SessionContext);
  const { pathname, search, hash } = useLocation();
  if (session === "loading")
    return <p role="status">{t("session.checkingYourSession")}</p>;
  return session === "authenticated" ? (
    <Outlet />
  ) : (
    <Navigate
      replace
      to={`/login?next=${encodeURIComponent(pathname + search + hash)}`}
    />
  );
}
export function GuestOnly() {
  const { t } = useText();
  const session = useContext(SessionContext);
  const [params] = useSearchParams();
  if (session === "loading")
    return <p role="status">{t("session.checkingYourSession")}</p>;
  return session === "authenticated" ? (
    <Navigate replace to={safeNext(params.get("next"))} />
  ) : (
    <Outlet />
  );
}
