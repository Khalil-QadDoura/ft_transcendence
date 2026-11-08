import { useContext, useEffect, useRef, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { LogoutButton } from "../features/auth/AuthScreens";
import { SessionContext } from "./session";
export function Layout({
  languageSlot,
  unreadSlot,
}: {
  languageSlot?: ReactNode;
  unreadSlot?: ReactNode;
}) {
  const { pathname } = useLocation();
  const previousPath = useRef(pathname);
  const main = useRef<HTMLElement>(null);
  const signedIn = useContext(SessionContext) === "authenticated";
  useEffect(() => {
    document.title = `${document.querySelector("h1")?.textContent || "Find your people"} · WOZU`;
    if (previousPath.current !== pathname) {
      window.scrollTo(0, 0);
      main.current?.focus({ preventScroll: true });
    }
    previousPath.current = pathname;
  }, [pathname]);
  return (
    <div className="site-frame">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <Link className="wordmark" to="/" aria-label="WOZU home">
          wozu<span>✳</span>
        </Link>
        <nav aria-label="Main navigation">
          {[
            ["/jobs", "Discover"],
            ["/friends", "Connect"],
            ["/game", "Play"],
          ].map(([to, label]) => (
            <NavLink key={to} to={to}>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="header-tools">
          <span className="language-slot">
            {languageSlot ?? (
              <span lang="en" aria-label="Current language: English">
                EN
              </span>
            )}
          </span>
          {unreadSlot}
          {signedIn && <LogoutButton />}
          <Link className="button small" to={signedIn ? "/profile" : "/login"}>
            {signedIn ? "My profile" : "Sign in"}{" "}
            <span aria-hidden="true">↗</span>
          </Link>
        </div>
      </header>
      <main id="main" ref={main} tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="site-footer">
        <Link className="wordmark" to="/" aria-label="WOZU home">
          wozu<span>✳</span>
        </Link>
        <p>A little more human.</p>
        <nav aria-label="Legal and service information">
          <Link to="/privacy">Privacy Policy</Link>
          <Link to="/terms">Terms of Service</Link>
          <Link to="/status">Status</Link>
        </nav>
        <small>© {new Date().getFullYear()} WOZU</small>
      </footer>
    </div>
  );
}
