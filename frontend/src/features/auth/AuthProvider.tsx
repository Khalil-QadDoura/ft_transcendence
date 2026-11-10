import {
  createContext,
  useCallback,
  useContext,
  useEffect,
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
    void client.restore();
  }, [client]);
  return (
    <AuthContext value={client}>
      <SessionContext value={status}>{children}</SessionContext>
    </AuthContext>
  );
}
export function useAuth() {
  return useContext(AuthContext);
}
