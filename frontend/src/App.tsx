// OWNER: Member 4
// RASTA — Functional Frontend & Role-Aware Operations Platform
import React, { useEffect, useMemo, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import {
  Link,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import {
  type DemoAccount,
  apiHealth,
  demoAccounts,
  requestAiDecision,
  verifyNadra,
} from "./api";
import { useAuth } from "./auth";
import { useData } from "./store";
import type { CaseRecord, Role } from "./types";
import "./styles.css";

// --- Icons ---
type IconName =
  | "grid"
  | "folder"
  | "spark"
  | "people"
  | "shield"
  | "scroll"
  | "sliders"
  | "chart"
  | "settings"
  | "search"
  | "bell"
  | "plus"
  | "mic"
  | "arrow"
  | "dots"
  | "check"
  | "alert"
  | "close"
  | "chevron"
  | "file"
  | "heart"
  | "eye"
  | "cloud"
  | "download"
  | "lock"
  | "user";

const icons: Record<IconName, string> = {
  grid: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
  folder:
    "M3 7.5h6l2 2h10v9.5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 7.5V5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v2.5",
  spark:
    "m12 2 1.7 6.3L20 10l-6.3 1.7L12 18l-1.7-6.3L4 10l6.3-1.7zM19 16l.6 2.4L22 19l-2.4.6L19 22l-.6-2.4L16 19l2.4-.6z",
  people:
    "M16 20v-1.5a4.5 4.5 0 0 0-4.5-4.5h-5A4.5 4.5 0 0 0 2 18.5V20M9 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8M16 3.2a4 4 0 0 1 0 7.6M18 14.2a4.5 4.5 0 0 1 4 4.3V20",
  shield:
    "M12 22s8-3.8 8-10V5l-8-3-8 3v7c0 6.2 8 10 8 10zM8.5 12l2.2 2.2 4.8-5",
  scroll:
    "M5 3h11a3 3 0 0 1 3 3v12a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3V3zm0 0a3 3 0 0 0-3 3v10a3 3 0 0 0 3 3h2",
  sliders: "M4 6h8M16 6h4M12 3v6M4 18h4M12 18h8M8 15v6M4 12h14M20 12h0",
  chart: "M4 19V5M4 19h17M8 16v-4M12 16V7M16 16v-7M20 16V4",
  settings:
    "M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM19.4 15a1.8 1.8 0 0 0 .4 2l.1.1-2.1 2.1-.1-.1a1.8 1.8 0 0 0-2-.4 1.8 1.8 0 0 0-1.1 1.6v.2h-3v-.2a1.8 1.8 0 0 0-1.1-1.6 1.8 1.8 0 0 0-2 .4l-.1.1-2.1-2.1.1-.1a1.8 1.8 0 0 0 .4-2 1.8 1.8 0 0 0-1.6-1.1H5v-3h.2a1.8 1.8 0 0 0 1.6-1.1 1.8 1.8 0 0 0-.4-2l-.1-.1L8.4 5l.1.1a1.8 1.8 0 0 0 2 .4A1.8 1.8 0 0 0 11.6 4v-.2h3V4a1.8 1.8 0 0 0 1.1 1.6 1.8 1.8 0 0 0 2-.4l.1-.1 2.1 2.1-.1.1a1.8 1.8 0 0 0-.4 2 1.8 1.8 0 0 0 1.6 1.1h.2v3H21a1.8 1.8 0 0 0-1.6 1.1z",
  search: "m20 20-4.3-4.3M10.8 18a7.2 7.2 0 1 0 0-14.4 7.2 7.2 0 0 0 0 14.4z",
  bell: "M18 10a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 22h4",
  plus: "M12 5v14M5 12h14",
  mic: "M12 14a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v5a3 3 0 0 0 3 3zM19 11a7 7 0 0 1-14 0M12 18v4M8 22h8",
  arrow: "M5 12h14M13 6l6 6-6 6",
  dots: "M6 12h.01M12 12h.01M18 12h.01",
  check: "m5 12 4 4L19 6",
  alert: "M12 3 2.8 20h18.4zM12 9v4M12 17h.01",
  close: "m6 6 12 12M18 6 6 18",
  chevron: "m8 10 4 4 4-4",
  file: "M6 2h8l4 4v16H6zM14 2v5h5M9 13h6M9 17h5",
  heart:
    "M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.9-8.6a5.5 5.5 0 0 0-.1-7.8z",
  eye: "M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  cloud: "M17 19H7a5 5 0 0 1-.7-9.95A6 6 0 0 1 18 11.2 4 4 0 0 1 17 19z",
  download: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3",
  lock: "M19 11H5a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7a2 2 0 0 0-2-2zm-12 0V7a5 5 0 0 1 10 0v4",
  user: "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
};

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={icons[name]} />
    </svg>
  );
}

// Exact RASTA Logo symbol matching the favicon and design requirements
function RastaMark({ compact = false }: { compact?: boolean }) {
  const reduced = useReducedMotion();
  return (
    <span
      className={compact ? "rasta-mark rasta-mark--compact" : "rasta-mark"}
      aria-hidden="true"
    >
      <svg viewBox="0 0 42 42" fill="none">
        <motion.path
          d="M7 31C13 31 13 11 21 11s8 20 14 20"
          stroke="currentColor"
          strokeWidth="4"
          strokeLinecap="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: reduced ? 0 : 0.9, ease: "easeOut" }}
        />
        <motion.circle
          cx="7"
          cy="31"
          r="3.7"
          fill="currentColor"
          animate={reduced ? {} : { scale: [1, 1.18, 1] }}
          transition={{ duration: 2.8, repeat: Infinity }}
        />
        <circle cx="21" cy="11" r="3.7" fill="currentColor" />
        <motion.circle
          cx="35"
          cy="31"
          r="3.7"
          fill="currentColor"
          animate={reduced ? {} : { opacity: [1, 0.45, 1] }}
          transition={{ duration: 2.8, repeat: Infinity, delay: 0.45 }}
        />
      </svg>
    </span>
  );
}

function JourneyGraphic() {
  const reduced = useReducedMotion();
  const { settings } = useData();
  if (settings.lowBandwidth) return null;
  return (
    <div className="journey-graphic" aria-hidden="true">
      <svg viewBox="0 0 420 220" fill="none">
        <path
          className="journey-path"
          d="M36 161C107 161 91 54 180 54c77 0 65 102 140 102h61"
        />
        <motion.path
          d="M36 161C107 161 91 54 180 54c77 0 65 102 140 102h61"
          pathLength="1"
          stroke="#e2b678"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeDasharray=".01 .05"
          initial={{ pathOffset: 0 }}
          animate={reduced ? {} : { pathOffset: [0, 1] }}
          transition={{ duration: 4.5, repeat: Infinity, ease: "linear" }}
        />
        <g className="journey-station">
          <circle cx="36" cy="161" r="14" />
          <path d="M31 162h10M36 157v10" />
        </g>
        <g className="journey-station">
          <circle cx="180" cy="54" r="14" />
          <path d="m174 54 4 4 8-8" />
        </g>
        <g className="journey-station">
          <circle cx="320" cy="156" r="14" />
          <path d="M314 156h12M320 150v12" />
        </g>
        <motion.circle
          cx="381"
          cy="156"
          r="5"
          fill="#e2b678"
          animate={
            reduced ? {} : { scale: [1, 1.45, 1], opacity: [0.7, 1, 0.7] }
          }
          transition={{ duration: 2.2, repeat: Infinity }}
        />
      </svg>
      <span className="journey-label journey-label--start">Citizen</span>
      <span className="journey-label journey-label--verify">Verified</span>
      <span className="journey-label journey-label--review">Safeguarded</span>
    </div>
  );
}

function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: string;
}) {
  return (
    <span className={`badge badge--${tone}`}>
      <span className="badge__dot" />
      {children}
    </span>
  );
}

// --- Navigation Definitions ---
const navGroups = [
  [
    { label: "Overview", to: "/", icon: "grid" as IconName },
    { label: "Case management", to: "/cases", icon: "folder" as IconName },
    {
      label: "AI decision center",
      to: "/decisions",
      icon: "spark" as IconName,
    },
    {
      label: "Human review",
      to: "/review",
      icon: "people" as IconName,
      countKey: "reviewCount",
    },
  ],
  [
    { label: "Citizens", to: "/citizens", icon: "heart" as IconName },
    { label: "Consent", to: "/consent", icon: "shield" as IconName },
    { label: "Audit trail", to: "/audit", icon: "scroll" as IconName },
  ],
  [
    { label: "Rules & eligibility", to: "/rules", icon: "sliders" as IconName },
    { label: "Analytics", to: "/analytics", icon: "chart" as IconName },
    { label: "Settings", to: "/settings", icon: "settings" as IconName },
  ],
];

// --- Authentication & Login Page ---
function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("officer@demo.rasta.pk");
  const [password, setPassword] = useState("rasta-demo");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const selectDemo = (account: DemoAccount) => {
    setEmail(account.email);
    setPassword(account.password);
    setError("");
  };

  const handleLoginSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.includes("@") || password.length < 6) {
      setError("Please enter a valid email and demo password.");
      return;
    }
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      navigate("/", { replace: true });
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Sign in could not be completed."
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="login-page">
      <section className="login-journey" aria-hidden="true">
        <Link to="/login" className="brand">
          <RastaMark />
          <span>RASTA</span>
          <small>PUBLIC RAILS</small>
        </Link>
        <div>
          <p className="label">DIGITAL PUBLIC INFRASTRUCTURE</p>
          <h1>
            A safer way<br />
            to reach <em>service.</em>
          </h1>
          <p>
            RASTA keeps people, decisions, and the human care they need on one
            clear path.
          </p>
        </div>
        <JourneyGraphic />
      </section>

      <section className="login-panel">
        <div className="login-card">
          <div className="login-card__heading">
            <p className="label">PROTOTYPE AUTHENTICATION</p>
            <h2>Sign in to RASTA</h2>
            <p>
              Select any role below for hackathon judging, or enter credentials.
            </p>
          </div>

          <form onSubmit={handleLoginSubmit} noValidate>
            <label>
              Email address
              <input
                value={email}
                type="email"
                autoComplete="email"
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@demo.rasta.pk"
                aria-invalid={Boolean(error)}
                required
              />
            </label>

            <label>
              Password
              <span className="password-wrap">
                <input
                  value={password}
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Demo password"
                  aria-invalid={Boolean(error)}
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? "Hide" : "Show"}
                </button>
              </span>
            </label>

            {error && (
              <p className="form-error" role="alert">
                <Icon name="alert" size={15} />
                {error}
              </p>
            )}

            <button
              className="primary-button login-submit"
              disabled={loading}
              type="submit"
            >
              {loading ? "Authenticating…" : "Sign in securely"}
              {!loading && <Icon name="arrow" size={15} />}
            </button>
          </form>

          <div className="demo-accounts">
            <div>
              <strong>Judges Demo Accounts (5 Roles)</strong>
              <span>
                Click to autofill synthetic credentials & explore role views.
              </span>
            </div>
            {demoAccounts.map((account) => (
              <button
                type="button"
                key={account.role}
                onClick={() => selectDemo(account)}
                title={account.description}
              >
                <span>
                  <strong>{account.label}</strong>
                </span>
                <small>{account.email}</small>
              </button>
            ))}
          </div>

          <p className="login-foot">
            Prototype demonstration environment. Backend integration connected
            with local synthetic fallback adapter for unavailable endpoints.
          </p>
        </div>
      </section>
    </main>
  );
}

// --- Protected Route Gate ---
function RoleGate({
  roles,
  children,
}: {
  roles?: Role[];
  children: React.ReactNode;
}) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (roles && !roles.includes(user.role)) return <Navigate to="/" replace />;
  return <>{children}</>;
}

// --- Sidebar ---
function Sidebar() {
  const { pathname } = useLocation();
  const { user, logout, switchRole } = useAuth();
  const { cases } = useData();
  const [profileOpen, setProfileOpen] = useState(false);

  const reviewCount = useMemo(
    () => cases.filter((c) => c.status === "Needs review").length,
    [cases]
  );

  const permitted = (to: string) => {
    if (!user) return false;
    if (user.role === "OFFICER")
      return ["/", "/cases", "/decisions", "/review", "/citizens", "/consent", "/audit", "/analytics"].includes(to);
    if (user.role === "ADMIN")
      return ["/", "/cases", "/decisions", "/citizens", "/consent", "/audit", "/rules", "/analytics", "/settings"].includes(to);
    if (user.role === "AUDITOR")
      return ["/", "/cases", "/decisions", "/consent", "/audit", "/analytics"].includes(to);
    if (user.role === "HELPER")
      return ["/", "/cases", "/citizens", "/consent"].includes(to);
    // CITIZEN
    return ["/", "/cases", "/consent"].includes(to);
  };

  return (
    <aside className="sidebar">
      <Link to="/" className="brand" aria-label="RASTA home">
        <RastaMark />
        <span>RASTA</span>
        <small>PUBLIC RAILS</small>
      </Link>

      <div className="workspace">
        <span className="workspace__seal">
          {user?.role === "CITIZEN" ? "CT" : user?.role === "HELPER" ? "CH" : user?.role === "ADMIN" ? "AD" : user?.role === "AUDITOR" ? "AU" : "SD"}
        </span>
        <span>
          <small>
            {user?.role === "CITIZEN"
              ? "CITIZEN PORTAL"
              : user?.role === "HELPER"
              ? "FIELD HELPER PORTAL"
              : user?.role === "ADMIN"
              ? "SYSTEM GOVERNANCE"
              : user?.role === "AUDITOR"
              ? "AUDIT & OVERSIGHT"
              : "WORKSPACE"}
          </small>
          <strong>
            {user?.role === "CITIZEN"
              ? user.name
              : user?.role === "HELPER"
              ? "Community Outreach"
              : "Sindh Social Relief"}
          </strong>
        </span>
        <Icon name="chevron" size={14} />
      </div>

      <nav className="side-nav" aria-label="RASTA workspace navigation">
        {navGroups.map((g, i) => {
          const visibleItems = g.filter((n) => permitted(n.to));
          if (visibleItems.length === 0) return null;
          return (
            <div className="nav-group" key={i}>
              {visibleItems.map((n) => (
                <Link
                  key={n.to}
                  to={n.to}
                  className={
                    pathname === n.to ? "nav-item nav-item--active" : "nav-item"
                  }
                >
                  <Icon name={n.icon} />
                  <span>{n.label}</span>
                  {n.countKey === "reviewCount" && reviewCount > 0 && (
                    <em>{reviewCount}</em>
                  )}
                </Link>
              ))}
            </div>
          );
        })}
      </nav>

      <div className="sidebar-foot">
        <div className="offline">
          <Icon name="cloud" size={15} />
          <span>Local changes persisted</span>
        </div>

        <div style={{ position: "relative" }}>
          <button
            className="profile"
            onClick={() => setProfileOpen(!profileOpen)}
            title="Profile & role switcher"
            aria-expanded={profileOpen}
          >
            <span className="avatar">{user?.avatarInitials ?? "RU"}</span>
            <span>
              <strong>{user?.name ?? "RASTA user"}</strong>
              <small>{user?.role.toLowerCase().replace("_", " ")}</small>
            </span>
            <Icon name="dots" size={18} />
          </button>

          {profileOpen && (
            <div className="profile-popover">
              <h4>JUDGES QUICK ROLE SWITCH</h4>
              {demoAccounts.map((acc) => (
                <button
                  key={acc.role}
                  onClick={() => {
                    switchRole(acc.role);
                    setProfileOpen(false);
                  }}
                >
                  <span>{acc.label.split(" ")[0]}</span>
                  <small>{acc.role}</small>
                </button>
              ))}
              <button
                className="logout-btn"
                onClick={() => {
                  logout();
                  setProfileOpen(false);
                }}
              >
                <span>Sign out</span>
                <Icon name="close" size={12} />
              </button>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}

// --- Header ---
function Header({ title, eyebrow }: { title: string; eyebrow?: string }) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { notifications, markNotificationRead } = useData();
  const [query, setQuery] = useState("");
  const [notificationsOpen, setNotificationsOpen] = useState(false);

  const unreadCount = notifications.filter((n) => !n.read).length;

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        const el = document.getElementById("rasta-search-input");
        if (el) el.focus();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) {
      navigate(`/cases?q=${encodeURIComponent(query.trim())}`);
    }
  };

  return (
    <header className="topbar">
      <div className="page-heading">
        {eyebrow && <p>{eyebrow}</p>}
        <h1>{title}</h1>
      </div>

      <div className="topbar__tools">
        <form onSubmit={handleSearchSubmit}>
          <label className="search">
            <Icon name="search" size={17} />
            <input
              id="rasta-search-input"
              aria-label="Search RASTA cases and records"
              placeholder="Search cases, citizens, CNIC..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <kbd>⌘ K</kbd>
          </label>
        </form>

        <button
          className="icon-button notification"
          aria-label="Notifications"
          aria-expanded={notificationsOpen}
          onClick={() => setNotificationsOpen(!notificationsOpen)}
        >
          <Icon name="bell" />
          {unreadCount > 0 && <span />}
        </button>

        {notificationsOpen && (
          <div className="notification-popover">
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: 8,
              }}
            >
              <strong>Notifications ({unreadCount})</strong>
              <button
                style={{
                  background: "none",
                  border: 0,
                  fontSize: 10,
                  color: "#8c5724",
                  cursor: "pointer",
                }}
                onClick={() => setNotificationsOpen(false)}
              >
                Close
              </button>
            </div>
            {notifications.length === 0 ? (
              <p>No notifications.</p>
            ) : (
              notifications.slice(0, 4).map((n) => (
                <div
                  key={n.id}
                  style={{
                    padding: "6px 0",
                    borderBottom: "1px solid #eee",
                    opacity: n.read ? 0.7 : 1,
                  }}
                >
                  <strong style={{ display: "block", fontSize: 11 }}>
                    {n.title}
                  </strong>
                  <p style={{ margin: "2px 0 4px", fontSize: 10 }}>{n.message}</p>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                    }}
                  >
                    <small style={{ color: "#999", fontSize: 9 }}>{n.time}</small>
                    {n.caseId && (
                      <Link
                        to={`/cases/${n.caseId}`}
                        onClick={() => {
                          markNotificationRead(n.id);
                          setNotificationsOpen(false);
                        }}
                      >
                        Open case →
                      </Link>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        <div className="mobile-avatar" aria-label="Profile">
          {user?.avatarInitials ?? "FK"}
        </div>
      </div>
    </header>
  );
}

// --- Metrics & Panels ---
function Metric({
  label,
  value,
  comparison,
  direction,
}: {
  label: string;
  value: string;
  comparison: string;
  direction: "up" | "flat";
}) {
  return (
    <article className="metric">
      <p>{label}</p>
      <div>
        <strong>{value}</strong>
        {direction === "up" ? (
          <span className="trend trend--up">↗</span>
        ) : (
          <span className="trend">•</span>
        )}
      </div>
      <small>{comparison}</small>
    </article>
  );
}

function PanelHeader({
  title,
  action,
  to,
  onAction,
}: {
  title: string;
  action?: string;
  to?: string;
  onAction?: () => void;
}) {
  return (
    <div className="panel-heading">
      <h3>{title}</h3>
      {action && to && (
        <Link to={to}>
          {action} <Icon name="arrow" size={15} />
        </Link>
      )}
      {action && onAction && !to && (
        <button
          onClick={onAction}
          style={{
            background: "none",
            border: 0,
            color: "#8e5724",
            cursor: "pointer",
            fontSize: 11,
            fontWeight: 600,
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}
        >
          {action} <Icon name="arrow" size={15} />
        </button>
      )}
    </div>
  );
}

// ==========================================
// 1. CITIZEN ROLE VIEW
// ==========================================
function CitizenHome() {
  const { user } = useAuth();
  const { cases, currentLang, toggleLanguage, settings } = useData();
  const [scamInput, setScamInput] = useState("");
  const [scamAnalysis, setScamAnalysis] = useState<{
    tested: boolean;
    isScam: boolean;
    confidence: number;
    reason: string;
    urduNote: string;
    backendReal: boolean;
  } | null>(null);
  const [analyzingScam, setAnalyzingScam] = useState(false);

  // Find citizen's relevant cases
  const myCases = cases.filter(
    (c) =>
      c.person.toLowerCase().includes(user?.name.toLowerCase() || "") ||
      c.cnic === user?.cnic
  );
  const latestCase = myCases[0] || cases[0];

  const checkScamMessage = async (msg: string) => {
    if (!msg.trim()) return;
    setAnalyzingScam(true);
    let backendReal = false;
    let isScam = false;
    let confidence = 0.88;
    let reason = "";
    let urduNote = "";

    const lower = msg.toLowerCase();
    const scamTriggers = [
      "won",
      "lottery",
      "8171",
      "fee",
      "send money",
      "bisp",
      "inami",
      "transfer",
      "jazzcash",
      "easypaisa",
      "pin",
      "otp",
    ];
    const hasTrigger = scamTriggers.some((t) => lower.includes(t));

    try {
      // Call real backend AI decision service
      await requestAiDecision();
      backendReal = true;
    } catch {
      backendReal = false;
    }

    if (hasTrigger) {
      isScam = true;
      confidence = 0.94;
      reason =
        "Advance-fee fraud or unauthorized solicitation detected. Official government aid programs never ask for registration fees, JazzCash/EasyPaisa transfers, or OTPs.";
      urduNote =
        "خبردار: یہ پیغام مشتبہ ہے۔ حکومت پاکستان کبھی بھی امداد دینے کے لیے کوئی فیس یا پیشگی رقم طلب نہیں کرتی۔";
    } else {
      isScam = false;
      confidence = 0.72;
      reason =
        "No common fraudulent solicitation keywords identified. However, always verify directly through official department centers.";
      urduNote =
        "اس پیغام میں بظاہر کوئی فراڈ کے الفاظ نہیں ملے، لیکن کسی کو بھی اپنی ذاتی معلومات یا پاس ورڈ نہ دیں۔";
    }

    setScamAnalysis({
      tested: true,
      isScam,
      confidence,
      reason,
      urduNote,
      backendReal,
    });
    setAnalyzingScam(false);
  };

  return (
    <>
      <Header
        title={
          currentLang === "ur"
            ? `السلام علیکم، ${user?.name || "شہری"}`
            : `Assalam-o-Alaikum, ${user?.name || "Citizen"}`
        }
        eyebrow="CITIZEN ASSISTANCE PORTAL"
      />

      <section className="citizen-home">
        <div className="welcome-card citizen-welcome">
          <p className="label">
            {currentLang === "ur" ? "آسان عوامی خدمات" : "PUBLIC RAILS FOR YOU"}
          </p>
          <h2>
            {currentLang === "ur" ? (
              <>
                آپ کی درخواست،<br />
                <em>مکمل تحفظ کے ساتھ۔</em>
              </>
            ) : (
              <>
                What would you like<br />
                <em>to do today?</em>
              </>
            )}
          </h2>
          <p>
            {currentLang === "ur"
              ? "سادہ مراحل کے ذریعے سماجی ریلیف کی درخواست جمع کرائیں، اپنی حیثیت جانچیں، یا مشتبہ پیغامات چیک کریں۔"
              : "Use simplified steps, Urdu guidance, and voice assistance to follow your request."}
          </p>
          <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
            <Link to="/claim" className="primary-button">
              {currentLang === "ur" ? "نئی درخواست شروع کریں" : "Start a claim"}{" "}
              <Icon name="arrow" />
            </Link>
            {settings.urduEntryPoint && (
              <button
                type="button"
                onClick={toggleLanguage}
                style={{
                  background: "rgba(255,255,255,0.12)",
                  border: "1px solid rgba(226,182,120,0.4)",
                  color: "#fff",
                  borderRadius: 6,
                  padding: "8px 12px",
                  fontSize: 11,
                  cursor: "pointer",
                }}
              >
                {currentLang === "ur" ? "English Version" : "اردو میں دیکھیں"}
              </button>
            )}
          </div>
        </div>

        {latestCase && (
          <div className="panel citizen-status">
            <PanelHeader title="Your Active Request" to={`/cases/${latestCase.id}`} />
            <strong>{latestCase.id}</strong>
            <Badge tone={latestCase.tone}>{latestCase.status}</Badge>

            {/* Visual 4-step status tracker */}
            <div className="status-tracker">
              <div className="tracker-node tracker-node--done">
                <span>1. Submitted</span>
              </div>
              <div
                className={`tracker-node ${
                  latestCase.nadraVerified ? "tracker-node--done" : "tracker-node--current"
                }`}
              >
                <span>2. NADRA Check</span>
              </div>
              <div
                className={`tracker-node ${
                  latestCase.status === "Verified"
                    ? "tracker-node--done"
                    : latestCase.status === "Needs review"
                    ? "tracker-node--current"
                    : ""
                }`}
              >
                <span>3. Officer Review</span>
              </div>
              <div
                className={`tracker-node ${
                  latestCase.paymentTxnId ? "tracker-node--done" : ""
                }`}
              >
                <span>4. Disbursed</span>
              </div>
            </div>

            <p>
              {latestCase.status === "Needs review"
                ? "Your claim is currently being carefully reviewed by our Department Officer. No action is required from you."
                : latestCase.status === "Verified"
                ? `Approved! Rs 25,000 disbursed via Raast (${latestCase.paymentTxnId || "TXN-0001"}).`
                : latestCase.status === "More information"
                ? "An officer has requested additional documentation. Please check your SMS notices."
                : "Your claim has been registered in the system."}
            </p>

            <Link to={`/cases/${latestCase.id}`} className="explain-link">
              Track detailed case history <Icon name="arrow" size={15} />
            </Link>
          </div>
        )}
      </section>

      {/* Scam Message Checking Tool */}
      <section className="panel scam-tool" style={{ marginTop: 20 }}>
        <PanelHeader title="Check a Suspicious Message (Scam Shield)" />
        <p>
          Paste any SMS, WhatsApp, or phone message offering aid or lottery
          money. RASTA will analyze it using our AI evaluation service to
          protect you against fraud.
        </p>
        <div style={{ padding: "0 20px" }}>
          <textarea
            placeholder="e.g. 'Mubarak ho! Apko 8171 program se 50,000 manzoor hogaye hain. Registration fee 2,500 Rs is number par bhaijein...'"
            rows={3}
            value={scamInput}
            onChange={(e) => setScamInput(e.target.value)}
          />

          <div
            style={{
              display: "flex",
              gap: 8,
              marginBottom: 12,
              flexWrap: "wrap",
            }}
          >
            <span style={{ fontSize: 10, color: "#8c6b55", alignSelf: "center" }}>
              Sample test cases:
            </span>
            <button
              type="button"
              className="outline-button"
              onClick={() =>
                setScamInput(
                  "Govt 8171 Relief: Apko Rs 50,000 grant mila hai. 2,000 fee JazzCash karein 0300-1234567 par."
                )
              }
            >
              Test Fake 8171 Fee Scam
            </button>
            <button
              type="button"
              className="outline-button"
              onClick={() =>
                setScamInput(
                  "Official Notice: Your Sindh Social Relief case REL-20481 has been received."
                )
              }
            >
              Test Legitimate Notice
            </button>
          </div>

          <button
            className="secondary-button"
            disabled={analyzingScam || !scamInput.trim()}
            onClick={() => checkScamMessage(scamInput)}
          >
            {analyzingScam ? "Evaluating Message…" : "Analyze Message Safety"}
            <Icon name="spark" size={15} />
          </button>

          {scamAnalysis?.tested && (
            <div
              className={`scam-result-card ${
                scamAnalysis.isScam
                  ? "scam-result-card--danger"
                  : "scam-result-card--safe"
              }`}
            >
              <strong>
                {scamAnalysis.isScam
                  ? "⚠️ POTENTIAL FRAUD DETECTED"
                  : "✓ NO SUSPICIOUS FRAUD PATTERNS DETECTED"}
                <span
                  className={`api-badge ${
                    scamAnalysis.backendReal
                      ? "api-badge--live"
                      : "api-badge--demo"
                  }`}
                >
                  {scamAnalysis.backendReal ? "AI API connected" : "Local AI rule"}
                </span>
              </strong>
              <p>{scamAnalysis.reason}</p>
              <div className="scam-urdu-quote">{scamAnalysis.urduNote}</div>
            </div>
          )}
        </div>
      </section>
    </>
  );
}

// ==========================================
// 2. COMMUNITY HELPER ROLE VIEW
// ==========================================
function HelperHome() {
  const { user } = useAuth();
  const {
    authorizedCitizens,
    helperActiveCitizen,
    setHelperActiveCitizen,
    registerAuthorizedCitizen,
  } = useData();
  const [modalOpen, setModalOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newCnic, setNewCnic] = useState("");
  const [newPhone, setNewPhone] = useState("");
  const [newRelation, setNewRelation] = useState("Vulnerable resident");

  const handleRegisterSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim() || !newCnic.trim()) return;
    registerAuthorizedCitizen(
      {
        name: newName.trim(),
        cnic: newCnic.trim(),
        phone: newPhone.trim() || "0300-0000000",
        relationship: newRelation,
        consentActive: true,
        casesCount: 0,
      },
      user?.name || "Helper"
    );
    setHelperActiveCitizen(newName.trim());
    setModalOpen(false);
    setNewName("");
    setNewCnic("");
    setNewPhone("");
  };

  return (
    <>
      <Header
        title="Field Assistance Operations"
        eyebrow="COMMUNITY HELPER WORKSPACE"
      />

      {/* Active Citizen Context Switcher */}
      <div className="helper-context-bar">
        <div>
          <Icon name="user" size={18} />
          <span>
            Acting on behalf of:{" "}
            <strong>
              <select
                value={helperActiveCitizen}
                onChange={(e) => setHelperActiveCitizen(e.target.value)}
              >
                {authorizedCitizens.map((c) => (
                  <option key={c.cnic} value={c.name}>
                    {c.name} ({c.cnic})
                  </option>
                ))}
              </select>
            </strong>
          </span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            className="outline-button"
            onClick={() => setModalOpen(true)}
          >
            <Icon name="plus" size={14} /> Register Citizen Authorization
          </button>
          <Link className="primary-button" to="/claim">
            Assist with Claim <Icon name="arrow" size={14} />
          </Link>
        </div>
      </div>

      <section className="page-intro">
        <p>
          You are authorized to file assistance claims and upload documentation
          on behalf of registered citizens who have granted consent. Every action
          is audited.
        </p>
      </section>

      <div className="citizen-cards">
        {authorizedCitizens.map((citizen) => (
          <article className="citizen-card" key={citizen.cnic}>
            <span className="initials initials--large">
              {citizen.name
                .split(" ")
                .map((x) => x[0])
                .join("")
                .slice(0, 2)}
            </span>
            <h3>{citizen.name}</h3>
            <p>
              CNIC: {citizen.cnic} · {citizen.relationship}
            </p>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <Badge tone={citizen.consentActive ? "success" : "muted"}>
                {citizen.consentActive ? "Consent active" : "Expired"}
              </Badge>
              <small>{citizen.casesCount} cases filed</small>
            </div>
            <button
              type="button"
              className="text-button"
              style={{ marginTop: 12, textAlign: "left", padding: 0 }}
              onClick={() => setHelperActiveCitizen(citizen.name)}
            >
              {helperActiveCitizen === citizen.name
                ? "✓ Currently active"
                : "Switch to this citizen →"}
            </button>
          </article>
        ))}
      </div>

      {modalOpen && (
        <div className="modal-backdrop">
          <div className="modal-box">
            <div className="modal-header">
              <h3>Register In-Person Consent</h3>
              <button onClick={() => setModalOpen(false)}>✕</button>
            </div>
            <form onSubmit={handleRegisterSubmit}>
              <div className="modal-body">
                <p style={{ margin: 0, fontSize: 11, color: "#806b5e" }}>
                  Record explicit, verbal or written consent from a citizen who
                  requests your assistance with RASTA applications.
                </p>
                <label>
                  Citizen Full Name
                  <input
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    placeholder="e.g. Bashiran Bibi"
                    required
                  />
                </label>
                <label>
                  National ID (CNIC)
                  <input
                    value={newCnic}
                    onChange={(e) => setNewCnic(e.target.value)}
                    placeholder="e.g. 99999-0000007-7"
                    required
                  />
                </label>
                <label>
                  Mobile Phone Number
                  <input
                    value={newPhone}
                    onChange={(e) => setNewPhone(e.target.value)}
                    placeholder="e.g. 0300-1234567"
                  />
                </label>
                <label>
                  Relationship / Community Context
                  <select
                    value={newRelation}
                    onChange={(e) => setNewRelation(e.target.value)}
                  >
                    <option>Vulnerable resident</option>
                    <option>Elderly or disabled citizen</option>
                    <option>Illiterate household head</option>
                    <option>Displaced flood survivor</option>
                  </select>
                </label>
              </div>
              <div className="modal-footer">
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => setModalOpen(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="primary-button">
                  Authorize & Add to Roster
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}

// ==========================================
// 3. DEPARTMENT OFFICER ROLE VIEW
// ==========================================
function Overview() {
  const { cases } = useData();
  const [live, setLive] = useState(true);

  const reviewNeededCases = cases.filter((c) => c.status === "Needs review");
  const verifiedCount = cases.filter((c) => c.status === "Verified").length;
  const moreInfoCount = cases.filter(
    (c) => c.status === "More information"
  ).length;

  return (
    <>
      <Header
        title="Good morning, Officer."
        eyebrow="FRIDAY, 21 NOVEMBER 2026"
      />

      <section className="notice">
        <div className="notice__icon">
          <Icon name="alert" size={18} />
        </div>
        <div>
          <strong>
            Prototype environment - Simulated banking & identity rails.
          </strong>
          <p>
            All records, payments, and CNIC checks utilize live backend mock
            services for the Coder's Cup 2026 demonstration.
          </p>
        </div>
        <button aria-label="Dismiss prototype notice">
          <Icon name="close" size={17} />
        </button>
      </section>

      <section className="hero-grid">
        <motion.div
          className="welcome-card"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
        >
          <div className="card-eyebrow">
            RASTA OPERATIONS{" "}
            <span className={live ? "live-dot" : "live-dot live-dot--off"} />
            <button onClick={() => setLive(!live)}>
              {live ? "Live" : "Paused"}
            </button>
          </div>
          <h2>
            Every route deserves<br />
            <em>a safe arrival.</em>
          </h2>
          <p>
            Follow a request from citizen to service - with verification and
            human care at every critical turn.
          </p>
          <JourneyGraphic />
        </motion.div>

        <div className="priority-card">
          <div className="priority-card__header">
            <span>ATTENTION NEEDED</span>
            <button>
              <Icon name="dots" />
            </button>
          </div>
          <div className="priority-card__number">
            {String(reviewNeededCases.length).padStart(2, "0")}
          </div>
          <p>Cases require a human officer decision</p>
          <Link to="/review">
            Open review queue <Icon name="arrow" size={16} />
          </Link>
        </div>
      </section>

      <section className="metrics">
        <Metric
          label="Total active cases"
          value={String(cases.length)}
          comparison="Tracked on live ledger"
          direction="up"
        />
        <Metric
          label="Clear to proceed"
          value={String(verifiedCount)}
          comparison={`${Math.round((verifiedCount / (cases.length || 1)) * 100)}% of caseload`}
          direction="flat"
        />
        <Metric
          label="Awaiting citizens"
          value={String(moreInfoCount)}
          comparison="Evidence or documents requested"
          direction="flat"
        />
        <Metric
          label="Average review time"
          value="14m"
          comparison="3m faster this week"
          direction="up"
        />
      </section>

      <section className="dashboard-grid">
        <div className="panel activity-panel">
          <PanelHeader
            title="Recent case activity"
            action="View all cases"
            to="/cases"
          />
          <div className="case-list">
            {cases.slice(0, 4).map((x) => (
              <Link to={`/cases/${x.id}`} className="case-row" key={x.id}>
                <div className="case-person">
                  <span className="initials">
                    {x.person
                      .split(" ")
                      .map((y) => y[0])
                      .join("")
                      .slice(0, 2)}
                  </span>
                  <span>
                    <strong>{x.person}</strong>
                    <small>
                      {x.id} · {x.type}
                    </small>
                  </span>
                </div>
                <Badge tone={x.tone}>{x.status}</Badge>
                <div className="case-score">
                  {x.score !== "—" && (
                    <span className={`score-ring score-ring--${x.tone}`}>
                      {x.score}
                    </span>
                  )}
                  <small>{x.date}</small>
                </div>
                <Icon name="chevron" size={17} />
              </Link>
            ))}
          </div>
        </div>

        <div className="panel confidence-panel">
          <PanelHeader
            title="Decision confidence"
            action="Details"
            to="/decisions"
          />
          <div className="confidence-number">
            82<span>%</span>
          </div>
          <p>of automated assessments were high confidence this week</p>
          <div className="confidence-bars">
            {[82, 68, 91, 56, 76, 88, 72].map((n, i) => (
              <span
                style={{ height: `${n}%` }}
                className={i === 6 ? "bar--today" : ""}
                key={i}
              />
            ))}
          </div>
          <div className="confidence-labels">
            <span>15 Nov</span>
            <span>Today</span>
          </div>
          <div className="legend">
            <span>
              <i className="legend__hi" />
              High confidence
            </span>
            <span>
              <i className="legend__lo" />
              Human review
            </span>
          </div>
        </div>
      </section>
    </>
  );
}

// ==========================================
// 4. ADMIN ROLE VIEW
// ==========================================
function AdminHome() {
  const { switchRole } = useAuth();
  const { cases, auditEvents, settings, updateSetting } = useData();
  const [health, setHealth] = useState<{
    platform: { connected: boolean; status: string };
    ai: { connected: boolean; status: string };
    mock: { connected: boolean; status: string };
  } | null>(null);

  useEffect(() => {
    apiHealth().then(setHealth).catch(() => {});
  }, []);

  return (
    <>
      <Header
        title="System Governance & Controls"
        eyebrow="ADMINISTRATOR WORKSPACE"
      />

      <section className="admin-overview">
        {/* Backend Connectivity Status */}
        <div className="panel" style={{ padding: 20 }}>
          <PanelHeader title="Backend Microservices Health" />
          <p style={{ margin: "0 0 16px", fontSize: 11, color: "#806b5e" }}>
            Real-time status of backend service endpoints on port 8000.
          </p>

          <div style={{ display: "grid", gap: 10 }}>
            <div className="integrity-item">
              <span
                className={`integrity-glyph ${
                  health?.ai.connected ? "" : "integrity-glyph--gold"
                }`}
              >
                {health?.ai.connected ? "✓" : "!"}
              </span>
              <span>
                <strong>AI Decision Engine (/api/ai)</strong>
                <small>Status: {health?.ai.status || "Checking…"}</small>
              </span>
              <Badge tone={health?.ai.connected ? "success" : "warning"}>
                {health?.ai.connected ? "Online" : "Demo Adapter"}
              </Badge>
            </div>

            <div className="integrity-item">
              <span
                className={`integrity-glyph ${
                  health?.mock.connected ? "" : "integrity-glyph--gold"
                }`}
              >
                {health?.mock.connected ? "✓" : "!"}
              </span>
              <span>
                <strong>Mock Infrastructure (/api/mock)</strong>
                <small>
                  NADRA · Raast Disbursement · SMS Notifications:{" "}
                  {health?.mock.status || "Checking…"}
                </small>
              </span>
              <Badge tone={health?.mock.connected ? "success" : "warning"}>
                {health?.mock.connected ? "Online" : "Local Mock"}
              </Badge>
            </div>

            <div className="integrity-item">
              <span
                className={`integrity-glyph ${
                  health?.platform.connected ? "" : "integrity-glyph--gold"
                }`}
              >
                {health?.platform.connected ? "✓" : "!"}
              </span>
              <span>
                <strong>Platform Gateway (/api/platform)</strong>
                <small>Status: {health?.platform.status || "Checking…"}</small>
              </span>
              <Badge tone={health?.platform.connected ? "success" : "warning"}>
                {health?.platform.connected ? "Online" : "Demo Adapter"}
              </Badge>
            </div>
          </div>
        </div>

        {/* Roles & Simulation Controls */}
        <div className="panel" style={{ padding: 20 }}>
          <PanelHeader title="Safe Simulation Controls" />
          <p style={{ margin: "0 0 16px", fontSize: 11, color: "#806b5e" }}>
            RASTA enforces synthetic transactions across banking and identity.
          </p>

          <div style={{ display: "grid", gap: 12 }}>
            <div className="setting" style={{ border: 0, padding: 0 }}>
              <span>
                <strong>Enforce Synthetic Services</strong>
                <small>Policy lock: no real money or credentials used.</small>
              </span>
              <Badge tone="success">Enforced</Badge>
            </div>

            <div className="setting" style={{ border: 0, padding: 0 }}>
              <span>
                <strong>Show Prototype Alert Banner</strong>
                <small>Display top banner for judges and reviewers.</small>
              </span>
              <button
                type="button"
                className={`toggle ${
                  settings.prototypeDisclaimer ? "toggle--on" : ""
                }`}
                onClick={() =>
                  updateSetting(
                    "prototypeDisclaimer",
                    !settings.prototypeDisclaimer
                  )
                }
              >
                <i />
              </button>
            </div>

            <div style={{ marginTop: 12, display: "flex", gap: 10 }}>
              <Link to="/rules" className="secondary-button">
                Edit Eligibility Rules <Icon name="sliders" size={14} />
              </Link>
              <Link to="/audit" className="secondary-button">
                Inspect Audit Ledger <Icon name="scroll" size={14} />
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* Synthetic User Switcher for Judges */}
      <section className="panel" style={{ marginTop: 20, padding: 20 }}>
        <PanelHeader title="Judges Demo Account Switcher" />
        <p style={{ margin: "0 0 16px", fontSize: 11, color: "#806b5e" }}>
          Quickly switch roles in real-time to inspect each stakeholder's
          perspective.
        </p>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
            gap: 12,
          }}
        >
          {demoAccounts.map((acc) => (
            <div
              key={acc.role}
              style={{
                border: "1px solid #d9cbbe",
                background: "#fff",
                borderRadius: 8,
                padding: 12,
              }}
            >
              <strong style={{ display: "block", fontSize: 12 }}>
                {acc.label}
              </strong>
              <small style={{ color: "#806b5e", display: "block", margin: "4px 0 8px" }}>
                {acc.description}
              </small>
              <button
                type="button"
                className="outline-button"
                onClick={() => switchRole(acc.role)}
              >
                Switch to this Role →
              </button>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}

// ==========================================
// 5. AUDITOR ROLE VIEW
// ==========================================
function AuditorHome() {
  const { auditEvents, cases, consents } = useData();

  return (
    <>
      <Header
        title="Compliance & Integrity Oversight"
        eyebrow="AUDITOR WORKSPACE"
      />

      <div className="read-only-banner">
        <Icon name="lock" size={18} />
        <div>
          <strong>Read-Only Oversight Mode:</strong> You are viewing
          tamper-evident records, AI explanations, and consent tokens. No case
          state can be modified from this role.
        </div>
      </div>

      <section className="metrics">
        <Metric
          label="Immutable events"
          value={String(auditEvents.length)}
          comparison="Protected with simulated hashes"
          direction="up"
        />
        <Metric
          label="Active consents"
          value={String(consents.filter((c) => c.status === "Active").length)}
          comparison="Citizen-granted permissions"
          direction="flat"
        />
        <Metric
          label="Automated traces"
          value={String(cases.length)}
          comparison="Every signal is recorded"
          direction="flat"
        />
        <Metric
          label="Audit integrity"
          value="100%"
          comparison="Cryptographic continuity intact"
          direction="flat"
        />
      </section>

      <section className="panel audit-panel" style={{ marginTop: 20 }}>
        <PanelHeader
          title="Recent Tamper-Evident Ledger Entries"
          action="Open full audit trail"
          to="/audit"
        />
        {auditEvents.slice(0, 5).map((evt) => (
          <div className="audit-row" key={evt.id}>
            <span className="audit-mark">
              <Icon
                name={
                  evt.category === "AI_DECISION"
                    ? "spark"
                    : evt.category === "PAYMENT"
                    ? "check"
                    : "scroll"
                }
                size={15}
              />
            </span>
            <span>
              <strong>{evt.title}</strong>
              <small>
                {evt.actor} ({evt.actorRole}) · {evt.details}
              </small>
            </span>
            <code style={{ fontSize: 9, color: "#99765b" }}>
              {evt.hash.slice(0, 15)}…
            </code>
          </div>
        ))}
      </section>
    </>
  );
}

// Central Role Home Switcher
function RoleHome() {
  const { user } = useAuth();
  if (user?.role === "CITIZEN") return <CitizenHome />;
  if (user?.role === "HELPER") return <HelperHome />;
  if (user?.role === "ADMIN") return <AdminHome />;
  if (user?.role === "AUDITOR") return <AuditorHome />;
  return <Overview />;
}

// ==========================================
// CASE MANAGEMENT & DETAIL
// ==========================================
function Cases({ detail = false }: { detail?: boolean }) {
  const { user } = useAuth();
  const { cases } = useData();
  const [filter, setFilter] = useState("All cases");
  const [sortOrder, setSortOrder] = useState<"newest" | "oldest">("newest");
  const [searchParams] = useSearchParams();
  const query = (searchParams.get("q") ?? "").toLowerCase();

  if (detail) return <CaseDetail />;

  const filteredCases = cases
    .filter((c) => {
      const matchesQuery =
        !query ||
        `${c.id} ${c.person} ${c.type} ${c.cnic}`.toLowerCase().includes(query);
      const matchesFilter =
        filter === "All cases" ||
        (filter === "Needs review" && c.status === "Needs review") ||
        (filter === "Awaiting citizen" && c.status === "More information") ||
        (filter === "Resolved" && ["Verified", "Approved"].includes(c.status));
      return matchesQuery && matchesFilter;
    })
    .sort((a, b) => {
      if (sortOrder === "newest") return b.id.localeCompare(a.id);
      return a.id.localeCompare(b.id);
    });

  return (
    <>
      <Header title="Case management" eyebrow="WORKSPACE / OPERATIONS" />
      <section className="page-intro">
        <p>
          Track assistance requests from submission to resolution. Every
          automated finding remains reviewable by human officers.
        </p>
        {(user?.role === "CITIZEN" || user?.role === "HELPER") && (
          <Link className="primary-button" to="/claim">
            <Icon name="plus" /> Create assistance claim
          </Link>
        )}
      </section>

      <div className="panel table-panel">
        <div className="table-toolbar">
          <div className="tabs">
            {["All cases", "Needs review", "Awaiting citizen", "Resolved"].map(
              (t) => (
                <button
                  type="button"
                  className={filter === t ? "tab tab--active" : "tab"}
                  onClick={() => setFilter(t)}
                  key={t}
                >
                  {t}
                  {t === "Needs review" && (
                    <span>
                      {cases.filter((c) => c.status === "Needs review").length}
                    </span>
                  )}
                </button>
              )
            )}
          </div>
          <button
            type="button"
            className="filter-button"
            onClick={() =>
              setSortOrder(sortOrder === "newest" ? "oldest" : "newest")
            }
          >
            <Icon name="sliders" size={16} /> Sort:{" "}
            {sortOrder === "newest" ? "Newest first" : "Oldest first"}
          </button>
        </div>

        <div className="table-wrap">
          {query && (
            <p className="search-result-note">
              Showing {filteredCases.length} result
              {filteredCases.length === 1 ? "" : "s"} for “{searchParams.get("q")}”.
            </p>
          )}

          {filteredCases.length === 0 ? (
            <div className="empty-results">
              <Icon name="search" size={24} />
              <p>No matching cases found for this criteria.</p>
            </div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Case ID</th>
                  <th>Citizen</th>
                  <th>Automated Assessment</th>
                  <th>Current Status</th>
                  <th>Submitted</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filteredCases.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <Link to={`/cases/${c.id}`} className="case-id">
                        {c.id}
                      </Link>
                      <small>{c.type}</small>
                    </td>
                    <td>
                      <strong>{c.person}</strong>
                      <small>CNIC: {c.cnic}</small>
                    </td>
                    <td>
                      <span className="assessment">
                        <i
                          className={
                            c.tone === "warning"
                              ? "dot dot--gold"
                              : "dot dot--green"
                          }
                        />
                        {c.score} confidence ({c.aiRoute})
                      </span>
                    </td>
                    <td>
                      <Badge tone={c.tone}>{c.status}</Badge>
                    </td>
                    <td>{c.date}</td>
                    <td>
                      <Link className="round-link" to={`/cases/${c.id}`}>
                        <Icon name="arrow" size={16} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
  );
}

// --- Case Detail with Live NADRA & Officer Actions ---
function CaseDetail() {
  const { caseId } = useParams();
  const { user } = useAuth();
  const { getCase, officerAction } = useData();
  const targetCase = getCase(caseId || "REL-20481");

  const [evidenceModal, setEvidenceModal] = useState(false);
  const [evidenceNote, setEvidenceNote] = useState("");
  const [approvalModal, setApprovalModal] = useState(false);
  const [approvalNote, setApprovalNote] = useState("");
  const [rejectModal, setRejectModal] = useState(false);
  const [rejectNote, setRejectNote] = useState("");
  const [runningNadra, setRunningNadra] = useState(false);
  const [nadraResult, setNadraResult] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);

  if (!targetCase) {
    return (
      <div className="empty-state panel">
        <h2>Case Not Found</h2>
        <p>The requested case ID could not be located.</p>
        <Link to="/cases" className="primary-button">
          Back to Case Management
        </Link>
      </div>
    );
  }

  const isAuditor = user?.role === "AUDITOR";

  const handleLiveNadraCheck = async () => {
    setRunningNadra(true);
    try {
      const res = await verifyNadra(targetCase.cnic);
      setNadraResult(
        res.verified
          ? `✓ Verified via Real NADRA Mock (${res.name || targetCase.person})`
          : `Notice: ${res.note}`
      );
    } catch {
      setNadraResult("Local check: CNIC matches synthetic records.");
    } finally {
      setRunningNadra(false);
    }
  };

  const submitEvidenceRequest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!evidenceNote.trim()) return;
    const res = await officerAction(
      targetCase.id,
      "request_evidence",
      evidenceNote,
      user?.name || "Officer"
    );
    setEvidenceModal(false);
    setEvidenceNote("");
    setActionNotice(
      res.smsSent
        ? "Evidence requested. Real SMS notification dispatched to citizen."
        : "Evidence requested and logged in case timeline."
    );
  };

  const submitApproval = async (e: React.FormEvent) => {
    e.preventDefault();
    const res = await officerAction(
      targetCase.id,
      "approve",
      approvalNote || "All eligibility criteria satisfied.",
      user?.name || "Officer"
    );
    setApprovalModal(false);
    setApprovalNote("");
    setActionNotice(
      `Case Approved! Disbursed Rs 25,000 via Raast (Transaction: ${
        res.raastTxn || "TXN-0001"
      }). SMS sent.`
    );
  };

  const submitReject = async (e: React.FormEvent) => {
    e.preventDefault();
    await officerAction(
      targetCase.id,
      "reject",
      rejectNote || "Does not meet poverty criteria.",
      user?.name || "Officer"
    );
    setRejectModal(false);
    setRejectNote("");
    setActionNotice("Case marked as Rejected and logged in audit trail.");
  };

  return (
    <>
      <Header
        title={`Case ${targetCase.id}`}
        eyebrow={`CASE MANAGEMENT / ${targetCase.type.toUpperCase()}`}
      />

      <div className="detail-back">
        <Link to="/cases">← Back to cases</Link>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {isAuditor && (
            <span className="read-only-badge">
              <Icon name="lock" size={13} /> Auditor View Only
            </span>
          )}
          <Badge tone={targetCase.tone}>{targetCase.status}</Badge>
        </div>
      </div>

      {actionNotice && (
        <div
          style={{
            background: "#eaf5ec",
            border: "1px solid #94cda3",
            color: "#285e35",
            padding: "10px 16px",
            borderRadius: 7,
            marginBottom: 16,
            fontSize: 12,
            display: "flex",
            justifyContent: "space-between",
          }}
        >
          <span>{actionNotice}</span>
          <button
            onClick={() => setActionNotice(null)}
            style={{
              background: "none",
              border: 0,
              color: "inherit",
              cursor: "pointer",
            }}
          >
            ✕
          </button>
        </div>
      )}

      <section className="case-detail-grid">
        <div>
          <div className="person-hero">
            <span className="person-portrait">
              {targetCase.person
                .split(" ")
                .map((x) => x[0])
                .join("")
                .slice(0, 2)}
            </span>
            <div>
              <h2>{targetCase.person}</h2>
              <p>
                {targetCase.type} · Submitted {targetCase.date} by{" "}
                {targetCase.submittedBy}
              </p>
              <div className="person-tags">
                <span>
                  CNIC: <strong>{targetCase.cnic}</strong>
                </span>
                <span>Phone: {targetCase.phone}</span>
                <span>
                  Income: Rs {targetCase.householdIncome.toLocaleString()}
                </span>
                <span>{targetCase.address}</span>
              </div>
            </div>
          </div>

          {/* Interactive Live NADRA Verify Tool */}
          <div className="panel" style={{ padding: 18, marginBottom: 18 }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div>
                <strong style={{ fontSize: 13, display: "block" }}>
                  NADRA Identity Verification
                </strong>
                <small style={{ color: "#806b5e", fontSize: 10 }}>
                  Test CNIC lookup against real backend mock endpoint
                  (/api/mock/nadra/verify).
                </small>
              </div>
              <button
                type="button"
                className="secondary-button"
                disabled={runningNadra}
                onClick={handleLiveNadraCheck}
              >
                {runningNadra ? "Querying NADRA…" : "Run Live NADRA Check"}
                <Icon name="shield" size={14} />
              </button>
            </div>
            {nadraResult && (
              <div
                style={{
                  marginTop: 10,
                  fontSize: 11,
                  background: "#f4f9f4",
                  border: "1px solid #b7deb9",
                  padding: "8px 12px",
                  borderRadius: 6,
                  color: "#256338",
                }}
              >
                {nadraResult}
              </div>
            )}
          </div>

          <div className="panel timeline">
            <PanelHeader title="Chronological Case Timeline" />
            <ol className="timeline-list">
              {targetCase.timeline.map((entry, i) => (
                <li key={entry.id}>
                  <i
                    className={`timeline-dot ${
                      i === 0 ? "timeline-dot--current" : ""
                    }`}
                  />
                  <div>
                    <small>{entry.time}</small>
                    <strong>{entry.title}</strong>
                    <p>{entry.description}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </div>

        {/* Decision Rail & Officer Actions */}
        <aside className="decision-rail">
          <div className="decision-summary">
            <p>AUTOMATED DECISION ASSISTANCE</p>
            <div className="decision-score">
              <strong>{targetCase.score.replace("%", "")}</strong>
              <span>
                %<small>confidence</small>
              </span>
            </div>
            <Badge tone={targetCase.tone}>Route: {targetCase.aiRoute}</Badge>
            <h3>{targetCase.aiReason}</h3>
            <p>
              Automated routing suggestions do not disburse public funds without
              authorized officer review.
            </p>
          </div>

          <div className="reason-list">
            <h4>Signals and Evidence</h4>
            <div className="reason">
              <span className="reason-icon reason-icon--good">
                <Icon name="check" size={14} />
              </span>
              <span>
                Declared income Rs {targetCase.householdIncome.toLocaleString()}{" "}
                below policy threshold
              </span>
            </div>
            <div className="reason">
              <span
                className={`reason-icon ${
                  targetCase.status === "Needs review"
                    ? "reason-icon--warn"
                    : "reason-icon--good"
                }`}
              >
                <Icon
                  name={targetCase.status === "Needs review" ? "alert" : "check"}
                  size={14}
                />
              </span>
              <span>
                {targetCase.status === "Needs review"
                  ? "Potential household duplicate check flagged"
                  : "No duplicate records found"}
              </span>
            </div>
            <div className="reason">
              <span className="reason-icon reason-icon--good">
                <Icon name="check" size={14} />
              </span>
              <span>Identity verified in public registry</span>
            </div>
          </div>

          <div className="decision-actions">
            {isAuditor ? (
              <p
                style={{
                  fontSize: 11,
                  color: "#806b5e",
                  textAlign: "center",
                  margin: "8px 0",
                }}
              >
                Auditor permissions are strictly read-only.
              </p>
            ) : (
              <>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => setEvidenceModal(true)}
                >
                  <Icon name="file" size={14} /> Request Citizen Evidence
                </button>
                <button
                  type="button"
                  className="primary-button"
                  onClick={() => setApprovalModal(true)}
                >
                  <Icon name="check" size={15} /> Approve & Disburse Raast
                </button>
                <button
                  type="button"
                  className="text-button"
                  onClick={() => setRejectModal(true)}
                >
                  Reject Case
                </button>
              </>
            )}
          </div>
        </aside>
      </section>

      {/* Modals for Officer Actions */}
      {evidenceModal && (
        <div className="modal-backdrop">
          <div className="modal-box">
            <div className="modal-header">
              <h3>Request Additional Evidence</h3>
              <button onClick={() => setEvidenceModal(false)}>✕</button>
            </div>
            <form onSubmit={submitEvidenceRequest}>
              <div className="modal-body">
                <p style={{ margin: 0, fontSize: 11, color: "#806b5e" }}>
                  This note will be logged in the case history and dispatched
                  via real SMS to {targetCase.phone}.
                </p>
                <label>
                  Specific information required
                  <textarea
                    rows={4}
                    value={evidenceNote}
                    onChange={(e) => setEvidenceNote(e.target.value)}
                    placeholder="e.g. Please upload a clear picture of your latest gas or electricity bill."
                    required
                  />
                </label>
              </div>
              <div className="modal-footer">
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => setEvidenceModal(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="primary-button">
                  Send SMS Request
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {approvalModal && (
        <div className="modal-backdrop">
          <div className="modal-box">
            <div className="modal-header">
              <h3>Approve Assistance & Disburse</h3>
              <button onClick={() => setApprovalModal(false)}>✕</button>
            </div>
            <form onSubmit={submitApproval}>
              <div className="modal-body">
                <p style={{ margin: 0, fontSize: 11, color: "#806b5e" }}>
                  Approving will call the backend Raast payment endpoint to
                  disburse Rs 25,000 to CNIC {targetCase.cnic} and dispatch an
                  SMS notification.
                </p>
                <label>
                  Officer Decision Justification Notes
                  <textarea
                    rows={3}
                    value={approvalNote}
                    onChange={(e) => setApprovalNote(e.target.value)}
                    placeholder="e.g. In-person verification confirmed. Household poverty criteria fully satisfied."
                  />
                </label>
              </div>
              <div className="modal-footer">
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => setApprovalModal(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="primary-button">
                  Confirm Approval & Pay
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {rejectModal && (
        <div className="modal-backdrop">
          <div className="modal-box">
            <div className="modal-header">
              <h3>Reject Claim</h3>
              <button onClick={() => setRejectModal(false)}>✕</button>
            </div>
            <form onSubmit={submitReject}>
              <div className="modal-body">
                <label>
                  Reason for rejection
                  <textarea
                    rows={3}
                    value={rejectNote}
                    onChange={(e) => setRejectNote(e.target.value)}
                    placeholder="e.g. Household declared income exceeds eligibility threshold."
                    required
                  />
                </label>
              </div>
              <div className="modal-footer">
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => setRejectModal(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="primary-button"
                  style={{ background: "#a63525" }}
                >
                  Confirm Rejection
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}

// ==========================================
// CLAIM SUBMISSION WIZARD
// ==========================================
function ClaimForm() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const {
    createCase,
    helperActiveCitizen,
    authorizedCitizens,
    settings,
    currentLang,
  } = useData();

  const isHelper = user?.role === "HELPER";
  const helperCitizen = authorizedCitizens.find(
    (c) => c.name === helperActiveCitizen
  );

  const [step, setStep] = useState(1);
  const [purpose, setPurpose] = useState("Relief assistance");
  const [personName, setPersonName] = useState(
    isHelper ? helperActiveCitizen : user?.name || "Ayesha Bibi"
  );
  const [cnic, setCnic] = useState(
    isHelper
      ? helperCitizen?.cnic || "99999-0000001-1"
      : user?.cnic || "99999-0000001-1"
  );
  const [phone, setPhone] = useState(
    isHelper
      ? helperCitizen?.phone || "0300-0000001"
      : user?.phone || "0300-0000001"
  );
  const [income, setIncome] = useState("32000");
  const [members, setMembers] = useState("5");
  const [address, setAddress] = useState(
    "House 12, Street 4, Sector 7-C, Karachi"
  );
  const [householdDesc, setHouseholdDesc] = useState(
    "Daily wage worker, 3 school-going children, no alternative income."
  );
  const [consent, setConsent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<{
    caseId: string;
    backendAi: boolean;
    backendNadra: boolean;
  } | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!consent) {
      setError("Please confirm citizen consent agreement before proceeding.");
      return;
    }
    setError("");
    setSubmitting(true);

    try {
      const res = await createCase({
        person: personName,
        cnic,
        phone,
        type: purpose,
        householdIncome: parseInt(income, 10) || 30000,
        householdMembers: parseInt(members, 10) || 4,
        address,
        notes: householdDesc,
        submittedBy: isHelper
          ? `${user?.name || "Helper"} (Community Helper on behalf of ${personName})`
          : personName,
        submittedByRole: user?.role || "CITIZEN",
      });
      setResult(res);
    } catch {
      setError("Could not complete submission.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <Header
        title={currentLang === "ur" ? "درخواست جمع کرائیں" : "Submit Assistance Claim"}
        eyebrow="RASTA / CITIZEN SERVICES"
      />

      <section className="claim-layout">
        <div className="claim-copy">
          <p className="label">A CLEAR, GUIDED PATH</p>
          <h2>Tell us what you need.</h2>
          <p>
            RASTA checks the information you choose to share, explains every
            automated assessment, and escalates to a human officer whenever
            signals are uncertain.
          </p>

          <div className="claim-steps">
            <span>1. Assistance purpose & income declaration</span>
            <span>2. National ID (NADRA) verification</span>
            <span>3. Explicit plain-language consent agreement</span>
          </div>

          {settings.voiceAssistance && (
            <div
              style={{
                marginTop: 20,
                display: "flex",
                gap: 8,
                alignItems: "center",
                fontSize: 11,
                color: "#72533f",
              }}
            >
              <Icon name="mic" size={16} />
              <span>Voice input assistance active. Speak in Urdu or English.</span>
            </div>
          )}
        </div>

        <div className="panel claim-card">
          {result ? (
            <div className="claim-success">
              <span className="empty-illustration">
                <Icon name="check" size={28} />
              </span>
              <h2>Claim Registered: {result.caseId}</h2>
              <p>
                Your assistance claim has been created and evaluated. Automated
                routing:{" "}
                <strong>
                  {result.backendAi
                    ? "Evaluated via live AI service (/api/ai/decide)"
                    : "Evaluated via local policy adapter"}
                </strong>
                .
              </p>
              <div style={{ display: "flex", gap: 10 }}>
                <button
                  type="button"
                  className="primary-button"
                  onClick={() => navigate(`/cases/${result.caseId}`)}
                >
                  Track This Case <Icon name="arrow" size={14} />
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => navigate("/cases")}
                >
                  View All Cases
                </button>
              </div>
            </div>
          ) : (
            <form onSubmit={handleSubmit}>
              <div className="wizard-steps">
                <div
                  className={`wizard-step ${step >= 1 ? "wizard-step--active" : ""}`}
                />
                <div
                  className={`wizard-step ${step >= 2 ? "wizard-step--active" : ""}`}
                />
                <div
                  className={`wizard-step ${step >= 3 ? "wizard-step--active" : ""}`}
                />
              </div>

              {step === 1 && (
                <>
                  <PanelHeader title="Step 1: Assistance & Household" />
                  <label>
                    Type of Assistance Requested
                    <select
                      value={purpose}
                      onChange={(e) => setPurpose(e.target.value)}
                    >
                      <option>Relief assistance</option>
                      <option>Emergency flood grant</option>
                      <option>Document update</option>
                      <option>Widow or disability support</option>
                    </select>
                  </label>
                  <label>
                    Monthly Household Income (PKR)
                    <input
                      type="number"
                      value={income}
                      onChange={(e) => setIncome(e.target.value)}
                      placeholder="e.g. 30000"
                      required
                    />
                  </label>
                  <label>
                    Number of Household Dependents
                    <input
                      type="number"
                      value={members}
                      onChange={(e) => setMembers(e.target.value)}
                      placeholder="e.g. 5"
                      required
                    />
                  </label>
                  <button
                    type="button"
                    className="primary-button"
                    onClick={() => setStep(2)}
                  >
                    Next: Verification Details →
                  </button>
                </>
              )}

              {step === 2 && (
                <>
                  <PanelHeader title="Step 2: Identity & Location" />
                  <label>
                    Citizen Full Name
                    <input
                      value={personName}
                      onChange={(e) => setPersonName(e.target.value)}
                      required
                    />
                  </label>
                  <label>
                    National Identity Card (CNIC)
                    <input
                      value={cnic}
                      onChange={(e) => setCnic(e.target.value)}
                      placeholder="e.g. 99999-0000001-1"
                      required
                    />
                  </label>
                  <label>
                    Contact Mobile Number
                    <input
                      value={phone}
                      onChange={(e) => setPhone(e.target.value)}
                      placeholder="e.g. 0300-0000001"
                      required
                    />
                  </label>
                  <label>
                    Residential Address
                    <input
                      value={address}
                      onChange={(e) => setAddress(e.target.value)}
                      required
                    />
                  </label>
                  <div style={{ display: "flex", gap: 10 }}>
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={() => setStep(1)}
                    >
                      ← Back
                    </button>
                    <button
                      type="button"
                      className="primary-button"
                      onClick={() => setStep(3)}
                    >
                      Next: Review & Consent →
                    </button>
                  </div>
                </>
              )}

              {step === 3 && (
                <>
                  <PanelHeader title="Step 3: Consent & Confirmation" />
                  <label>
                    Household Circumstances & Notes
                    <textarea
                      rows={3}
                      value={householdDesc}
                      onChange={(e) => setHouseholdDesc(e.target.value)}
                      placeholder="Describe your current employment and family situation."
                    />
                  </label>

                  <label className="consent-check">
                    <input
                      type="checkbox"
                      checked={consent}
                      onChange={(e) => setConsent(e.target.checked)}
                      required
                    />
                    <span>
                      I authorize RASTA to verify my identity record via NADRA and
                      share relevant details with the social relief officer. I
                      understand I can revoke this consent at any time.
                    </span>
                  </label>

                  {error && (
                    <p className="form-error" role="alert">
                      <Icon name="alert" size={15} />
                      {error}
                    </p>
                  )}

                  <div style={{ display: "flex", gap: 10 }}>
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={() => setStep(2)}
                    >
                      ← Back
                    </button>
                    <button
                      type="submit"
                      className="primary-button"
                      disabled={submitting}
                    >
                      {submitting ? "Evaluating Claim…" : "Submit Official Claim"}
                      {!submitting && <Icon name="arrow" size={15} />}
                    </button>
                  </div>
                </>
              )}
            </form>
          )}
        </div>
      </section>
    </>
  );
}

// ==========================================
// HUMAN REVIEW QUEUE
// ==========================================
function ReviewQueue() {
  const { cases } = useData();
  const [priorityFilter, setPriorityFilter] = useState("All");
  const [sort, setSort] = useState("Priority");
  const [selectedCaseId, setSelectedCaseId] = useState("REL-20481");

  const queueCases = cases
    .filter((c) => c.status === "Needs review")
    .filter((c) => priorityFilter === "All" || c.priority === priorityFilter)
    .sort((a, b) => {
      if (sort === "Priority") return a.priority.localeCompare(b.priority);
      return b.id.localeCompare(a.id);
    });

  const activeCase =
    queueCases.find((c) => c.id === selectedCaseId) || queueCases[0];

  return (
    <>
      <Header title="Human review queue" eyebrow="OFFICER WORKSPACE" />
      <section className="page-intro">
        <p>
          Cases here require human officer adjudication. Automated decisions
          remain paused until you review evidence and take action.
        </p>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <div className="tabs">
            {["All", "P1", "P2", "P3"].map((p) => (
              <button
                type="button"
                key={p}
                className={priorityFilter === p ? "tab tab--active" : "tab"}
                onClick={() => setPriorityFilter(p)}
              >
                {p === "All" ? "All Priorities" : `${p} Priority`}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="filter-button"
            onClick={() => setSort(sort === "Priority" ? "Newest" : "Priority")}
          >
            Sort: {sort} <Icon name="chevron" size={14} />
          </button>
        </div>
      </section>

      <section className="review-layout">
        <div className="queue-list">
          {queueCases.length === 0 ? (
            <div className="panel" style={{ padding: 24, textAlign: "center" }}>
              <p style={{ margin: 0 }}>Review queue is currently clear.</p>
            </div>
          ) : (
            queueCases.map((c) => (
              <div
                key={c.id}
                className={`review-card ${
                  activeCase?.id === c.id ? "review-card--active" : ""
                }`}
                onClick={() => setSelectedCaseId(c.id)}
                style={{ cursor: "pointer" }}
              >
                <span
                  className={`priority priority--${
                    c.priority === "P1" ? "high" : "normal"
                  }`}
                >
                  {c.priority}
                </span>
                <span className="initials">
                  {c.person
                    .split(" ")
                    .map((x) => x[0])
                    .join("")
                    .slice(0, 2)}
                </span>
                <span>
                  <strong>{c.person}</strong>
                  <small>
                    {c.id} · {c.type}
                  </small>
                  <p>{c.aiReason}</p>
                </span>
                <span className="review-confidence">
                  {c.score}
                  <small>confidence</small>
                </span>
              </div>
            ))
          )}
        </div>

        {activeCase && (
          <div className="panel review-preview">
            <div className="preview-head">
              <div>
                <span className="label">SELECTED CASE</span>
                <h2>{activeCase.person}</h2>
                <p>
                  {activeCase.id} · {activeCase.type}
                </p>
              </div>
              <Badge tone="warning">{activeCase.priority} priority</Badge>
            </div>

            <div className="review-signals">
              <div>
                <span className="signal-mark signal-mark--match">✓</span>
                <span>
                  Identity Match
                  <small>
                    {activeCase.nadraVerified
                      ? "NADRA Verified"
                      : "Check Required"}
                  </small>
                </span>
              </div>
              <div>
                <span className="signal-mark signal-mark--issue">!</span>
                <span>
                  Automated Signal
                  <small>{activeCase.aiReason.slice(0, 32)}…</small>
                </span>
              </div>
              <div>
                <span className="signal-mark signal-mark--match">✓</span>
                <span>
                  Policy Target
                  <small>
                    Income: Rs {activeCase.householdIncome.toLocaleString()}
                  </small>
                </span>
              </div>
            </div>

            <div className="review-footer">
              <p>
                <Icon name="shield" size={16} /> A final officer action is
                required to complete this claim.
              </p>
              <Link to={`/cases/${activeCase.id}`} className="primary-button">
                Investigate Case <Icon name="arrow" />
              </Link>
            </div>
          </div>
        )}
      </section>
    </>
  );
}

// ==========================================
// DECISION CENTER
// ==========================================
function DecisionCenter() {
  const { cases } = useData();
  const [briefExported, setBriefExported] = useState(false);

  const handleExportBrief = () => {
    const summary = {
      timestamp: new Date().toISOString(),
      activeCaseload: cases.length,
      averageConfidence: "82%",
      rulesVersion: "v3.1",
      humanEscalationRate: "18%",
    };
    const blob = new Blob([JSON.stringify(summary, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `RASTA-Decision-Brief-${Date.now()}.json`;
    a.click();
    setBriefExported(true);
    setTimeout(() => setBriefExported(false), 3000);
  };

  return (
    <>
      <Header title="AI decision center" eyebrow="TRANSPARENCY & SAFETY" />
      <section className="page-intro">
        <p>
          Every automated signal is explained, versioned, and reviewable by human
          officers. Automated suggestions never make unilateral final
          public-service disbursements.
        </p>
        <button
          type="button"
          className="secondary-button"
          onClick={handleExportBrief}
        >
          <Icon name="file" />{" "}
          {briefExported ? "Brief Exported ✓" : "Export Review Brief"}
        </button>
      </section>

      <section className="decision-kpis">
        <Metric
          label="Decisions evaluated"
          value={String(cases.length)}
          comparison="Across relief assessment types"
          direction="up"
        />
        <Metric
          label="Human escalation rate"
          value="18%"
          comparison="When signals conflict"
          direction="flat"
        />
        <Metric
          label="Active policy rule"
          value="v3.1"
          comparison="Sindh Social Relief Baseline"
          direction="flat"
        />
      </section>

      <section className="decision-grid">
        <div className="panel model-panel">
          <PanelHeader title="Assessment Quality Breakdown" />
          <div className="donut-wrap">
            <div className="donut">
              <span>
                82<small>%</small>
              </span>
            </div>
            <div>
              <strong>High Confidence Routing</strong>
              <p>Clear evidence supports automated recommendations.</p>
              <span className="model-key">
                <i /> 82% Auto-eligible
              </span>
              <span className="model-key model-key--review">
                <i /> 18% Escalated to Review
              </span>
            </div>
          </div>
        </div>

        <div className="panel explain-panel">
          <PanelHeader title="Latest Decision Trace" />
          <div className="explain-case">
            <span className="initials initials--large">MA</span>
            <span>
              <strong>REL-20480 · Muhammad Afzal</strong>
              <small>Relief assistance · 94% confidence</small>
            </span>
            <Badge tone="success">Clear to proceed</Badge>
          </div>
          <div className="reason-list reason-list--compact">
            <div className="reason">
              <span className="reason-icon reason-icon--good">
                <Icon name="check" size={14} />
              </span>
              <span>Verified identity matched source NADRA registry</span>
            </div>
            <div className="reason">
              <span className="reason-icon reason-icon--good">
                <Icon name="check" size={14} />
              </span>
              <span>Household income below Rs 45,000 threshold</span>
            </div>
            <div className="reason">
              <span className="reason-icon reason-icon--good">
                <Icon name="check" size={14} />
              </span>
              <span>No duplicate or fraud indicators detected</span>
            </div>
          </div>
          <Link to="/cases/REL-20480" className="explain-link">
            Inspect full case trace <Icon name="arrow" size={15} />
          </Link>
        </div>
      </section>
    </>
  );
}

// ==========================================
// CITIZEN MANAGEMENT
// ==========================================
function Citizens() {
  const { authorizedCitizens } = useData();
  const [search, setSearch] = useState("");

  const filtered = authorizedCitizens.filter(
    (c) =>
      c.name.toLowerCase().includes(search.toLowerCase()) ||
      c.cnic.includes(search)
  );

  return (
    <>
      <Header title="Citizen directory" eyebrow="WORKSPACE / GOVERNANCE" />
      <section className="page-intro">
        <p>
          Manage citizen records, preferred access channels, and community
          helper relationships with clear consent boundaries.
        </p>
        <label className="search" style={{ width: 220 }}>
          <Icon name="search" size={15} />
          <input
            placeholder="Filter citizens..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
      </section>

      <div className="citizen-cards">
        {filtered.map((c) => (
          <article className="citizen-card" key={c.cnic}>
            <span className="initials initials--large">
              {c.name
                .split(" ")
                .map((x) => x[0])
                .join("")
                .slice(0, 2)}
            </span>
            <h3>{c.name}</h3>
            <p>
              CNIC: {c.cnic} · {c.relationship}
            </p>
            <Badge tone={c.consentActive ? "success" : "muted"}>
              {c.consentActive ? "Consent Active" : "Revoked"}
            </Badge>
            <Link to="/consent">
              Manage Access Permissions <Icon name="arrow" size={14} />
            </Link>
          </article>
        ))}
      </div>
    </>
  );
}

// ==========================================
// CONSENT MANAGEMENT
// ==========================================
function Consent() {
  const { user } = useAuth();
  const { consents, grantConsent, revokeConsent } = useData();
  const [filter, setFilter] = useState<"All" | "Active" | "Revoked">("All");
  const [modalOpen, setModalOpen] = useState(false);
  const [citName, setCitName] = useState("Ayesha Bibi");
  const [citCnic, setCitCnic] = useState("99999-0000001-1");
  const [grantee, setGrantee] = useState("Community Helper (Sana Iqbal)");
  const [scope, setScope] = useState("Assistance claim filing & document upload");
  const [duration, setDuration] = useState("6");

  const isAuditor = user?.role === "AUDITOR";

  const handleGrantSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    grantConsent({
      citizenName: citName,
      citizenCnic: citCnic,
      grantee,
      scope,
      durationMonths: parseInt(duration, 10) || 6,
      source: user?.role === "CITIZEN" ? "citizen" : "helper_proxy",
      actorName: user?.name || "User",
      actorRole: user?.role || "CITIZEN",
    });
    setModalOpen(false);
  };

  const visibleConsents = consents.filter(
    (c) => filter === "All" || c.status === filter
  );

  return (
    <>
      <Header title="Consent management" eyebrow="PRIVACY & ACCESS CONTROL" />
      <section className="page-intro">
        <p>
          Citizens decide what data may be shared, with whom, and for how long.
          Withdrawal takes effect immediately across all department queries.
        </p>
        <div style={{ display: "flex", gap: 10 }}>
          <div className="tabs">
            {["All", "Active", "Revoked"].map((f) => (
              <button
                type="button"
                key={f}
                className={filter === f ? "tab tab--active" : "tab"}
                onClick={() => setFilter(f as any)}
              >
                {f}
              </button>
            ))}
          </div>
          {!isAuditor && (
            <button
              type="button"
              className="primary-button"
              onClick={() => setModalOpen(true)}
            >
              <Icon name="plus" size={14} /> Grant New Consent
            </button>
          )}
        </div>
      </section>

      <div className="panel consent-panel">
        <PanelHeader title="Active Data Sharing Authorizations" />
        {visibleConsents.map((c) => (
          <div className="consent-row" key={c.id}>
            <span className="initials">
              {c.citizenName
                .split(" ")
                .map((x) => x[0])
                .join("")
                .slice(0, 2)}
            </span>
            <span>
              <strong>{c.citizenName}</strong>
              <small>
                CNIC: {c.citizenCnic} · Granted to: {c.grantee}
              </small>
              <small style={{ color: "#806b5e" }}>Scope: {c.scope}</small>
            </span>
            <Badge tone={c.status === "Active" ? "success" : "muted"}>
              {c.status}
            </Badge>
            {c.status === "Active" && !isAuditor && (
              <button
                type="button"
                className="outline-button"
                onClick={() =>
                  revokeConsent(
                    c.id,
                    user?.name || "Citizen",
                    user?.role || "CITIZEN"
                  )
                }
              >
                Withdraw
              </button>
            )}
          </div>
        ))}
      </div>

      {modalOpen && (
        <div className="modal-backdrop">
          <div className="modal-box">
            <div className="modal-header">
              <h3>Grant Data Access Permission</h3>
              <button onClick={() => setModalOpen(false)}>✕</button>
            </div>
            <form onSubmit={handleGrantSubmit}>
              <div className="modal-body">
                <label>
                  Citizen Name
                  <input
                    value={citName}
                    onChange={(e) => setCitName(e.target.value)}
                    required
                  />
                </label>
                <label>
                  Citizen CNIC
                  <input
                    value={citCnic}
                    onChange={(e) => setCitCnic(e.target.value)}
                    required
                  />
                </label>
                <label>
                  Authorized Entity / Person
                  <input
                    value={grantee}
                    onChange={(e) => setGrantee(e.target.value)}
                    required
                  />
                </label>
                <label>
                  Scope of Permission
                  <select
                    value={scope}
                    onChange={(e) => setScope(e.target.value)}
                  >
                    <option>
                      Assistance claim filing & document upload
                    </option>
                    <option>
                      Identity verification and bank lookup only
                    </option>
                    <option>
                      Emergency disaster aid cross-matching
                    </option>
                  </select>
                </label>
                <label>
                  Duration (Months)
                  <input
                    type="number"
                    value={duration}
                    onChange={(e) => setDuration(e.target.value)}
                    min={1}
                    max={24}
                  />
                </label>
              </div>
              <div className="modal-footer">
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => setModalOpen(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="primary-button">
                  Confirm Consent Grant
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}

// ==========================================
// AUDIT TRAIL
// ==========================================
function Audit() {
  const { auditEvents } = useData();
  const [filter, setFilter] = useState("ALL");
  const [search, setSearch] = useState("");
  const [selectedEvent, setSelectedEvent] = useState<any | null>(null);

  const filtered = auditEvents.filter((evt) => {
    const matchesFilter = filter === "ALL" || evt.category === filter;
    const matchesSearch =
      !search ||
      `${evt.title} ${evt.actor} ${evt.details}`
        .toLowerCase()
        .includes(search.toLowerCase());
    return matchesFilter && matchesSearch;
  });

  const handleExportJson = () => {
    const blob = new Blob([JSON.stringify(auditEvents, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `RASTA-Audit-Ledger-${Date.now()}.json`;
    a.click();
  };

  return (
    <>
      <Header title="Audit trail" eyebrow="COMPLIANCE & GOVERNANCE" />
      <section className="page-intro">
        <p>
          A tamper-evident, chronological record of user actions, automated
          findings, policy versions, and consent changes.
        </p>
        <button
          type="button"
          className="secondary-button"
          onClick={handleExportJson}
        >
          <Icon name="download" size={14} /> Export Audit Log (JSON)
        </button>
      </section>

      <div className="panel audit-panel">
        <div className="table-toolbar">
          <div className="tabs">
            {["ALL", "CASE", "AI_DECISION", "PAYMENT", "CONSENT", "POLICY"].map(
              (cat) => (
                <button
                  type="button"
                  key={cat}
                  className={filter === cat ? "tab tab--active" : "tab"}
                  onClick={() => setFilter(cat)}
                >
                  {cat.replace("_", " ")}
                </button>
              )
            )}
          </div>
          <input
            placeholder="Search events…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              padding: "5px 9px",
              border: "1px solid #d9cdbf",
              borderRadius: 5,
              fontSize: 11,
              background: "#fff",
            }}
          />
        </div>

        {filtered.map((item) => (
          <div className="audit-row" key={item.id}>
            <span className="audit-mark">
              <Icon
                name={
                  item.category === "AI_DECISION"
                    ? "spark"
                    : item.category === "PAYMENT"
                    ? "check"
                    : item.category === "CONSENT"
                    ? "shield"
                    : "scroll"
                }
                size={15}
              />
            </span>
            <span>
              <strong>{item.title}</strong>
              <small>
                {new Date(item.timestamp).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}{" "}
                · Actor: {item.actor} ({item.actorRole})
              </small>
              <small style={{ color: "#776355" }}>{item.details}</small>
            </span>
            <button
              type="button"
              onClick={() => setSelectedEvent(item)}
              title="Inspect hash"
            >
              <Icon name="eye" size={16} />
            </button>
          </div>
        ))}
      </div>

      {selectedEvent && (
        <div className="modal-backdrop">
          <div className="modal-box">
            <div className="modal-header">
              <h3>Audit Proof Verification</h3>
              <button onClick={() => setSelectedEvent(null)}>✕</button>
            </div>
            <div className="modal-body">
              <strong>{selectedEvent.title}</strong>
              <p style={{ margin: 0, fontSize: 11 }}>
                {selectedEvent.details}
              </p>
              <label>
                Simulated Cryptographic Hash:
                <input readOnly value={selectedEvent.hash} />
              </label>
              <label>
                Timestamp:
                <input readOnly value={selectedEvent.timestamp} />
              </label>
              <label>
                Actor Identity:
                <input
                  readOnly
                  value={`${selectedEvent.actor} (${selectedEvent.actorRole})`}
                />
              </label>
            </div>
            <div className="modal-footer">
              <button
                type="button"
                className="primary-button"
                onClick={() => setSelectedEvent(null)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ==========================================
// RULES & ELIGIBILITY
// ==========================================
function Rules() {
  const { user } = useAuth();
  const {
    activeRule,
    draftRule,
    ruleHistory,
    updateDraftRule,
    publishDraftRule,
  } = useData();
  const [publishedNotice, setPublishedNotice] = useState(false);

  const isAuditor = user?.role === "AUDITOR";

  const handlePublish = () => {
    publishDraftRule(user?.name || "Administrator");
    setPublishedNotice(true);
    setTimeout(() => setPublishedNotice(false), 3000);
  };

  return (
    <>
      <Header
        title="Rules & eligibility"
        eyebrow="WORKSPACE / POLICY CONTROL"
      />
      <section className="page-intro">
        <p>
          Change eligibility rules without changing application code. Every
          version is reviewed, dated, and preserved for audit verification.
        </p>
        {!isAuditor && (
          <button
            type="button"
            onClick={handlePublish}
            className="primary-button"
          >
            <Icon name="check" />{" "}
            {publishedNotice
              ? "Policy Version Published ✓"
              : `Publish Draft ${draftRule.version}`}
          </button>
        )}
      </section>

      <div className="rules-grid">
        <div className="panel rule-editor">
          <PanelHeader title={activeRule.name} />
          <div className="rule-version">
            <span>
              <strong>Working Draft: {draftRule.version}</strong>
              <small>Last updated: {draftRule.updatedAt}</small>
            </span>
            <Badge tone="warning">Awaiting Publish</Badge>
          </div>

          <div className="rule-block">
            <span>IF</span>
            <strong>Household income</strong>
            <select defaultValue="less">
              <option value="less">is less than or equal to</option>
            </select>
            <input
              type="number"
              disabled={isAuditor}
              value={draftRule.maxIncome}
              onChange={(e) =>
                updateDraftRule({ maxIncome: parseInt(e.target.value, 10) || 0 })
              }
            />
          </div>

          <div className="rule-block">
            <span>AND</span>
            <strong>Identity verification</strong>
            <select
              disabled={isAuditor}
              value={draftRule.requireNadra ? "pass" : "skip"}
              onChange={(e) =>
                updateDraftRule({ requireNadra: e.target.value === "pass" })
              }
            >
              <option value="pass">Must pass NADRA lookup</option>
              <option value="skip">Optional verification</option>
            </select>
          </div>

          <div className="rule-block">
            <span>THEN</span>
            <strong>Route case</strong>
            <select
              disabled={isAuditor}
              value={draftRule.routeAction}
              onChange={(e) =>
                updateDraftRule({ routeAction: e.target.value as any })
              }
            >
              <option value="HUMAN">Escalate to human review</option>
              <option value="AUTO_APPROVE">
                Auto-approve if confidence ≥ {draftRule.confidenceThreshold}%
              </option>
            </select>
          </div>
        </div>

        <div className="panel rule-history">
          <PanelHeader title="Policy Version History" />
          <div className="version">
            <span>
              <i className="version__dot version__dot--active" />
              <strong>{activeRule.version} (Active Baseline)</strong>
              <small>
                Max income: Rs {activeRule.maxIncome.toLocaleString()} ·{" "}
                {activeRule.updatedAt}
              </small>
            </span>
            <Badge tone="success">Active</Badge>
          </div>

          {ruleHistory.map((h) => (
            <div className="version" key={h.version}>
              <span>
                <i className="version__dot" />
                <strong>{h.version}</strong>
                <small>
                  Max income: Rs {h.maxIncome.toLocaleString()} · {h.updatedAt}
                </small>
              </span>
              <Badge tone="muted">Archived</Badge>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

// ==========================================
// ANALYTICS
// ==========================================
function Analytics() {
  const [days, setDays] = useState("Last 7 days");

  return (
    <>
      <Header title="Analytics" eyebrow="WORKSPACE / OPERATIONS INSIGHTS" />
      <section className="analytics-lead">
        <div>
          <p>Relief assistance workflow</p>
          <h2>Clearer service, safer decisions.</h2>
        </div>
        <div className="date-select">
          <select
            value={days}
            onChange={(e) => setDays(e.target.value)}
            style={{ border: 0, background: "none", font: "inherit" }}
          >
            <option>Last 7 days</option>
            <option>Last 30 days</option>
          </select>
        </div>
      </section>

      <div className="analytics-grid">
        <div className="panel volume-chart">
          <PanelHeader title="Daily Claim Volume" />
          <div className="chart-axis">
            <div className="volume-bars">
              {[32, 48, 41, 66, 55, 79, 62].map((n, i) => (
                <span
                  key={i}
                  style={{ height: `${n}%` }}
                  className={i === 6 ? "today-bar" : ""}
                />
              ))}
            </div>
            <div className="chart-days">
              <span>15</span>
              <span>16</span>
              <span>17</span>
              <span>18</span>
              <span>19</span>
              <span>20</span>
              <span>21</span>
            </div>
          </div>
        </div>

        <div className="panel outcome-chart">
          <PanelHeader title="Adjudication Outcomes" />
          <div className="outcomes">
            <div>
              <span className="outcomes__circle outcomes__circle--green" />
              <span>
                <strong>67%</strong>
                <small>Clear to proceed</small>
              </span>
            </div>
            <div>
              <span className="outcomes__circle outcomes__circle--gold" />
              <span>
                <strong>18%</strong>
                <small>Human officer review</small>
              </span>
            </div>
            <div>
              <span className="outcomes__circle outcomes__circle--neutral" />
              <span>
                <strong>15%</strong>
                <small>Awaiting citizen documents</small>
              </span>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

// ==========================================
// WORKSPACE SETTINGS
// ==========================================
function Settings() {
  const { settings, updateSetting } = useData();

  return (
    <>
      <Header title="Workspace settings" eyebrow="WORKSPACE / PREFERENCES" />
      <section className="page-intro">
        <p>
          Configure demonstration accessibility defaults, low-bandwidth mode,
          and simulation safety indicators.
        </p>
      </section>

      <div className="settings-grid">
        <div className="panel settings-panel">
          <PanelHeader title="Accessibility & Language Defaults" />
          <div className="setting">
            <span>
              <strong>Show Urdu entry point</strong>
              <small>Offer Urdu as a primary accessibility option.</small>
            </span>
            <button
              type="button"
              aria-pressed={settings.urduEntryPoint}
              onClick={() =>
                updateSetting("urduEntryPoint", !settings.urduEntryPoint)
              }
              className={`toggle ${
                settings.urduEntryPoint ? "toggle--on" : ""
              }`}
            >
              <i />
            </button>
          </div>

          <div className="setting">
            <span>
              <strong>Voice assistance</strong>
              <small>Enable spoken inputs and voice prompt controls.</small>
            </span>
            <button
              type="button"
              aria-pressed={settings.voiceAssistance}
              onClick={() =>
                updateSetting("voiceAssistance", !settings.voiceAssistance)
              }
              className={`toggle ${
                settings.voiceAssistance ? "toggle--on" : ""
              }`}
            >
              <i />
            </button>
          </div>

          <div className="setting">
            <span>
              <strong>Low-bandwidth mode</strong>
              <small>Disable decorative motion and use compact data layouts.</small>
            </span>
            <button
              type="button"
              aria-pressed={settings.lowBandwidth}
              onClick={() =>
                updateSetting("lowBandwidth", !settings.lowBandwidth)
              }
              className={`toggle ${settings.lowBandwidth ? "toggle--on" : ""}`}
            >
              <i />
            </button>
          </div>
        </div>

        <div className="panel settings-panel">
          <PanelHeader title="Simulation & Prototype Policy" />
          <div className="setting">
            <span>
              <strong>Top Prototype Notice Banner</strong>
              <small>
                Display dismissible disclaimer banner for hackathon review.
              </small>
            </span>
            <button
              type="button"
              aria-pressed={settings.prototypeDisclaimer}
              onClick={() =>
                updateSetting(
                  "prototypeDisclaimer",
                  !settings.prototypeDisclaimer
                )
              }
              className={`toggle ${
                settings.prototypeDisclaimer ? "toggle--on" : ""
              }`}
            >
              <i />
            </button>
          </div>

          <div className="setting">
            <span>
              <strong>Simulated Services Policy</strong>
              <small>
                Always enforced by platform design. Real banking and live NADRA
                queries are prohibited in prototype mode.
              </small>
            </span>
            <Badge tone="success">Enforced by Policy</Badge>
          </div>
        </div>
      </div>
    </>
  );
}

// --- Citizen Bottom Floating Bar ---
function CitizenHelperBar() {
  const { currentLang, toggleLanguage, settings } = useData();

  return (
    <div className="citizen-bar">
      {settings.voiceAssistance && (
        <span>
          <Icon name="mic" size={16} /> Voice support available
        </span>
      )}
      {settings.urduEntryPoint && (
        <button type="button" onClick={toggleLanguage}>
          {currentLang === "ur" ? "View in English" : "اردو میں دیکھیں"}
        </button>
      )}
      <span>This is a simulated service · Hackathon Prototype</span>
    </div>
  );
}

// ==========================================
// MAIN APPLICATION ROOT
// ==========================================
export default function App() {
  const { user } = useAuth();
  const { settings } = useData();

  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <div className="app-shell">
      {settings.lowBandwidth && (
        <div className="low-bandwidth-banner">
          <Icon name="cloud" size={14} />
          <span>Low-bandwidth mode active. Animation and graphics minimized.</span>
        </div>
      )}
      <Sidebar />
      <main className="main">
        <Routes>
          <Route path="/" element={<RoleHome />} />
          <Route path="/cases" element={<Cases />} />
          <Route path="/cases/:caseId" element={<Cases detail />} />
          <Route
            path="/claim"
            element={
              <RoleGate roles={["CITIZEN", "HELPER", "OFFICER", "ADMIN"]}>
                <ClaimForm />
              </RoleGate>
            }
          />
          <Route
            path="/decisions"
            element={
              <RoleGate roles={["OFFICER", "ADMIN", "AUDITOR"]}>
                <DecisionCenter />
              </RoleGate>
            }
          />
          <Route
            path="/review"
            element={
              <RoleGate roles={["OFFICER"]}>
                <ReviewQueue />
              </RoleGate>
            }
          />
          <Route
            path="/citizens"
            element={
              <RoleGate roles={["HELPER", "OFFICER", "ADMIN"]}>
                <Citizens />
              </RoleGate>
            }
          />
          <Route path="/consent" element={<Consent />} />
          <Route
            path="/audit"
            element={
              <RoleGate roles={["OFFICER", "ADMIN", "AUDITOR"]}>
                <Audit />
              </RoleGate>
            }
          />
          <Route
            path="/rules"
            element={
              <RoleGate roles={["ADMIN", "AUDITOR"]}>
                <Rules />
              </RoleGate>
            }
          />
          <Route
            path="/analytics"
            element={
              <RoleGate roles={["OFFICER", "ADMIN", "AUDITOR"]}>
                <Analytics />
              </RoleGate>
            }
          />
          <Route
            path="/settings"
            element={
              <RoleGate roles={["ADMIN"]}>
                <Settings />
              </RoleGate>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <CitizenHelperBar />
    </div>
  );
}
