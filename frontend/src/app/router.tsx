import { LegalPage } from "../features/legal/LegalPage";
import { Link, type RouteObject } from "react-router-dom";
import { Layout } from "./Layout";
import { RequireSession, GuestOnly } from "./session";
import { Welcome } from "../features/home/Welcome";
import { ComponentPreview } from "../features/dev/ComponentPreview";
import { JobsPage } from "../features/jobs/JobsPage";
import { JobDetailPage } from "../features/jobs/JobDetailPage";
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
      { path: "privacy", element: <LegalPage kind="privacy" /> },
      { path: "terms", element: <LegalPage kind="terms" /> },
      { path: "jobs", element: <JobsPage /> },
      { path: "jobs/:id", element: <JobDetailPage /> },
      ...pages([
        ["users/:id", "Meet the person."],
        ["game/rules", "How to play."],
        ["status", "Service status"],
      ]),
      {
        element: <GuestOnly />,
        children: pages([
          ["login", "Welcome back."],
          ["register", "Make your introduction."],
        ]),
      },
      ...pages([
        ["verify-email", "Check your inbox."],
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
