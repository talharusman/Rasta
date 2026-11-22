import { createContext, useContext, useEffect, useMemo, useState } from "react";
import {
  type AuthResult, type AuthUser, type Role, ApiError, DEMO_MODE_ALLOWED, DEMO_PASSWORD, SESSION_EXPIRED_EVENT,
  demoAccounts, getCurrentUser, login as loginRequest,
} from "./api";

type Session = AuthResult;

interface AuthContextValue {
  user: AuthUser | null;
  login: (email: string, password: string) => Promise<AuthUser>;
  logout: () => void;
  switchRole: (role: Role) => Promise<void>;
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
    // A demo session left over from a build that allowed demo mode is not valid here.
    if (session?.user.source === "demo" && !DEMO_MODE_ALLOWED) {
      setSession(null);
      localStorage.removeItem(SESSION_KEY);
      return;
    }
    if (!session) return;
    // Verify /api/v1/auth/me in the background; a rejected token ends the session.
    getCurrentUser(session.accessToken)
      .then((updated) => {
        setSession((prev) => (prev ? { ...prev, user: { ...updated, email: prev.user.email } } : null));
      })
      .catch((error) => {
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          setSession(null);
          localStorage.removeItem(SESSION_KEY);
        }
        // Network errors keep the session so weak connections don't sign users out.
      });
  }, []);

  useEffect(() => {
    const expire = () => {
      setSession(null);
      localStorage.removeItem(SESSION_KEY);
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, expire);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, expire);
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
        // Shared phones: don't leave anyone's unsent claim draft behind.
        try {
          Object.keys(localStorage)
            .filter((key) => key.startsWith("rasta.claimDraft."))
            .forEach((key) => localStorage.removeItem(key));
        } catch {
          // ignore storage errors
        }
      },
      async switchRole(targetRole: Role) {
        const account = demoAccounts.find((a) => a.role === targetRole);
        if (!account) return;
        // loginRequest already falls back to the offline demo only when that is
        // explicitly enabled; any other failure is surfaced to the caller.
        if (!DEMO_PASSWORD) {
          throw new Error("Quick role switch is turned off. Sign out and sign in with the account's email and password.");
        }
        const next = await loginRequest(account.email, DEMO_PASSWORD);
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
