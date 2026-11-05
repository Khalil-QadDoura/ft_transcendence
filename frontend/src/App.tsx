import { Component, lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Layout } from "./app/Layout";
import { useAuth } from "./app/state";
import { ErrorNotice, Loading } from "./components/ui";
import { Jobs, JobDetail, Applications } from "./features/jobs/Jobs";
import { AuthPage } from "./features/auth/Auth";
import {
  Friends,
  Profile,
  PublicProfile,
  Settings,
} from "./features/profile/Profile";
import { Employer, JobEditor, Applicants } from "./features/employer/Employer";
import { GameLobby, GameRoom, GameRules } from "./features/game/Game";
import { Legal, NotFound, Status } from "./features/info/Info";
const Chat = lazy(() =>
  import("./features/chat/Chat").then((m) => ({ default: m.Chat })),
);
const Videos = lazy(() =>
  import("./features/videos/Videos").then((m) => ({ default: m.Videos })),
);
function Guard({ children }: { children: ReactNode }) {
  const { signedIn, loading, error } = useAuth();
  const location = useLocation();
  if (!signedIn)
    return (
      <Navigate
        to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`}
        replace
      />
    );
  if (loading) return <Loading />;
  if (error) return <ErrorNotice error={error} />;
  return children;
}
class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <div className="empty">
        <h1>Something interrupted your workspace.</h1>
        <p>Your saved account data has not been changed.</p>
        <button
          className="button primary"
          onClick={() => window.location.reload()}
        >
          Reload workspace
        </button>
      </div>
    ) : (
      this.props.children
    );
  }
}
export default function App() {
  return (
    <Boundary>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/login" element={<AuthPage mode="login" />} />
          <Route path="/register" element={<AuthPage mode="register" />} />
          <Route path="/forgot-password" element={<AuthPage mode="forgot" />} />
          <Route path="/reset-password" element={<AuthPage mode="reset" />} />
          <Route path="/verify-email" element={<AuthPage mode="verify" />} />
          <Route element={<Layout />}>
            <Route index element={<Navigate to="/jobs" replace />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/jobs/:id" element={<JobDetail />} />
            <Route
              path="/applications"
              element={
                <Guard>
                  <Applications />
                </Guard>
              }
            />
            <Route
              path="/profile"
              element={
                <Guard>
                  <Profile />
                </Guard>
              }
            />
            <Route
              path="/users/:id"
              element={
                <Guard>
                  <PublicProfile />
                </Guard>
              }
            />
            <Route
              path="/friends"
              element={
                <Guard>
                  <Friends />
                </Guard>
              }
            />
            <Route
              path="/settings"
              element={
                <Guard>
                  <Settings />
                </Guard>
              }
            />
            <Route
              path="/videos"
              element={
                <Guard>
                  <Videos />
                </Guard>
              }
            />
            <Route
              path="/chat"
              element={
                <Guard>
                  <Chat />
                </Guard>
              }
            />
            <Route
              path="/chat/:id"
              element={
                <Guard>
                  <Chat />
                </Guard>
              }
            />
            <Route
              path="/employer"
              element={
                <Guard>
                  <Employer />
                </Guard>
              }
            />
            <Route
              path="/employer/jobs/new"
              element={
                <Guard>
                  <JobEditor />
                </Guard>
              }
            />
            <Route
              path="/employer/jobs/:id/edit"
              element={
                <Guard>
                  <JobEditor />
                </Guard>
              }
            />
            <Route
              path="/employer/jobs/:id/applications"
              element={
                <Guard>
                  <Applicants />
                </Guard>
              }
            />
            <Route
              path="/game"
              element={
                <Guard>
                  <GameLobby />
                </Guard>
              }
            />
            <Route
              path="/game/rooms/:id"
              element={
                <Guard>
                  <GameRoom />
                </Guard>
              }
            />
            <Route path="/game/rules" element={<GameRules />} />
            <Route path="/privacy" element={<Legal kind="privacy" />} />
            <Route path="/terms" element={<Legal kind="terms" />} />
            <Route path="/status" element={<Status />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
    </Boundary>
  );
}
