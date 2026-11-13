import copy from "./copy.en.json";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
  type PropsWithChildren,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { SessionContext } from "../../app/session";
import { createAuthGateway, type AuthGateway } from "./gateway";

const gateway = createAuthGateway();
export const AuthContext = createContext<AuthGateway>(gateway);
export function AuthProvider({
  children,
  client = gateway,
}: PropsWithChildren<{ client?: AuthGateway }>) {
  const queries = useQueryClient();
  const [retry, setRetry] = useState(0);
  const [restoreFailed, setRestoreFailed] = useState(false);
  const subscribe = useCallback(
    (listener: () => void) => {
      let version = client.getSessionVersion();
      return client.subscribe(() => {
        const next = client.getSessionVersion();
        if (next !== version) {
          // Clear private queries before the new session reaches route consumers.
          queries.clear();
          version = next;
        }
        listener();
      });
    },
    [client, queries],
  );
  const status = useSyncExternalStore(subscribe, client.getStatus);
  useEffect(() => {
    let active = true;
    void client.restore().then(
      () => {
        if (active) setRestoreFailed(false);
      },
      () => {
        if (active) setRestoreFailed(true);
      },
    );
    return () => {
      active = false;
    };
  }, [client, retry]);
  return (
    <AuthContext value={client}>
      <SessionContext value={status}>
        {restoreFailed && status === "loading" && (
          <div
            role="alert"
            className="mx-auto my-4 max-w-xl rounded-lg border border-border bg-surface p-4 text-ink"
          >
            <p>{copy.yourSessionCouldNotBeRestoredRightNowYourSaved}</p>
            <button
              type="button"
              className="mt-2 underline"
              onClick={() => {
                setRestoreFailed(false);
                setRetry((value) => value + 1);
              }}
            >
              {copy.tryAgain}
            </button>
          </div>
        )}
        {children}
      </SessionContext>
    </AuthContext>
  );
}
export function useAuth() {
  return useContext(AuthContext);
}
