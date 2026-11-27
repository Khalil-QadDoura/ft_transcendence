import { EmployerJobs } from "../features/employer/EmployerJobs";
import { FriendsPage } from "../features/people/FriendsPage";
import { PublicProfile } from "../features/people/PublicProfile";
import { ProfilePage } from "../features/profile/ProfilePage";
import { CompanyPage } from "../features/companies/CompanyPage";
import { useText } from "../i18n/useText";
import {
  ForgotPassword,
  ResetPassword,
  AccountSettings,
} from "../features/account/AccountPages";
import { LegalPage } from "../features/legal/LegalPage";
import { Link, type RouteObject } from "react-router-dom";
import {
  AuthForm,
  OAuthCallback,
  VerifyEmail,
} from "../features/auth/AuthScreens";
import { Layout } from "./Layout";
import { RequireSession, GuestOnly } from "./session";
import { Welcome } from "../features/home/Welcome";
import { ComponentPreview } from "../features/dev/ComponentPreview";
import { MyApplicationsPage } from "../features/applications/MyApplicationsPage";
import { JobsPage } from "../features/jobs/JobsPage";
import { ConversationsPage } from "../features/conversations/ConversationsPage";
import { GameLobbyPage } from "../features/game/GameLobbyPage";
import { GameRoomPage } from "../features/game/GameRoomPage";
import { VideoResumePage } from "../features/media/VideoResumePage";
import { StatusPage } from "../features/status/StatusPage";
import { GameRulesPage } from "../features/game/rules/GameRulesPage";
import { GAME_RULES_PATH } from "../features/game/rules/paths";
function ComingSoon({ title }: { title: string }) {
  const { t } = useText();
  return (
    <section className="empty-page">
      <span className="eyebrow">{t("routes.aSpaceForWhatsNext")}</span>
      <h1>{t(title)}</h1>
      <p>{t("routes.thisSpaceIsTakingShapePleaseCheckBackSoon")}</p>
      <Link className="button" to="/">
        {t("routes.backToWozu")}
        <span aria-hidden="true">↗</span>
      </Link>
    </section>
  );
}
function Missing() {
  const { t } = useText();
  return (
    <section className="empty-page">
      <span className="eyebrow">{t("routes.404ASmallDetour")}</span>
      <h1>
        {t("routes.aDifferent")}
        <br />
        <em>{t("routes.direction")}</em>
      </h1>
      <p>{t("routes.weCouldntFindThatPageYourNextChapterIs")}</p>
      <Link className="button" to="/">
        {t("routes.takeMeHome")}
        <span aria-hidden="true">↗</span>
      </Link>
    </section>
  );
}
const pages = (entries: [string, string][]): RouteObject[] =>
  entries.map(([path, title]) => ({
    path,
    element: <ComingSoon title={title} />,
  }));
// Explicit route slots keep future domain PRs small. These are not completed feature pages.
export const routes: RouteObject[] = [
  ...(import.meta.env.DEV
    ? [{ path: "/dev/components", element: <ComponentPreview /> }]
    : []),
  {
    element: <Layout />,
    children: [
      { index: true, element: <Welcome /> },
      { path: "privacy", element: <LegalPage kind="privacy" /> },
      { path: "terms", element: <LegalPage kind="terms" /> },
      { path: "jobs", element: <JobsPage /> },
      // Public (INF-16): outside RequireSession, works for logged-out visitors.
      { path: "status", element: <StatusPage /> },
      // Public (FE-34): outside RequireSession, works for logged-out visitors.
      { path: GAME_RULES_PATH, element: <GameRulesPage /> },
      ...pages([["jobs/:id", "routes.job"]]),
      {
        element: <GuestOnly />,
        children: [
          { path: "login", element: <AuthForm key="login" mode="login" /> },
          {
            path: "register",
            element: <AuthForm key="register" mode="register" />,
          },
        ],
      },
      { path: "verify-email", element: <VerifyEmail /> },
      { path: "oauth/callback", element: <OAuthCallback /> },
      { path: "forgot-password", element: <ForgotPassword /> },
      { path: "reset-password", element: <ResetPassword /> },
      {
        element: <RequireSession />,
        children: [
          { path: "settings", element: <AccountSettings /> },
          { path: "profile", element: <ProfilePage /> },
          { path: "friends", element: <FriendsPage /> },
          { path: "company", element: <CompanyPage /> },
          { path: "users/:id", element: <PublicProfile /> },
          { path: "videos", element: <VideoResumePage /> },
          { path: "applications", element: <MyApplicationsPage /> },
          { path: "employer/jobs", element: <EmployerJobs /> },
          { path: "employer/jobs/new", element: <EmployerJobs /> },
          { path: "employer/jobs/:id/edit", element: <EmployerJobs /> },
          { path: "game", element: <GameLobbyPage /> },
          { path: "game/rooms/:id", element: <GameRoomPage /> },
          ...pages([
            ["employer/*", "routes.employer"],
          ]),
          { path: "chat", element: <ConversationsPage /> },
          { path: "chat/:id", element: <ConversationsPage /> },
        ],
      },
      { path: "*", element: <Missing /> },
    ],
  },
];
