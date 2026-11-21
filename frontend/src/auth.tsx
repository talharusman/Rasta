import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { type AuthResult, type AuthUser, type Role, demoAccounts, getCurrentUser, login as loginRequest } from "./api";

type Session = AuthResult;

interface AuthContextValue {
  user: AuthUser | null;
  login: (email: string, password: string) => Promise<AuthUser>;
  logout: () => void;
  switchRole: (role: Role) => void;
  isRole: (...roles: Role[]) => boolean;
}

const SESSION_KEY = "rasta.session.v2";
const AuthContext = createContext<AuthContextValue | null>(null);

function loadSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as Session;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(loadSession);

  useEffect(() => {
    if (!session) return;
    // If authenticated via real API token, verify /api/v1/auth/me silently in background
    if (session.user.source === "api") {
      getCurrentUser(session.accessToken)
        .then((updated) => {
          setSession((prev) => (prev ? { ...prev, user: updated } : null));
        })
        .catch(() => {
          // Keep active session unless strictly revoked
        });
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user: session?.user ?? null,
      async login(email, password) {
        const next = await loginRequest(email, password);
        setSession(next);
        localStorage.setItem(SESSION_KEY, JSON.stringify(next));
        return next.user;
      },
      logout() {
        setSession(null);
        localStorage.removeItem(SESSION_KEY);
      },
      switchRole(targetRole: Role) {
        const account = demoAccounts.find((a) => a.role === targetRole);
        if (!account) return;
        const { password: _, label: __, description: ___, ...user } = account;
        const next: Session = {
          accessToken: `demo.${user.id}.${Date.now()}`,
          user: { ...user, source: "demo" },
        };
        setSession(next);
        localStorage.setItem(SESSION_KEY, JSON.stringify(next));
      },
      isRole: (...roles) => Boolean(session && roles.includes(session.user.role)),
    }),
    [session]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}
