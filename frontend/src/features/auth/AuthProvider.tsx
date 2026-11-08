import {
  createContext,
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
  const status = useSyncExternalStore(client.subscribe, client.getStatus);
  const queries = useQueryClient();
  useEffect(() => {
    queries.clear();
  }, [status, queries]);
  return (
    <AuthContext value={client}>
      <SessionContext value={status}>{children}</SessionContext>
    </AuthContext>
  );
}
export function useAuth() {
  return useContext(AuthContext);
}
