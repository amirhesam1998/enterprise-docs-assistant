import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { UNAUTHORIZED_EVENT, api, tokenStore } from "../api/client";
import type { Me } from "../api/types";

type Status = "loading" | "authed" | "anon";

interface AuthValue {
  status: Status;
  me: Me | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  refreshMe: () => Promise<void>;
  /** True if the level/permissions in /auth/me allow `perm`. creator bypasses. */
  can: (perm: string) => boolean;
  hasAdminPanel: boolean;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [status, setStatus] = useState<Status>("loading");

  const refreshMe = useCallback(async () => {
    const data = await api.me();
    setMe(data);
    setStatus("authed");
  }, []);

  const logout = useCallback(() => {
    tokenStore.clear();
    setMe(null);
    setStatus("anon");
  }, []);

  const login = useCallback(
    async (username: string, password: string) => {
      const token = await api.login(username, password);
      tokenStore.set(token);
      await refreshMe();
    },
    [refreshMe],
  );

  // Boot: resume a persisted session if the token still resolves.
  useEffect(() => {
    if (!tokenStore.get()) {
      setStatus("anon");
      return;
    }
    refreshMe().catch(() => {
      tokenStore.clear();
      setStatus("anon");
    });
  }, [refreshMe]);

  // A 401 from anywhere clears the session and drops back to login.
  useEffect(() => {
    const onUnauthorized = () => logout();
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [logout]);

  const value = useMemo<AuthValue>(() => {
    const isCreator = me?.level === "creator";
    return {
      status,
      me,
      login,
      logout,
      refreshMe,
      can: (perm: string) =>
        !!me && (isCreator || me.permissions.includes(perm)),
      hasAdminPanel: !!me && (isCreator || me.level === "admin"),
    };
  }, [status, me, login, logout, refreshMe]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
