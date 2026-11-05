import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, hasSession, type User } from "../api/client";
const AuthContext = createContext<{
  user?: User;
  loading: boolean;
  signedIn: boolean;
  error: unknown;
}>({ loading: true, signedIn: false, error: null });
export function AuthProvider({ children }: { children: ReactNode }) {
  const [signedIn, setSignedIn] = useState(hasSession);
  const client = useQueryClient();
  useEffect(() => {
    const onSession = () => {
      const active = hasSession();
      setSignedIn(active);
      if (!active) client.clear();
      else void client.invalidateQueries({ queryKey: ["me"] });
    };
    window.addEventListener("wozu:session", onSession);
    return () => window.removeEventListener("wozu:session", onSession);
  }, [client]);
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<User>("/users/me"),
    enabled: signedIn,
    retry: false,
  });
  return (
    <AuthContext.Provider
      value={{
        user: me.data,
        signedIn,
        loading: signedIn && me.isPending,
        error: me.error,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
export const useAuth = () => useContext(AuthContext);
export function useSavedJobs() {
  const { user } = useAuth();
  const key = `wozu.saved.${user?.id ?? "guest"}`;
  const read = () => {
    try {
      return JSON.parse(localStorage.getItem(key) || "[]") as number[];
    } catch {
      return [];
    }
  };
  const [saved, setSaved] = useState<number[]>(read);
  useEffect(() => {
    try {
      setSaved(JSON.parse(localStorage.getItem(key) || "[]") as number[]);
    } catch {
      setSaved([]);
    }
  }, [key]);
  const toggle = (id: number) =>
    setSaved((prev) => {
      const next = prev.includes(id)
        ? prev.filter((x) => x !== id)
        : [...prev, id];
      localStorage.setItem(key, JSON.stringify(next));
      return next;
    });
  return { saved, toggle };
}
