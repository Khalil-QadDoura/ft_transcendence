import { useTranslation } from "react-i18next";
import { LanguageSwitcher } from "../i18n/LanguageSwitcher";
import { formatNumber } from "../i18n";
import { useContext, useEffect, useRef, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { LogoutButton } from "../features/auth/AuthScreens";
import { SessionContext } from "./session";
import { GAME_RULES_PATH } from "../features/game/rules/paths";
export function Layout({
  languageSlot,
  unreadSlot,
}: {
  languageSlot?: ReactNode;
  unreadSlot?: ReactNode;
}) {
  const { t, i18n } = useTranslation();
  const { pathname } = useLocation();
  const previousPath = useRef(pathname);
  const main = useRef<HTMLElement>(null);
  const signedIn = useContext(SessionContext) === "authenticated";
  useEffect(() => {
    const heading = main.current?.querySelector("h1")?.cloneNode(true) as
      HTMLElement | undefined;
    // A visual line break separates words even though textContent omits it.
    heading
      ?.querySelectorAll("br")
      .forEach((lineBreak) => lineBreak.replaceWith(" "));
    const title = heading?.textContent?.replace(/\s+/g, " ").trim();
    document.title = `${title || t("tagline")} · WOZU`;
    if (previousPath.current !== pathname) {
      window.scrollTo(0, 0);
      main.current?.focus({ preventScroll: true });
    }
    previousPath.current = pathname;
  }, [pathname, i18n.resolvedLanguage, t]);
  return (
    <div className="site-frame">
      <a className="skip-link" href="#main">
        {t("skip")}
      </a>
      <header className="site-header">
        <Link className="wordmark" to="/" aria-label={t("home")}>
          wozu<span>✳</span>
        </Link>
        <nav aria-label={t("navigation")}>
          {[
            ["/jobs", t("discover")],
            ["/friends", t("connect")],
            ["/game", t("play")],
          ].map(([to, label]) => (
            <NavLink key={to} to={to}>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="header-tools">
          <span className="language-slot">
            {languageSlot ?? <LanguageSwitcher />}
          </span>
          {unreadSlot}
          {signedIn && <LogoutButton />}
          <Link className="button small" to={signedIn ? "/profile" : "/login"}>
            {signedIn ? t("profile") : t("signIn")}{" "}
            <span className="directional-icon" aria-hidden="true">
              ↗
            </span>
          </Link>
        </div>
      </header>
      <main id="main" ref={main} tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="site-footer">
        <Link className="wordmark" to="/" aria-label={t("home")}>
          wozu<span>✳</span>
        </Link>
        <p>{t("tagline")}</p>
        <nav aria-label={t("legalNavigation")}>
          <Link to="/privacy">{t("privacy")}</Link>
          <Link to="/terms">{t("terms")}</Link>
          <Link to={GAME_RULES_PATH}>{t("gameRules")}</Link>
          <Link to="/status">{t("status")}</Link>
        </nav>
        <small>
          © {formatNumber(new Date().getFullYear(), { useGrouping: false })}{" "}
          WOZU
        </small>
      </footer>
    </div>
  );
}
