"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { getSession, logout as logoutRequest, type User } from "@/lib/auth";

type AuthStatus = "loading" | "authenticated" | "unauthenticated";

type AuthContextValue = {
  user: User | null;
  status: AuthStatus;
  /** Record a user returned by login/register. */
  setUser: (user: User | null) => void;
  /** Re-ask the API who is signed in. */
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
};

// Default used only when no provider is above (e.g. a segment rendered in isolation
// by tooling). It behaves like "still checking" and performs no actions.
const noProvider: AuthContextValue = {
  user: null,
  status: "loading",
  setUser: () => {},
  refresh: async () => {},
  logout: async () => {},
};

const AuthContext = createContext<AuthContextValue>(noProvider);

/**
 * Holds the signed-in user for the whole app. The backend is the source of truth:
 * on load we call GET /auth/session (the HttpOnly cookie travels with it) and never
 * keep tokens in JavaScript-accessible storage.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");

  const setUser = useCallback((next: User | null) => {
    setUserState(next);
    setStatus(next ? "authenticated" : "unauthenticated");
  }, []);

  const refresh = useCallback(async () => {
    try {
      setUser(await getSession());
    } catch {
      // A network failure means "no usable session".
      setUser(null);
    }
  }, [setUser]);

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } finally {
      setUser(null);
    }
  }, [setUser]);

  // Initial session check. State is only set from the promise callbacks, and the
  // cancelled flag ignores a result that arrives after the effect was cleaned up.
  useEffect(() => {
    let cancelled = false;
    getSession()
      .then((me) => {
        if (!cancelled) setUser(me);
      })
      .catch(() => {
        if (!cancelled) setUser(null);
      });
    return () => {
      cancelled = true;
    };
  }, [setUser]);

  return (
    <AuthContext.Provider value={{ user, status, setUser, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}
