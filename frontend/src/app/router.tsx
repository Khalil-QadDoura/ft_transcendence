import { useText } from "../i18n/useText";
import {
  ForgotPassword,
  ResetPassword,
  AccountSettings,
} from "../features/account/AccountPages";
import { LegalPage } from "../features/legal/LegalPage";
import { Link, type RouteObject } from "react-router-dom";
import { AuthForm, VerifyEmail } from "../features/auth/AuthScreens";
import { Layout } from "./Layout";
import { RequireSession, GuestOnly } from "./session";
import { Welcome } from "../features/home/Welcome";
import { ComponentPreview } from "../features/dev/ComponentPreview";
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
      ...pages([
        ["jobs", "routes.jobs"],
        ["jobs/:id", "routes.job"],
        ["users/:id", "routes.person"],
        ["game/rules", "routes.rules"],
        ["status", "routes.status"],
      ]),
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
      { path: "forgot-password", element: <ForgotPassword /> },
      { path: "reset-password", element: <ResetPassword /> },
      {
        element: <RequireSession />,
        children: [
          { path: "settings", element: <AccountSettings /> },
          ...pages([
            ["profile", "routes.profile"],
            ["friends", "routes.friends"],
            ["chat", "routes.chat"],
            ["chat/:id", "routes.conversation"],
            ["videos", "routes.videos"],
            ["employer/*", "routes.employer"],
            ["game", "routes.game"],
            ["game/rooms/:id", "routes.room"],
          ]),
        ],
      },
      { path: "*", element: <Missing /> },
    ],
  },
];
