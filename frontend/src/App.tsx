import { useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import "./styles.css";

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
  | "cloud";
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
      count: "8",
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
const cases = [
  {
    id: "REL-20481",
    person: "Ayesha Bibi",
    type: "Relief assistance",
    status: "Needs review",
    score: "62%",
    tone: "warning",
    date: "18 min ago",
  },
  {
    id: "REL-20480",
    person: "Muhammad Afzal",
    type: "Relief assistance",
    status: "Verified",
    score: "94%",
    tone: "success",
    date: "42 min ago",
  },
  {
    id: "REL-20479",
    person: "Zainab Kausar",
    type: "Document update",
    status: "More information",
    score: "—",
    tone: "muted",
    date: "1 hr ago",
  },
  {
    id: "REL-20478",
    person: "Naseem Akhtar",
    type: "Relief assistance",
    status: "Submitted",
    score: "88%",
    tone: "neutral",
    date: "2 hrs ago",
  },
];
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
function Sidebar() {
  const { pathname } = useLocation();
  return (
    <aside className="sidebar">
      <Link to="/" className="brand" aria-label="RASTA home">
        <RastaMark />
        <span>RASTA</span>
        <small>PUBLIC RAILS</small>
      </Link>
      <div className="workspace">
        <span className="workspace__seal">SD</span>
        <span>
          <small>WORKSPACE</small>
          <strong>Sindh Social Relief</strong>
        </span>
        <Icon name="chevron" size={14} />
      </div>
      <nav className="side-nav" aria-label="RASTA workspace navigation">
        {navGroups.map((g, i) => (
          <div className="nav-group" key={i}>
            {g.map((n) => (
              <Link
                key={n.to}
                to={n.to}
                className={
                  pathname === n.to ? "nav-item nav-item--active" : "nav-item"
                }
              >
                <Icon name={n.icon} />
                <span>{n.label}</span>
                {n.count && <em>{n.count}</em>}
              </Link>
            ))}
          </div>
        ))}
      </nav>
      <div className="sidebar-foot">
        <div className="offline">
          <Icon name="cloud" size={15} />
          <span>All changes saved</span>
        </div>
        <button className="profile">
          <span className="avatar">FK</span>
          <span>
            <strong>Fatima Khan</strong>
            <small>Department officer</small>
          </span>
          <Icon name="dots" size={18} />
        </button>
      </div>
    </aside>
  );
}
function Header({ title, eyebrow }: { title: string; eyebrow?: string }) {
  return (
    <header className="topbar">
      <div className="page-heading">
        {eyebrow && <p>{eyebrow}</p>}
        <h1>{title}</h1>
      </div>
      <div className="topbar__tools">
        <label className="search">
          <Icon name="search" size={17} />
          <input
            aria-label="Search RASTA"
            placeholder="Search cases, citizens..."
          />
          <kbd>⌘ K</kbd>
        </label>
        <button className="icon-button notification" aria-label="Notifications">
          <Icon name="bell" />
          <span />
        </button>
        <button className="mobile-avatar" aria-label="Profile">
          FK
        </button>
      </div>
    </header>
  );
}
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
}: {
  title: string;
  action?: string;
  to?: string;
}) {
  return (
    <div className="panel-heading">
      <h3>{title}</h3>
      {action && to && (
        <Link to={to}>
          {action} <Icon name="arrow" size={15} />
        </Link>
      )}
    </div>
  );
}
function Overview() {
  const [live, setLive] = useState(true);
  return (
    <>
      <Header
        title="Good morning, Fatima."
        eyebrow="Friday, 21 November 2026"
      />
      <section className="notice">
        <div className="notice__icon">
          <Icon name="alert" size={18} />
        </div>
        <div>
          <strong>
            Prototype environment - no real public services or personal data.
          </strong>
          <p>
            All identities, payments, and case records are simulated for the
            Coder's Cup 2026 demonstration.
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
          <h2>Every route deserves<br /><em>a safe arrival.</em></h2>
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
          <div className="priority-card__number">08</div>
          <p>Cases require a human decision</p>
          <Link to="/review">
            Open review queue <Icon name="arrow" size={16} />
          </Link>
        </div>
      </section>
      <section className="metrics">
        <Metric
          label="New cases today"
          value="24"
          comparison="12% from yesterday"
          direction="up"
        />
        <Metric
          label="Clear to proceed"
          value="16"
          comparison="67% of today's cases"
          direction="flat"
        />
        <Metric
          label="Awaiting citizens"
          value="05"
          comparison="Documents or consent needed"
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
            {cases.map((x) => (
              <Link to={`/cases/${x.id}`} className="case-row" key={x.id}>
                <div className="case-person">
                  <span className="initials">
                    {x.person
                      .split(" ")
                      .map((y) => y[0])
                      .join("")}
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
          <p>of decisions were high confidence this week</p>
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
      <section className="dashboard-grid dashboard-grid--bottom">
        <div className="panel action-panel">
          <PanelHeader title="Continue working" />
          <div className="continue-item">
            <div className="continue-icon">
              <Icon name="folder" />
            </div>
            <div>
              <strong>REL-20481 needs your decision</strong>
              <p>Duplicate record risk detected · 18 min ago</p>
            </div>
            <Link to="/cases/REL-20481">
              <Icon name="arrow" />
            </Link>
          </div>
          <div className="continue-item">
            <div className="continue-icon continue-icon--gold">
              <Icon name="file" />
            </div>
            <div>
              <strong>Policy version 3.2 is ready to publish</strong>
              <p>Eligibility rule update · Drafted by administrator</p>
            </div>
            <Link to="/rules">
              <Icon name="arrow" />
            </Link>
          </div>
        </div>
        <div className="panel integrity-panel">
          <PanelHeader title="System integrity" />
          <div className="integrity-item">
            <span className="integrity-glyph">✓</span>
            <span>
              <strong>Audit trail protected</strong>
              <small>Every action is recorded</small>
            </span>
            <Badge tone="success">Healthy</Badge>
          </div>
          <div className="integrity-item">
            <span className="integrity-glyph integrity-glyph--gold">↗</span>
            <span>
              <strong>Mock services connected</strong>
              <small>Identity · Payments · Notifications</small>
            </span>
            <Badge tone="success">3 / 3</Badge>
          </div>
        </div>
      </section>
    </>
  );
}
function Cases({ detail = false }: { detail?: boolean }) {
  const [filter, setFilter] = useState("All cases");
  if (detail) return <CaseDetail />;
  return (
    <>
      <Header title="Case management" eyebrow="WORKSPACE / OPERATIONS" />
      <section className="page-intro">
        <p>
          Track assistance requests from submission to resolution. Every
          automated finding remains reviewable.
        </p>
        <button className="primary-button">
          <Icon name="plus" /> Create case
        </button>
      </section>
      <div className="panel table-panel">
        <div className="table-toolbar">
          <div className="tabs">
            {["All cases", "Needs review", "Awaiting citizen", "Resolved"].map(
              (t) => (
                <button
                  className={filter === t ? "tab tab--active" : "tab"}
                  onClick={() => setFilter(t)}
                  key={t}
                >
                  {t}
                  {t === "Needs review" && <span>8</span>}
                </button>
              ),
            )}
          </div>
          <button className="filter-button">
            <Icon name="sliders" size={16} /> Filter
          </button>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Case</th>
                <th>Citizen</th>
                <th>Automated assessment</th>
                <th>Current status</th>
                <th>Last updated</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {cases
                .concat([
                  {
                    id: "REL-20477",
                    person: "Irfan Ali",
                    type: "Relief assistance",
                    status: "Verified",
                    score: "97%",
                    tone: "success",
                    date: "3 hrs ago",
                  },
                ])
                .map((c) => (
                  <tr key={c.id}>
                    <td>
                      <Link to={`/cases/${c.id}`} className="case-id">
                        {c.id}
                      </Link>
                      <small>{c.type}</small>
                    </td>
                    <td>
                      <strong>{c.person}</strong>
                      <small>Citizen record</small>
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
                        {c.score} confidence
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
        </div>
      </div>
    </>
  );
}
function CaseDetail() {
  const [approved, setApproved] = useState(false);
  return (
    <>
      <Header
        title="Case REL-20481"
        eyebrow="CASE MANAGEMENT / RELIEF ASSISTANCE"
      />
      <div className="detail-back">
        <Link to="/cases">← Back to cases</Link>
        <Badge tone={approved ? "success" : "warning"}>
          {approved ? "Approved by officer" : "Human decision needed"}
        </Badge>
      </div>
      <section className="case-detail-grid">
        <div>
          <div className="person-hero">
            <span className="person-portrait">AB</span>
            <div>
              <h2>Ayesha Bibi</h2>
              <p>Relief assistance request · Submitted today at 09:42</p>
              <div className="person-tags">
                <span>
                  Citizen ID: <strong>•••• 4382</strong>
                </span>
                <span>Karachi East</span>
                <span>Urdu preferred</span>
              </div>
            </div>
          </div>
          <div className="panel timeline">
            <PanelHeader title="Case timeline" />
            <Timeline />
          </div>
          <div className="panel evidence">
            <PanelHeader title="Information & documents" />
            <div className="document">
              <span className="document__icon">
                <Icon name="file" />
              </span>
              <span>
                <strong>Household declaration</strong>
                <small>Extracted with document reading · 2 min ago</small>
              </span>
              <Badge tone="success">Read</Badge>
            </div>
            <div className="data-warning">
              <Icon name="alert" />
              <span>
                <strong>Potential duplicate information</strong>
                <small>
                  A similar household record was found. This is why the case is
                  routed to you.
                </small>
              </span>
            </div>
          </div>
        </div>
        <aside className="decision-rail">
          <div className="decision-summary">
            <p>DECISION ASSISTANCE</p>
            <div className="decision-score">
              <strong>62</strong>
              <span>
                %<small>confidence</small>
              </span>
            </div>
            <Badge tone="warning">Uncertain</Badge>
            <h3>Ask a human to decide</h3>
            <p>
              One or more signals conflict. No payment can proceed without
              officer review.
            </p>
          </div>
          <div className="reason-list">
            <h4>Why this was escalated</h4>
            <Reason good="Identity details match verified record" />
            <Reason warn="Household address may match REL-18214" />
            <Reason good="Eligibility rule v3.1 is satisfied" />
            <Link to="/decisions" className="explain-link">
              View full explanation <Icon name="arrow" size={15} />
            </Link>
          </div>
          <div className="decision-actions">
            <button
              className="secondary-button"
              onClick={() =>
                alert("Evidence request added to this simulated case.")
              }
            >
              Request evidence
            </button>
            <button
              className="primary-button"
              onClick={() => setApproved(true)}
            >
              <Icon name="check" /> Approve simulated case
            </button>
            <button
              className="text-button"
              onClick={() => alert("The simulated case has been rejected.")}
            >
              Reject case
            </button>
          </div>
        </aside>
      </section>
    </>
  );
}
function Timeline() {
  return (
    <ol className="timeline-list">
      <li>
        <i className="timeline-dot timeline-dot--current" />
        <div>
          <small>TODAY · 10:13</small>
          <strong>Automated assessment completed</strong>
          <p>Routed to human review due to duplicate risk.</p>
        </div>
      </li>
      <li>
        <i className="timeline-dot" />
        <div>
          <small>TODAY · 10:11</small>
          <strong>Identity record verified</strong>
          <p>Mock identity service returned a matching record.</p>
        </div>
      </li>
      <li>
        <i className="timeline-dot" />
        <div>
          <small>TODAY · 09:42</small>
          <strong>Case submitted by community helper</strong>
          <p>Consent to share records is active.</p>
        </div>
      </li>
    </ol>
  );
}
function Reason({ good, warn }: { good?: string; warn?: string }) {
  return (
    <div className="reason">
      <span
        className={
          good
            ? "reason-icon reason-icon--good"
            : "reason-icon reason-icon--warn"
        }
      >
        <Icon name={good ? "check" : "alert"} size={14} />
      </span>
      <span>{good || warn}</span>
    </div>
  );
}
function DecisionCenter() {
  return (
    <>
      <Header title="AI decision center" eyebrow="TRANSPARENCY & SAFETY" />
      <section className="page-intro">
        <p>
          Every automated signal is explained, versioned, and ready for human
          review. These suggestions do not make final public-service decisions.
        </p>
        <button className="secondary-button">
          <Icon name="file" /> Export review brief
        </button>
      </section>
      <section className="decision-kpis">
        <Metric
          label="Decisions this week"
          value="128"
          comparison="Across 4 assessment types"
          direction="up"
        />
        <Metric
          label="Human escalation"
          value="18%"
          comparison="When signals are uncertain"
          direction="flat"
        />
        <Metric
          label="Rule version"
          value="v3.1"
          comparison="Active since 18 Nov"
          direction="flat"
        />
      </section>
      <section className="decision-grid">
        <div className="panel model-panel">
          <PanelHeader title="Assessment quality" />
          <div className="donut-wrap">
            <div className="donut">
              <span>
                82<small>%</small>
              </span>
            </div>
            <div>
              <strong>High confidence</strong>
              <p>Clear evidence supports the recommended route.</p>
              <span className="model-key">
                <i /> 105 decisions
              </span>
              <span className="model-key model-key--review">
                <i /> 23 sent to review
              </span>
            </div>
          </div>
        </div>
        <div className="panel explain-panel">
          <PanelHeader title="Latest explainable decision" />
          <div className="explain-case">
            <span className="initials initials--large">MA</span>
            <span>
              <strong>REL-20480 · Muhammad Afzal</strong>
              <small>Relief assistance · 94% confidence</small>
            </span>
            <Badge tone="success">Clear to proceed</Badge>
          </div>
          <div className="reason-list reason-list--compact">
            <Reason good="Verified identity matched source record" />
            <Reason good="Policy eligibility: household income below threshold" />
            <Reason good="No duplicate or scam indicators detected" />
          </div>
          <Link to="/cases/REL-20480" className="explain-link">
            Inspect decision trace <Icon name="arrow" size={15} />
          </Link>
        </div>
      </section>
    </>
  );
}
function ReviewQueue() {
  const [sort, setSort] = useState("Priority");
  return (
    <>
      <Header title="Human review queue" eyebrow="OFFICER WORKSPACE" />
      <section className="page-intro">
        <p>
          Cases here need a person’s judgment. Automated decisions are paused
          until you take action.
        </p>
        <div className="sort">
          <span>Sort:</span>
          <button
            onClick={() => setSort(sort === "Priority" ? "Oldest" : "Priority")}
          >
            {sort} <Icon name="chevron" size={14} />
          </button>
        </div>
      </section>
      <section className="review-layout">
        <div className="queue-list">
          {cases.slice(0, 3).map((c, i) => (
            <Link
              key={c.id}
              className={
                i === 0 ? "review-card review-card--active" : "review-card"
              }
              to={`/cases/${c.id}`}
            >
              <span
                className={`priority priority--${i === 0 ? "high" : "normal"}`}
              >
                {i === 0 ? "P1" : "P2"}
              </span>
              <span className="initials">
                {c.person
                  .split(" ")
                  .map((x) => x[0])
                  .join("")}
              </span>
              <span>
                <strong>{c.person}</strong>
                <small>
                  {c.id} · {c.type}
                </small>
                <p>
                  {i === 0
                    ? "Possible household duplicate needs verification"
                    : "Evidence does not fully agree with eligibility rule"}
                </p>
              </span>
              <span className="review-confidence">
                {c.score}
                <small>confidence</small>
              </span>
            </Link>
          ))}
        </div>
        <div className="panel review-preview">
          <div className="preview-head">
            <div>
              <span className="label">SELECTED CASE</span>
              <h2>Ayesha Bibi</h2>
              <p>REL-20481 · Relief assistance</p>
            </div>
            <Badge tone="warning">P1 priority</Badge>
          </div>
          <div className="review-signals">
            <div>
              <span className="signal-mark signal-mark--match">✓</span>
              <span>
                Identity match<small>Mock verification passed</small>
              </span>
            </div>
            <div>
              <span className="signal-mark signal-mark--issue">!</span>
              <span>
                Duplicate risk<small>Similar household record</small>
              </span>
            </div>
            <div>
              <span className="signal-mark signal-mark--match">✓</span>
              <span>
                Policy eligible<small>Rule version 3.1</small>
              </span>
            </div>
          </div>
          <div className="review-footer">
            <p>
              <Icon name="shield" size={16} /> A final officer action is
              required.
            </p>
            <Link to="/cases/REL-20481" className="primary-button">
              Review case <Icon name="arrow" />
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
function PlaceholderPage({
  title,
  copy,
  children,
}: {
  title: string;
  copy: string;
  children?: React.ReactNode;
}) {
  return (
    <>
      <Header title={title} eyebrow="WORKSPACE / GOVERNANCE" />
      <section className="page-intro">
        <p>{copy}</p>
        <button className="primary-button">
          <Icon name="plus" /> Add record
        </button>
      </section>
      {children || (
        <div className="empty-state panel">
          <span className="empty-illustration">
            <Icon name="folder" size={28} />
          </span>
          <h2>Everything is in order</h2>
          <p>
            This prototype workspace has no additional records to display right
            now.
          </p>
        </div>
      )}
    </>
  );
}
function Citizens() {
  return (
    <PlaceholderPage
      title="Citizen management"
      copy="Manage citizen records, preferred access methods, and helper relationships with clear consent boundaries."
    >
      <div className="citizen-cards">
        {["Ayesha Bibi", "Muhammad Afzal", "Zainab Kausar"].map((name, i) => (
          <article className="citizen-card" key={name}>
            <span className="initials initials--large">
              {name
                .split(" ")
                .map((x) => x[0])
                .join("")}
            </span>
            <h3>{name}</h3>
            <p>
              {i === 0
                ? "Urdu · Voice assistance enabled"
                : "Urdu · Text and helper access"}
            </p>
            <Badge tone="success">Consent active</Badge>
            <Link to="/consent">
              Manage access <Icon name="arrow" size={14} />
            </Link>
          </article>
        ))}
      </div>
    </PlaceholderPage>
  );
}
function Consent() {
  return (
    <PlaceholderPage
      title="Consent management"
      copy="Citizens decide what data may be shared, with whom, and for how long. Withdrawal takes effect immediately."
    >
      <div className="panel consent-panel">
        <PanelHeader title="Active sharing permissions" />
        <div className="consent-row">
          <span className="initials">AB</span>
          <span>
            <strong>Ayesha Bibi</strong>
            <small>Shared with community helper · Assistance claim scope</small>
          </span>
          <Badge tone="success">Active</Badge>
          <button className="outline-button">Withdraw</button>
        </div>
        <div className="consent-row">
          <span className="initials">MA</span>
          <span>
            <strong>Muhammad Afzal</strong>
            <small>
              Shared with department officer · Identity verification scope
            </small>
          </span>
          <Badge tone="success">Active</Badge>
          <button className="outline-button">Withdraw</button>
        </div>
      </div>
    </PlaceholderPage>
  );
}
function Audit() {
  return (
    <PlaceholderPage
      title="Audit trail"
      copy="A tamper-evident, chronological record of user actions, automated findings, policy versions, and consent changes."
    >
      <div className="panel audit-panel">
        <PanelHeader title="Latest recorded events" />
        {[
          "Officer opened REL-20481 for review",
          "Decision engine escalated REL-20481",
          "Community helper submitted a case for Ayesha Bibi",
          "Consent recorded for assistance-claim sharing",
        ].map((item, i) => (
          <div className="audit-row" key={item}>
            <span className="audit-mark">
              <Icon name={i === 1 ? "spark" : "scroll"} size={15} />
            </span>
            <span>
              <strong>{item}</strong>
              <small>{18 + i * 9} minutes ago · Demo workspace</small>
            </span>
            <button>
              <Icon name="eye" size={16} />
            </button>
          </div>
        ))}
      </div>
    </PlaceholderPage>
  );
}
function Rules() {
  const [published, setPublished] = useState(false);
  return (
    <>
      <Header
        title="Rules & eligibility"
        eyebrow="WORKSPACE / POLICY CONTROL"
      />
      <section className="page-intro">
        <p>
          Change eligibility rules without changing code. Every version is
          reviewed, dated, and preserved for audit.
        </p>
        <button onClick={() => setPublished(true)} className="primary-button">
          <Icon name="check" />{" "}
          {published ? "Version published" : "Publish draft v3.2"}
        </button>
      </section>
      <div className="rules-grid">
        <div className="panel rule-editor">
          <PanelHeader title="Relief assistance eligibility" />
          <div className="rule-version">
            <span>
              <strong>Version 3.2</strong>
              <small>Draft · Edited 12 min ago</small>
            </span>
            <Badge tone="warning">Awaiting publish</Badge>
          </div>
          <div className="rule-block">
            <span>IF</span>
            <strong>Household income</strong>
            <select defaultValue="less">
              <option value="less">is less than</option>
            </select>
            <input defaultValue="Rs 45,000" />
          </div>
          <div className="rule-block">
            <span>AND</span>
            <strong>Identity verification</strong>
            <select defaultValue="pass">
              <option value="pass">is verified</option>
            </select>
          </div>
          <div className="rule-block">
            <span>THEN</span>
            <strong>Route case</strong>
            <select defaultValue="review">
              <option value="review">to human review</option>
            </select>
          </div>
        </div>
        <div className="panel rule-history">
          <PanelHeader title="Version history" />
          <div className="version">
            <span>
              <i className="version__dot version__dot--active" />
              <strong>v3.1</strong>
              <small>Active · 18 Nov 2026</small>
            </span>
            <Badge tone="success">Active</Badge>
          </div>
          <div className="version">
            <span>
              <i className="version__dot" />
              <strong>v3.0</strong>
              <small>Archived · 07 Nov 2026</small>
            </span>
            <button className="text-button">Compare</button>
          </div>
        </div>
      </div>
    </>
  );
}
function Analytics() {
  return (
    <>
      <Header title="Analytics" eyebrow="WORKSPACE / OPERATIONS INSIGHTS" />
      <section className="analytics-lead">
        <div>
          <p>Relief assistance workflow</p>
          <h2>Clearer service, safer decisions.</h2>
        </div>
        <div className="date-select">
          Last 7 days <Icon name="chevron" size={15} />
        </div>
      </section>
      <div className="analytics-grid">
        <div className="panel volume-chart">
          <PanelHeader title="Case volume" />
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
          <PanelHeader title="Case outcomes" />
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
                <small>Human review</small>
              </span>
            </div>
            <div>
              <span className="outcomes__circle outcomes__circle--neutral" />
              <span>
                <strong>15%</strong>
                <small>Awaiting citizen</small>
              </span>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
function Setting({
  label,
  detail,
  on = false,
}: {
  label: string;
  detail: string;
  on?: boolean;
}) {
  const [enabled, setEnabled] = useState(on);
  return (
    <div className="setting">
      <span>
        <strong>{label}</strong>
        <small>{detail}</small>
      </span>
      <button
        aria-pressed={enabled}
        onClick={() => setEnabled(!enabled)}
        className={enabled ? "toggle toggle--on" : "toggle"}
      >
        <i />
      </button>
    </div>
  );
}
function Settings() {
  return (
    <PlaceholderPage
      title="Workspace settings"
      copy="Configure your demonstration workspace, notification preferences, and accessibility defaults."
    >
      <div className="settings-grid">
        <div className="panel settings-panel">
          <PanelHeader title="Accessibility by default" />
          <Setting
            label="Show Urdu entry point"
            detail="Offer Urdu as a starting language"
            on
          />
          <Setting
            label="Voice assistance"
            detail="Enable spoken input and read-aloud controls"
            on
          />
          <Setting
            label="Low-bandwidth mode"
            detail="Use lighter uploads and save local drafts"
          />
        </div>
        <div className="panel settings-panel">
          <PanelHeader title="Simulation controls" />
          <Setting
            label="Prototype disclaimer"
            detail="Display on all service screens"
            on
          />
          <Setting
            label="Mock services"
            detail="Use simulated identity and payment responses"
            on
          />
        </div>
      </div>
    </PlaceholderPage>
  );
}
function CitizenHelperBar() {
  return (
    <div className="citizen-bar">
      <span>
        <Icon name="mic" size={16} /> Voice support available
      </span>
      <button>اردو میں دیکھیں</button>
      <span>This is a simulated service</span>
    </div>
  );
}
export default function App() {
  return (
    <div className="app-shell">
      <Sidebar />
      <main className="main">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/cases" element={<Cases />} />
          <Route path="/cases/:caseId" element={<Cases detail />} />
          <Route path="/decisions" element={<DecisionCenter />} />
          <Route path="/review" element={<ReviewQueue />} />
          <Route path="/citizens" element={<Citizens />} />
          <Route path="/consent" element={<Consent />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="/rules" element={<Rules />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Overview />} />
        </Routes>
      </main>
      <CitizenHelperBar />
    </div>
  );
}
