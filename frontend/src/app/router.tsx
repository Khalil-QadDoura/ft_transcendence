import { Link, type RouteObject } from "react-router-dom";
import { AuthForm, VerifyEmail } from "../features/auth/AuthScreens";
import { Layout } from "./Layout";
import { RequireSession, GuestOnly } from "./session";
import { Welcome } from "../features/home/Welcome";
import { ComponentPreview } from "../features/dev/ComponentPreview";
function ComingSoon({ title }: { title: string }) {
  return (
    <section className="empty-page">
      <span className="eyebrow">A SPACE FOR WHAT’S NEXT</span>
      <h1>{title}</h1>
      <p>This space is taking shape. Please check back soon.</p>
      <Link className="button" to="/">
        Back to WOZU <span aria-hidden="true">↗</span>
      </Link>
    </section>
  );
}
function Missing() {
  return (
    <section className="empty-page">
      <span className="eyebrow">404 / A SMALL DETOUR</span>
      <h1>
        A different
        <br />
        <em>direction.</em>
      </h1>
      <p>We couldn’t find that page. Your next chapter is still out there.</p>
      <Link className="button" to="/">
        Take me home <span aria-hidden="true">↗</span>
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
      ...pages([
        ["jobs", "Find your next chapter."],
        ["jobs/:id", "A closer look."],
        ["users/:id", "Meet the person."],
        ["game/rules", "How to play."],
        ["privacy", "Privacy Policy"],
        ["terms", "Terms of Service"],
        ["status", "Service status"],
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
      ...pages([
        ["forgot-password", "Let’s get you back in."],
        ["reset-password", "A fresh start."],
      ]),
      {
        element: <RequireSession />,
        children: pages([
          ["profile", "Your story."],
          ["friends", "Good company."],
          ["chat", "Start a conversation."],
          ["chat/:id", "Keep the conversation going."],
          ["videos", "More than a résumé."],
          ["employer/*", "Build your next team."],
          ["game", "Trust your instincts."],
          ["game/rooms/:id", "Who’s really human?"],
          ["settings", "Make yourself at home."],
        ]),
      },
      { path: "*", element: <Missing /> },
    ],
  },
];
