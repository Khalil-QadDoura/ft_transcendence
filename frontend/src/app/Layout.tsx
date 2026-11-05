import { useEffect, useState } from "react";
import {
  Link,
  NavLink,
  Outlet,
  useLocation,
  useNavigate,
} from "react-router-dom";
import {
  ArrowUpRight,
  BriefcaseBusiness,
  ChevronDown,
  CircleHelp,
  Compass,
  FileText,
  Gamepad2,
  Globe2,
  LogOut,
  Menu,
  MessageCircle,
  Settings2,
  Sparkles,
  UserRound,
  UsersRound,
  Video,
  X,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api, logout } from "../api/client";
import { useAuth } from "./state";
import { Avatar, ErrorNotice } from "../components/ui";
import { useLiveEvents } from "./live";

export function Wordmark() {
  return (
    <Link className="wordmark" to="/jobs" aria-label="WOZU home">
      <span className="brand-symbol">
        w<span>•</span>
      </span>
      wozu<span className="brand-dot">.</span>
    </Link>
  );
}
export function Layout() {
  const { user, signedIn } = useAuth();
  const { t, i18n } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [logoutError, setLogoutError] = useState<unknown>(null);
  const unread = useQuery({
    queryKey: ["unread"],
    queryFn: () => api<{ total_unread: number }>("/conversations/unread"),
    enabled: signedIn,
    refetchInterval: 30000,
  });
  const connection = useLiveEvents(signedIn);
  useEffect(() => {
    setOpen(false);
    window.scrollTo({ top: 0 });
    document.title = `WOZU · ${location.pathname.split("/")[1] || "Discover"}`;
  }, [location.pathname]);
  const nav = [
    { path: "/jobs", label: "Discover jobs", icon: Compass },
    { path: "/applications", label: "My applications", icon: FileText },
    { path: "/videos", label: "Video studio", icon: Video },
    { path: "/chat", label: "Messages", icon: MessageCircle },
    { path: "/friends", label: "My network", icon: UsersRound },
    { path: "/game", label: "Turing Duel", icon: Gamepad2 },
  ];
  return (
    <div className="workspace">
      <a className="skip-link" href="#main-content">
        {t("Skip to content")}
      </a>
      {open && (
        <button
          className="sidebar-backdrop"
          aria-label={t("Close menu")}
          onClick={() => setOpen(false)}
        />
      )}
      <aside className={`sidebar ${open ? "is-open" : ""}`}>
        <div className="sidebar-brand">
          <Wordmark />
          <button
            className="icon-button mobile-only"
            aria-label={t("Close menu")}
            onClick={() => setOpen(false)}
          >
            <X size={20} />
          </button>
        </div>
        <span className="sidebar-caption">{t("YOUR NEXT CHAPTER")}</span>
        <nav aria-label={t("Main navigation")}>
          {nav.map(({ path, label, icon: Icon }) => (
            <NavLink
              key={path}
              to={path}
              className={({ isActive }) =>
                `nav-link ${isActive ? "active" : ""}`
              }
            >
              <Icon size={20} />
              <span>{t(label)}</span>
              {path === "/chat" && !!unread.data?.total_unread && (
                <span className="nav-count">{unread.data.total_unread}</span>
              )}
              {path === "/game" && <span className="nav-new">PLAY</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-divider" />
        <span className="sidebar-caption">{t("YOUR WORKSPACE")}</span>
        <NavLink to="/employer" className="nav-link">
          <BriefcaseBusiness size={20} />
          {t("Employer studio")}
        </NavLink>
        <NavLink to="/profile" className="nav-link">
          <UserRound size={20} />
          {t("My profile")}
        </NavLink>
        <div className="sidebar-bottom">
          <div className="sidebar-promo">
            <span className="little-spark">
              <Sparkles size={20} />
            </span>
            <h3>{t("More than a résumé.")}</h3>
            <p>{t("Let your personality open the next door.")}</p>
            <Link to="/videos">
              {t("Create your intro")}
              <ArrowUpRight size={17} />
            </Link>
          </div>
          <NavLink className="nav-link" to="/settings">
            <Settings2 size={19} />
            {t("Settings")}
          </NavLink>
          <NavLink className="nav-link" to="/status">
            <CircleHelp size={19} />
            {t("System status")}
          </NavLink>
          <div className="sidebar-account">
            <Avatar
              name={
                user?.first_name
                  ? `${user.first_name} ${user.last_name || ""}`
                  : "You"
              }
            />
            <div>
              <strong>{user?.first_name || t("Your next chapter")}</strong>
              <span>{user?.position || t("Make it happen")}</span>
            </div>
            {signedIn && (
              <button
                className="icon-button"
                aria-label={t("Sign out")}
                onClick={() => {
                  void logout()
                    .then(() => navigate("/login"))
                    .catch(setLogoutError);
                }}
              >
                <LogOut size={17} />
              </button>
            )}
          </div>
        </div>
      </aside>
      <div className="workspace-main">
        <header className="topbar">
          <div className="topbar-left">
            <button
              className="icon-button mobile-only"
              aria-label={t("Open menu")}
              onClick={() => setOpen(true)}
            >
              <Menu size={22} />
            </button>
            <span className="topbar-breadcrumb">
              {t("Workspace")}
              <span>/</span>
              <strong>
                {t(
                  nav.find((x) => location.pathname.startsWith(x.path))
                    ?.label || "Your space",
                )}
              </strong>
            </span>
          </div>
          <div className="topbar-actions">
            {signedIn && (
              <span className={`connection ${connection}`}>
                <i />
                {t(connection === "connected" ? "Connected" : "Reconnecting")}
              </span>
            )}
            <label className="language-picker">
              <Globe2 size={17} />
              <select
                aria-label={t("Language")}
                value={i18n.language}
                onChange={(e) => void i18n.changeLanguage(e.target.value)}
              >
                <option value="en">English</option>
                <option value="ar">العربية</option>
                <option value="az">Azərbaycanca</option>
                <option value="tr">Türkçe</option>
                <option value="ru">Русский</option>
              </select>
              <ChevronDown size={12} />
            </label>
            {signedIn ? (
              <Link to="/profile" aria-label={t("My profile")}>
                <Avatar name={user?.first_name || "You"} size="small" />
              </Link>
            ) : (
              <Link className="button primary small" to="/login">
                {t("Sign in")}
                <ArrowUpRight size={15} />
              </Link>
            )}
          </div>
        </header>
        <main id="main-content" className="main-content">
          <ErrorNotice error={logoutError} />
          <Outlet />
        </main>
        <footer className="footer">
          <span>
            © {new Date().getFullYear()} WOZU{" "}
            <span className="footer-tag">{t("A little more human.")}</span>
          </span>
          <div>
            <Link to="/privacy">{t("Privacy")}</Link>
            <Link to="/terms">{t("Terms")}</Link>
            <Link to="/status">
              {t("Status")}
              <span className="status-dot" />
            </Link>
          </div>
        </footer>
      </div>
    </div>
  );
}
