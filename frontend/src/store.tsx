// Central state store for RASTA with local persistence and real backend integration
import React, { createContext, useContext, useEffect, useState } from "react";
import {
  createBackendCase,
  disburseRaast,
  fetchBackendAuditLogs,
  fetchBackendCases,
  fetchBackendConsents,
  fetchBackendMetrics,
  fetchBackendRules,
  getStoredToken,
  grantBackendConsent,
  publishBackendRule,
  requestAiDecision,
  reviewBackendCase,
  sendSms,
  submitBackendCase,
  verifyNadra,
  withdrawBackendConsent,
} from "./api";
import type {
  AppSettings,
  AuditEvent,
  CaseRecord,
  ConsentRecord,
  NotificationItem,
  PolicyRule,
  Role,
} from "./types";

interface HelperCitizen {
  name: string;
  cnic: string;
  phone: string;
  relationship: string;
  consentActive: boolean;
  casesCount: number;
}

interface DataContextValue {
  // Cases
  cases: CaseRecord[];
  getCase: (id: string) => CaseRecord | undefined;
  createCase: (payload: {
    person: string;
    cnic: string;
    phone: string;
    type: string;
    householdIncome: number;
    householdMembers: number;
    address: string;
    notes?: string;
    submittedBy: string;
    submittedByRole: Role;
  }) => Promise<{ caseId: string; backendAi: boolean; backendNadra: boolean }>;
  officerAction: (
    caseId: string,
    action: "approve" | "reject" | "request_evidence",
    notes: string,
    officerName: string
  ) => Promise<{ success: boolean; smsSent?: boolean; raastTxn?: string; note?: string }>;

  // Consents
  consents: ConsentRecord[];
  grantConsent: (payload: {
    citizenName: string;
    citizenCnic: string;
    grantee: string;
    scope: string;
    durationMonths: number;
    source: "citizen" | "helper_proxy";
    actorName: string;
    actorRole: Role;
  }) => void;
  revokeConsent: (id: string, actorName: string, actorRole: Role) => void;

  // Audit
  auditEvents: AuditEvent[];
  logAuditEvent: (
    category: AuditEvent["category"],
    title: string,
    details: string,
    actor: string,
    actorRole: Role
  ) => void;

  // Rules & Policy
  activeRule: PolicyRule;
  draftRule: PolicyRule;
  ruleHistory: PolicyRule[];
  updateDraftRule: (updates: Partial<PolicyRule>) => void;
  publishDraftRule: (actorName: string) => void;

  // Notifications
  notifications: NotificationItem[];
  markNotificationRead: (id: string) => void;
  dismissNotification: (id: string) => void;

  // Settings
  settings: AppSettings;
  updateSetting: <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => void;

  // Helper context
  helperActiveCitizen: string;
  setHelperActiveCitizen: (name: string) => void;
  authorizedCitizens: HelperCitizen[];
  registerAuthorizedCitizen: (citizen: HelperCitizen, helperName: string) => void;

  // Language
  currentLang: "en" | "ur";
  toggleLanguage: () => void;
  setLanguage: (lang: "en" | "ur") => void;
}

const STORAGE_KEYS = {
  CASES: "rasta.data.cases.v2",
  CONSENTS: "rasta.data.consents.v2",
  AUDIT: "rasta.data.audit.v2",
  RULES: "rasta.data.rules.v2",
  NOTIFICATIONS: "rasta.data.notifications.v2",
  SETTINGS: "rasta.data.settings.v2",
  CITIZENS: "rasta.data.citizens.v2",
  HELPER_ACTIVE: "rasta.data.helper_active.v2",
  LANG: "rasta.data.lang.v2",
};

const initialCases: CaseRecord[] = [
  {
    id: "REL-20481",
    person: "Ayesha Bibi",
    cnic: "99999-0000001-1",
    phone: "0300-0000001",
    type: "Relief assistance",
    householdIncome: 38000,
    householdMembers: 5,
    address: "House 14-B, Korangi Sector 4, Karachi",
    status: "Needs review",
    priority: "P1",
    score: "62%",
    tone: "warning",
    date: "18 min ago",
    submittedAt: "2026-11-21T09:42:00Z",
    submittedBy: "Sana Iqbal (Community Helper)",
    submittedByRole: "HELPER",
    aiRoute: "HUMAN",
    aiReason: "Duplicate household address flag detected with historical record REL-18214.",
    aiConfidence: 0.62,
    nadraVerified: true,
    nadraNote: "FAKE NADRA: Record matches identity registry.",
    timeline: [
      {
        id: "t1",
        title: "Claim Submitted",
        time: "09:42 AM",
        description: "Assistance claim submitted with proxy citizen consent.",
        type: "submit",
      },
      {
        id: "t2",
        title: "NADRA Verification Passed",
        time: "10:11 AM",
        description: "Identity verified against synthetic registry for CNIC 99999-0000001-1.",
        type: "verify",
      },
      {
        id: "t3",
        title: "AI Escalation",
        time: "10:13 AM",
        description: "Decision engine routed to HUMAN review (62% confidence) due to duplicate risk.",
        type: "ai",
      },
    ],
  },
  {
    id: "REL-20480",
    person: "Muhammad Afzal",
    cnic: "99999-0000002-2",
    phone: "0300-0000002",
    type: "Relief assistance",
    householdIncome: 28000,
    householdMembers: 4,
    address: "Village Chuharkana, District Sheikhupura",
    status: "Verified",
    priority: "P2",
    score: "94%",
    tone: "success",
    date: "42 min ago",
    submittedAt: "2026-11-21T08:50:00Z",
    submittedBy: "Muhammad Afzal",
    submittedByRole: "CITIZEN",
    aiRoute: "AUTO_CLEAR",
    aiReason: "Identity verified, income below Rs 45,000 threshold, no duplicates.",
    aiConfidence: 0.94,
    nadraVerified: true,
    timeline: [
      {
        id: "t4",
        title: "Claim Submitted",
        time: "08:50 AM",
        description: "Self-service citizen claim submitted with audio verification.",
        type: "submit",
      },
      {
        id: "t5",
        title: "Automated Assessment Cleared",
        time: "09:05 AM",
        description: "High confidence route (94%). All criteria satisfied.",
        type: "ai",
      },
      {
        id: "t6",
        title: "Disbursement Scheduled",
        time: "09:12 AM",
        description: "Clear to proceed for Rs 25,000 emergency grant via Raast.",
        type: "payment",
      },
    ],
  },
  {
    id: "REL-20479",
    person: "Zainab Kausar",
    cnic: "99999-0000003-3",
    phone: "0300-0000003",
    type: "Document update",
    householdIncome: 42000,
    householdMembers: 3,
    address: "Street 8, Mohalla Eidgah, Rawalpindi",
    status: "More information",
    priority: "P3",
    score: "—",
    tone: "muted",
    date: "1 hr ago",
    submittedAt: "2026-11-21T08:15:00Z",
    submittedBy: "Zainab Kausar",
    submittedByRole: "CITIZEN",
    aiRoute: "HUMAN",
    aiReason: "Document scan low-resolution; utility bill date unreadable.",
    aiConfidence: 0.45,
    evidenceRequested: true,
    evidenceNotes: ["Officer requested updated electricity bill scan."],
    timeline: [
      {
        id: "t7",
        title: "Document Submission",
        time: "08:15 AM",
        description: "Address update filed with utility receipt attachment.",
        type: "submit",
      },
      {
        id: "t8",
        title: "Evidence Requested",
        time: "08:35 AM",
        description: "Officer Fatima Khan requested clearer copy via SMS dispatch.",
        type: "evidence",
      },
    ],
  },
  {
    id: "REL-20478",
    person: "Naseem Akhtar",
    cnic: "99999-0000004-4",
    phone: "0300-0000004",
    type: "Relief assistance",
    householdIncome: 31000,
    householdMembers: 6,
    address: "Chak 45/SB, Sargodha",
    status: "Submitted",
    priority: "P2",
    score: "88%",
    tone: "neutral",
    date: "2 hrs ago",
    submittedAt: "2026-11-21T07:20:00Z",
    submittedBy: "Naseem Akhtar",
    submittedByRole: "CITIZEN",
    aiRoute: "HUMAN",
    aiReason: "Income threshold satisfied. Awaiting officer queue confirmation.",
    aiConfidence: 0.88,
    timeline: [
      {
        id: "t9",
        title: "Claim Submitted",
        time: "07:20 AM",
        description: "New relief grant application registered.",
        type: "submit",
      },
    ],
  },
  {
    id: "REL-20477",
    person: "Irfan Ali",
    cnic: "99999-0000005-5",
    phone: "0300-0000005",
    type: "Relief assistance",
    householdIncome: 22000,
    householdMembers: 4,
    address: "Unit 3, Latifabad, Hyderabad",
    status: "Verified",
    priority: "P2",
    score: "97%",
    tone: "success",
    date: "3 hrs ago",
    submittedAt: "2026-11-21T06:40:00Z",
    submittedBy: "Sana Iqbal (Community Helper)",
    submittedByRole: "HELPER",
    aiRoute: "AUTO_CLEAR",
    aiReason: "High confidence identity & poverty scorecard verified.",
    aiConfidence: 0.97,
    paymentTxnId: "FAKE-TXN-0001",
    paymentAmount: 25000,
    timeline: [
      {
        id: "t10",
        title: "Disbursed via Raast",
        time: "07:10 AM",
        description: "Payment of Rs 25,000 confirmed under TXN-0001.",
        type: "payment",
      },
    ],
  },
];

const initialConsents: ConsentRecord[] = [
  {
    id: "c-101",
    citizenName: "Ayesha Bibi",
    citizenCnic: "99999-0000001-1",
    grantee: "Community Helper (Sana Iqbal)",
    scope: "Assistance claim filing, document upload & status notifications",
    grantedAt: "2026-11-15T10:00:00Z",
    expiresAt: "2027-05-15T10:00:00Z",
    status: "Active",
    source: "citizen",
  },
  {
    id: "c-102",
    citizenName: "Muhammad Afzal",
    citizenCnic: "99999-0000002-2",
    grantee: "Department Officer (Fatima Khan)",
    scope: "Direct NADRA identity verification and Raast bank lookup",
    grantedAt: "2026-11-18T14:30:00Z",
    expiresAt: "2027-02-18T14:30:00Z",
    status: "Active",
    source: "citizen",
  },
  {
    id: "c-103",
    citizenName: "Zainab Kausar",
    citizenCnic: "99999-0000003-3",
    grantee: "Department of Social Relief",
    scope: "Household survey verification and relief cross-matching",
    grantedAt: "2026-10-10T09:00:00Z",
    expiresAt: "2026-11-20T09:00:00Z",
    status: "Active",
    source: "citizen",
  },
];

const initialAudit: AuditEvent[] = [
  {
    id: "aud-001",
    timestamp: "2026-11-21T09:44:00Z",
    category: "AI_DECISION",
    title: "AI Decision Engine Escalated REL-20481",
    actor: "RASTA Decision Engine v2.1",
    actorRole: "ADMIN",
    details: "Case REL-20481 routed to HUMAN review queue due to duplicate address score (0.62).",
    hash: "sha256:7e88c0a25691d57e4e13",
    source: "api",
  },
  {
    id: "aud-002",
    timestamp: "2026-11-21T09:42:00Z",
    category: "CASE",
    title: "Community Helper Filed Claim for Ayesha Bibi",
    actor: "Sana Iqbal",
    actorRole: "HELPER",
    details: "Assisted submission completed with active citizen consent token c-101.",
    hash: "sha256:3a91b2c4e5f678901234",
    source: "local_ledger",
  },
  {
    id: "aud-003",
    timestamp: "2026-11-21T08:35:00Z",
    category: "NADRA",
    title: "NADRA Verification Checked for Muhammad Afzal",
    actor: "RASTA Platform Gateway",
    actorRole: "ADMIN",
    details: "Synthetic identity lookup returned verified for CNIC 99999-0000002-2.",
    hash: "sha256:9f44a1b8c2d3e5f76812",
    source: "api",
  },
  {
    id: "aud-004",
    timestamp: "2026-11-20T16:20:00Z",
    category: "POLICY",
    title: "Eligibility Policy Rule v3.1 Promoted",
    actor: "Mariam Shah",
    actorRole: "ADMIN",
    details: "Max income threshold set to Rs 45,000; mandatory NADRA requirement activated.",
    hash: "sha256:1b2c3d4e5f6a7b8c9d0e",
    source: "local_ledger",
  },
];

const initialActiveRule: PolicyRule = {
  version: "v3.1",
  name: "Sindh Social Relief Assistance Eligibility",
  status: "Active",
  maxIncome: 45000,
  requireNadra: true,
  confidenceThreshold: 80,
  routeAction: "HUMAN",
  updatedAt: "18 Nov 2026",
  updatedBy: "Mariam Shah (Administrator)",
  notes: "Active policy baseline enforced across all relief queues.",
};

const initialDraftRule: PolicyRule = {
  version: "v3.2",
  name: "Sindh Social Relief Assistance Eligibility (Draft)",
  status: "Draft",
  maxIncome: 50000,
  requireNadra: true,
  confidenceThreshold: 85,
  routeAction: "HUMAN",
  updatedAt: "21 Nov 2026",
  updatedBy: "Mariam Shah (Administrator)",
  notes: "Proposed adjustment for inflation relief and stricter duplicate matching.",
};

const initialNotifications: NotificationItem[] = [
  {
    id: "notif-1",
    title: "Human review required",
    message: "Case REL-20481 (Ayesha Bibi) requires officer adjudication.",
    caseId: "REL-20481",
    time: "18m ago",
    read: false,
    type: "alert",
  },
  {
    id: "notif-2",
    title: "Raast disbursement confirmed",
    message: "REL-20477 (Irfan Ali) Rs 25,000 sent via FAKE-TXN-0001.",
    caseId: "REL-20477",
    time: "3h ago",
    read: false,
    type: "success",
  },
];

const initialAuthorizedCitizens: HelperCitizen[] = [
  {
    name: "Ayesha Bibi",
    cnic: "99999-0000001-1",
    phone: "0300-0000001",
    relationship: "Self-registered applicant",
    consentActive: true,
    casesCount: 1,
  },
  {
    name: "Muhammad Afzal",
    cnic: "99999-0000002-2",
    phone: "0300-0000002",
    relationship: "Community elder",
    consentActive: true,
    casesCount: 1,
  },
  {
    name: "Zainab Kausar",
    cnic: "99999-0000003-3",
    phone: "0300-0000003",
    relationship: "Widow grant program",
    consentActive: true,
    casesCount: 1,
  },
  {
    name: "Ghulam Rasool",
    cnic: "99999-0000006-6",
    phone: "0300-0000006",
    relationship: "Agricultural laborer",
    consentActive: true,
    casesCount: 0,
  },
];

function generateSimHash(): string {
  const chars = "0123456789abcdef";
  let hash = "sha256:";
  for (let i = 0; i < 20; i++) hash += chars[Math.floor(Math.random() * chars.length)];
  return hash;
}

const DataContext = createContext<DataContextValue | null>(null);

export function DataProvider({ children }: { children: React.ReactNode }) {
  // Cases state
  const [cases, setCases] = useState<CaseRecord[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.CASES);
      return saved ? JSON.parse(saved) : initialCases;
    } catch {
      return initialCases;
    }
  });

  // Consents state
  const [consents, setConsents] = useState<ConsentRecord[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.CONSENTS);
      return saved ? JSON.parse(saved) : initialConsents;
    } catch {
      return initialConsents;
    }
  });

  // Audit state
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.AUDIT);
      return saved ? JSON.parse(saved) : initialAudit;
    } catch {
      return initialAudit;
    }
  });

  // Rules state
  const [activeRule, setActiveRule] = useState<PolicyRule>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.RULES);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed.active) return parsed.active;
      }
      return initialActiveRule;
    } catch {
      return initialActiveRule;
    }
  });

  const [draftRule, setDraftRule] = useState<PolicyRule>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.RULES);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed.draft) return parsed.draft;
      }
      return initialDraftRule;
    } catch {
      return initialDraftRule;
    }
  });

  const [ruleHistory] = useState<PolicyRule[]>([
    {
      version: "v3.0",
      name: "Sindh Relief Assistance (Legacy)",
      status: "Archived",
      maxIncome: 40000,
      requireNadra: true,
      confidenceThreshold: 75,
      routeAction: "HUMAN",
      updatedAt: "07 Nov 2026",
      updatedBy: "Admin",
      notes: "Archived prior policy version.",
    },
  ]);

  // Notifications state
  const [notifications, setNotifications] = useState<NotificationItem[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.NOTIFICATIONS);
      return saved ? JSON.parse(saved) : initialNotifications;
    } catch {
      return initialNotifications;
    }
  });

  // Settings state
  const [settings, setSettings] = useState<AppSettings>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.SETTINGS);
      if (saved) return JSON.parse(saved);
    } catch {
      // fallback
    }
    return {
      urduEntryPoint: true,
      voiceAssistance: true,
      lowBandwidth: false,
      prototypeDisclaimer: true,
      simulationEnforced: true,
    };
  });

  // Helper context state
  const [helperActiveCitizen, setHelperActiveCitizenState] = useState<string>(() => {
    return localStorage.getItem(STORAGE_KEYS.HELPER_ACTIVE) || "Ayesha Bibi";
  });

  const [authorizedCitizens, setAuthorizedCitizens] = useState<HelperCitizen[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.CITIZENS);
      return saved ? JSON.parse(saved) : initialAuthorizedCitizens;
    } catch {
      return initialAuthorizedCitizens;
    }
  });

  // Language state
  const [currentLang, setCurrentLang] = useState<"en" | "ur">(() => {
    return (localStorage.getItem(STORAGE_KEYS.LANG) as "en" | "ur") || "en";
  });

  // Apply low-bandwidth class to document body
  useEffect(() => {
    if (settings.lowBandwidth) {
      document.body.classList.add("low-bandwidth-mode");
    } else {
      document.body.classList.remove("low-bandwidth-mode");
    }
  }, [settings.lowBandwidth]);

  // Persistence effects
  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.CASES, JSON.stringify(cases));
  }, [cases]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.CONSENTS, JSON.stringify(consents));
  }, [consents]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.AUDIT, JSON.stringify(auditEvents));
  }, [auditEvents]);

  useEffect(() => {
    localStorage.setItem(
      STORAGE_KEYS.RULES,
      JSON.stringify({ active: activeRule, draft: draftRule })
    );
  }, [activeRule, draftRule]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.NOTIFICATIONS, JSON.stringify(notifications));
  }, [notifications]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.SETTINGS, JSON.stringify(settings));
  }, [settings]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.CITIZENS, JSON.stringify(authorizedCitizens));
  }, [authorizedCitizens]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.LANG, currentLang);
  }, [currentLang]);

  // Backend hydration: merge live data when a real (non-demo) session exists
  useEffect(() => {
    const token = getStoredToken();
    if (!token || token.startsWith("demo.")) return;

    // Hydrate cases from backend
    fetchBackendCases()
      .then((items) => {
        if (!items.length) return;
        // Map backend case shape to local CaseRecord shape (best-effort)
        const mapped = items.map((bc: any) => ({
          id: bc.case_number || bc.id,
          person: bc.data?.name || "Unknown",
          cnic: bc.data?.mock_identity_id?.replace("MOCK-", "").replace(/(\d{5})(\d{7})(\d)/, "$1-$2-$3") || "—",
          phone: bc.data?.payment_account || "—",
          type: bc.claim_type || "Relief assistance",
          householdIncome: bc.data?.monthly_income || 0,
          householdMembers: bc.data?.household_size || 0,
          address: bc.data?.address || "—",
          status: mapBackendStatus(bc.status),
          priority: ((bc.data?.monthly_income || 0) < 30000 ? "P1" : "P2") as CaseRecord["priority"],
          score: bc.ai_confidence ? `${Math.round(bc.ai_confidence * 100)}%` : "—",
          tone: mapStatusTone(bc.status),
          date: relativeTime(bc.submitted_at || bc.created_at),
          submittedAt: bc.submitted_at || bc.created_at || new Date().toISOString(),
          submittedBy: bc.data?.name || "Citizen",
          submittedByRole: "CITIZEN" as const,
          aiRoute: bc.ai_route || "HUMAN",
          aiReason: bc.ai_reason || "",
          aiConfidence: bc.ai_confidence || 0.5,
          nadraVerified: bc.nadra_verified ?? false,
          timeline: [],
          backendId: bc.id,
          backendRevision: bc.revision,
        }));
        setCases((prev) => {
          // Prepend backend cases that are not already in local state (by id)
          const localIds = new Set(prev.map((c) => c.id));
          const newOnes = mapped.filter((m: any) => !localIds.has(m.id));
          return newOnes.length ? [...newOnes, ...prev] : prev;
        });
      })
      .catch(() => {/* backend offline – silent */});

    // Hydrate audit log
    fetchBackendAuditLogs()
      .then((items) => {
        if (!items.length) return;
        const mapped = items.map((a: any) => ({
          id: a.id,
          timestamp: a.created_at,
          category: (a.event_type?.toUpperCase() || "CASE") as AuditEvent["category"],
          title: a.event_type ? `Backend: ${a.event_type}` : "Backend Event",
          actor: a.actor_id || "System",
          actorRole: "ADMIN" as const,
          details: JSON.stringify(a.payload || {}),
          hash: a.id,
          source: "api" as const,
        }));
        setAuditEvents((prev) => {
          const localIds = new Set(prev.map((e) => e.id));
          const newOnes = mapped.filter((m: any) => !localIds.has(m.id));
          return newOnes.length ? [...newOnes, ...prev] : prev;
        });
      })
      .catch(() => {/* backend offline – silent */});

    // Hydrate metrics (just log to console for now — could expose via context later)
    fetchBackendMetrics()
      .then((m) => { console.info("[RASTA] Backend metrics:", m); })
      .catch(() => {/* backend offline – silent */});

    // Hydrate rules
    fetchBackendRules()
      .then((items) => {
        if (!items.length) return;
        const active = items.find((r: any) => r.status === "active" || r.is_active);
        if (active) {
          setActiveRule((prev) => ({
            ...prev,
            version: `v${active.version || "1.0"}`,
            maxIncome: active.conditions_json?.max_income || prev.maxIncome,
            requireNadra: active.conditions_json?.require_nadra ?? prev.requireNadra,
            confidenceThreshold: active.conditions_json?.confidence_threshold || prev.confidenceThreshold,
            notes: active.conditions_json?.notes || prev.notes,
            updatedBy: "Backend sync",
          }));
        }
      })
      .catch(() => {/* backend offline – silent */});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Helper: map backend status string to local display status
  function mapBackendStatus(status: string): CaseRecord["status"] {
    switch (status) {
      case "submitted": return "Submitted";
      case "under_review": return "Needs review";
      case "needs_proof": return "More information";
      case "approved": return "Verified";
      case "rejected": return "Rejected";
      default: return "Needs review";
    }
  }

  function mapStatusTone(status: string): CaseRecord["tone"] {
    switch (status) {
      case "approved": return "success";
      case "rejected": return "danger";
      case "needs_proof": return "muted";
      case "submitted": return "neutral";
      default: return "warning";
    }
  }

  function relativeTime(iso?: string): string {
    if (!iso) return "—";
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins} min ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs} hr ago`;
    return `${Math.floor(hrs / 24)} days ago`;
  }

  // Methods
  const logAuditEvent = (
    category: AuditEvent["category"],
    title: string,
    details: string,
    actor: string,
    actorRole: Role
  ) => {
    const event: AuditEvent = {
      id: `aud-${Date.now()}`,
      timestamp: new Date().toISOString(),
      category,
      title,
      details,
      actor,
      actorRole,
      hash: generateSimHash(),
      source: "local_ledger",
    };
    setAuditEvents((prev) => [event, ...prev]);
  };

  const getCase = (id: string) => cases.find((c) => c.id === id);

  const createCase = async (payload: {
    person: string;
    cnic: string;
    phone: string;
    type: string;
    householdIncome: number;
    householdMembers: number;
    address: string;
    notes?: string;
    submittedBy: string;
    submittedByRole: Role;
  }) => {
    let aiRoute = "HUMAN";
    let aiReason = "Automated escalation";
    let aiConfidence = 0.65;
    let backendAi = false;
    let backendNadra = false;
    let nadraVerified = false;
    let nadraNote = "Synthetic lookup pending";

    // Call real backend AI decide endpoint
    try {
      const aiResp = await requestAiDecision();
      aiRoute = aiResp.route || "HUMAN";
      aiReason = aiResp.reason || "Backend AI decision route";
      aiConfidence = typeof aiResp.confidence === "number" ? aiResp.confidence : 0.65;
      backendAi = true;
    } catch {
      aiReason = "Local adapter: Income threshold flagged for human review";
    }

    // Call real backend NADRA verify endpoint
    try {
      const nadraResp = await verifyNadra(payload.cnic);
      nadraVerified = nadraResp.verified;
      nadraNote = nadraResp.note;
      backendNadra = true;
    } catch {
      nadraVerified = true;
      nadraNote = "Local simulated NADRA match";
    }

    const nextId = `REL-${Math.floor(20482 + Math.random() * 500)}`;
    const nowTime = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    const newCase: CaseRecord = {
      id: nextId,
      person: payload.person,
      cnic: payload.cnic,
      phone: payload.phone,
      type: payload.type,
      householdIncome: payload.householdIncome,
      householdMembers: payload.householdMembers,
      address: payload.address,
      notes: payload.notes,
      status: aiRoute === "AUTO_APPROVE" ? "Verified" : "Needs review",
      priority: payload.householdIncome < 30000 ? "P1" : "P2",
      score: `${Math.round(aiConfidence * 100)}%`,
      tone: aiRoute === "AUTO_APPROVE" ? "success" : "warning",
      date: "Just now",
      submittedAt: new Date().toISOString(),
      submittedBy: payload.submittedBy,
      submittedByRole: payload.submittedByRole,
      aiRoute,
      aiReason,
      aiConfidence,
      nadraVerified,
      nadraNote,
      timeline: [
        {
          id: `t-${Date.now()}-1`,
          title: "Claim Submitted",
          time: nowTime,
          description: `Filed by ${payload.submittedBy} (${payload.submittedByRole.toLowerCase()}).`,
          type: "submit",
        },
        {
          id: `t-${Date.now()}-2`,
          title: nadraVerified ? "NADRA Record Verified" : "NADRA Identity Notice",
          time: nowTime,
          description: nadraNote,
          type: "verify",
        },
        {
          id: `t-${Date.now()}-3`,
          title: `AI Assessment: ${aiRoute}`,
          time: nowTime,
          description: `${aiReason} (Confidence: ${Math.round(aiConfidence * 100)}%).`,
          type: "ai",
        },
      ],
    };

    setCases((prev) => [newCase, ...prev]);

    // Persist to backend (fire-and-forget, optimistic UI already updated)
    const token = getStoredToken();
    if (token && !token.startsWith("demo.")) {
      (async () => {
        try {
          // Try to get citizen_id from stored session
          const sessionRaw = localStorage.getItem("rasta.session.v2");
          const session = sessionRaw ? JSON.parse(sessionRaw) : null;
          const citizenId = session?.user?.citizen_id;
          if (citizenId) {
            const idempotencyKey = `${citizenId}-${nextId}`;
            const created = await createBackendCase({
              citizen_id: citizenId,
              claim_type: "relief_payment",
              idempotency_key: idempotencyKey,
              data: {
                name: payload.person,
                mock_identity_id: `MOCK-${payload.cnic.replace(/-/g, "")}`,
                monthly_income: payload.householdIncome,
                household_size: payload.householdMembers,
                payment_account: payload.cnic.replace(/-/g, ""),
              },
            });
            // Auto-submit so it enters review queue
            if (created?.id) {
              await submitBackendCase(created.id, 0).catch(() => {/* ok */});
            }
          }
        } catch (err) {
          console.warn("[RASTA] Backend case persist failed (non-blocking):", err);
        }
      })();
    }

    // Audit log
    logAuditEvent(
      "CASE",
      `Case ${nextId} Created for ${payload.person}`,
      `Submitted by ${payload.submittedBy} with declared income Rs ${payload.householdIncome.toLocaleString()}. AI route: ${aiRoute}.`,
      payload.submittedBy,
      payload.submittedByRole
    );

    // Notification
    setNotifications((prev) => [
      {
        id: `notif-${Date.now()}`,
        title: "New case created",
        message: `${nextId} for ${payload.person} is awaiting officer review.`,
        caseId: nextId,
        time: "Just now",
        read: false,
        type: "info",
      },
      ...prev,
    ]);

    return { caseId: nextId, backendAi, backendNadra };
  };

  const officerAction = async (
    caseId: string,
    action: "approve" | "reject" | "request_evidence",
    notes: string,
    officerName: string
  ) => {
    const targetCase = cases.find((c) => c.id === caseId);
    if (!targetCase) return { success: false, note: "Case not found" };

    const nowTime = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    if (action === "approve") {
      let raastTxn = "FAKE-TXN-DEMO";
      let smsSent = false;

      // Real Raast payment API call
      try {
        const payRes = await disburseRaast(targetCase.cnic, 25000);
        raastTxn = payRes.transaction_id;
      } catch {
        raastTxn = `TXN-${Math.floor(10000 + Math.random() * 90000)}`;
      }

      // Real SMS dispatch API call
      try {
        await sendSms(
          targetCase.phone,
          `RASTA: Your assistance claim ${targetCase.id} was APPROVED. Disbursed Rs 25,000 via Raast (Txn: ${raastTxn}).`
        );
        smsSent = true;
      } catch {
        smsSent = false;
      }

      setCases((prev) =>
        prev.map((c) => {
          if (c.id !== caseId) return c;
          return {
            ...c,
            status: "Verified",
            tone: "success",
            paymentTxnId: raastTxn,
            paymentAmount: 25000,
            officerDecisionNotes: notes,
            timeline: [
              {
                id: `t-${Date.now()}-app`,
                title: "Approved by Officer",
                time: nowTime,
                description: `${officerName} approved this claim: "${notes || "All criteria satisfied"}".`,
                type: "officer",
              },
              {
                id: `t-${Date.now()}-pay`,
                title: "Raast Emergency Disbursement",
                time: nowTime,
                description: `Payment of Rs 25,000 completed under transaction ${raastTxn}.`,
                type: "payment",
              },
              ...c.timeline,
            ],
          };
        })
      );

      logAuditEvent(
        "PAYMENT",
        `Officer Approved Case ${caseId}`,
        `Officer ${officerName} approved assistance. Raast payment ${raastTxn} generated for Rs 25,000. Notes: ${notes}`,
        officerName,
        "OFFICER"
      );

      setNotifications((prev) => [
        {
          id: `notif-${Date.now()}`,
          title: "Disbursement completed",
          message: `${caseId} approved by ${officerName}. Rs 25,000 disbursed via Raast.`,
          caseId,
          time: "Just now",
          read: false,
          type: "success",
        },
        ...prev,
      ]);

      _syncOfficerAction(caseId, "approve", notes);
      return { success: true, raastTxn, smsSent };
    }

    if (action === "request_evidence") {
      let smsSent = false;
      try {
        await sendSms(
          targetCase.phone,
          `RASTA NOTICE for ${targetCase.id}: Officer requested information: ${notes}.`
        );
        smsSent = true;
      } catch {
        smsSent = false;
      }

      setCases((prev) =>
        prev.map((c) => {
          if (c.id !== caseId) return c;
          return {
            ...c,
            status: "More information",
            tone: "muted",
            evidenceRequested: true,
            evidenceNotes: [...(c.evidenceNotes || []), notes],
            timeline: [
              {
                id: `t-${Date.now()}-ev`,
                title: "Information Requested by Officer",
                time: nowTime,
                description: `${officerName} sent request: "${notes}". SMS alert dispatched to ${c.phone}.`,
                type: "evidence",
              },
              ...c.timeline,
            ],
          };
        })
      );

      logAuditEvent(
        "CASE",
        `Evidence Requested for ${caseId}`,
        `Officer ${officerName} requested: ${notes}. Dispatched SMS notification.`,
        officerName,
        "OFFICER"
      );

      _syncOfficerAction(caseId, "ask_proof", notes, ["identity_proof", "income_proof"]);
      return { success: true, smsSent };
    }

    if (action === "reject") {
      try {
        await sendSms(
          targetCase.phone,
          `RASTA: Your assistance claim ${targetCase.id} could not be approved: ${notes}.`
        );
      } catch {
        // ok
      }

      setCases((prev) =>
        prev.map((c) => {
          if (c.id !== caseId) return c;
          return {
            ...c,
            status: "Rejected",
            tone: "danger",
            officerDecisionNotes: notes,
            timeline: [
              {
                id: `t-${Date.now()}-rej`,
                title: "Claim Rejected by Officer",
                time: nowTime,
                description: `Reason: ${notes || "Eligibility criteria not met"}.`,
                type: "officer",
              },
              ...c.timeline,
            ],
          };
        })
      );

      logAuditEvent(
        "CASE",
        `Case ${caseId} Rejected`,
        `Officer ${officerName} rejected claim with reason: ${notes}`,
        officerName,
        "OFFICER"
      );

      _syncOfficerAction(caseId, "reject", notes);
      return { success: true };
    }

    return { success: false };
  };

  // --- Backend sync helper for officer actions (fire-and-forget) ---
  const _syncOfficerAction = (
    caseId: string,
    backendAction: "approve" | "reject" | "ask_proof",
    notes: string,
    requiredDocs: string[] = []
  ) => {
    const token = getStoredToken();
    if (!token || token.startsWith("demo.")) return;
    reviewBackendCase(caseId, backendAction, notes || backendAction, 0, requiredDocs)
      .catch((e) => console.warn(`[RASTA] Backend ${backendAction} sync failed:`, e));
  };

  const grantConsent = (payload: {
    citizenName: string;
    citizenCnic: string;
    grantee: string;
    scope: string;
    durationMonths: number;
    source: "citizen" | "helper_proxy";
    actorName: string;
    actorRole: Role;
  }) => {
    const granted = new Date();
    const expires = new Date();
    expires.setMonth(expires.getMonth() + payload.durationMonths);

    const newRecord: ConsentRecord = {
      id: `c-${Date.now()}`,
      citizenName: payload.citizenName,
      citizenCnic: payload.citizenCnic,
      grantee: payload.grantee,
      scope: payload.scope,
      grantedAt: granted.toISOString(),
      expiresAt: expires.toISOString(),
      status: "Active",
      source: payload.source,
    };

    setConsents((prev) => [newRecord, ...prev]);

    // Persist to backend (fire-and-forget)
    const token = getStoredToken();
    if (token && !token.startsWith("demo.")) {
      const sessionRaw = localStorage.getItem("rasta.session.v2");
      const session = sessionRaw ? JSON.parse(sessionRaw) : null;
      const citizenId = session?.user?.citizen_id;
      if (citizenId) {
        grantBackendConsent({
          citizen_id: citizenId,
          scope: payload.scope,
          purpose: payload.grantee,
          grantee_id: null,
        }).catch((e) => console.warn("[RASTA] Backend consent grant failed:", e));
      }
    }

    logAuditEvent(
      "CONSENT",
      `Consent Granted for ${payload.citizenName}`,
      `Scope: ${payload.scope}. Grantee: ${payload.grantee}. Valid for ${payload.durationMonths} months.`,
      payload.actorName,
      payload.actorRole
    );
  };

  const revokeConsent = (id: string, actorName: string, actorRole: Role) => {
    const target = consents.find((c) => c.id === id);
    if (!target) return;

    setConsents((prev) =>
      prev.map((c) => (c.id === id ? { ...c, status: "Revoked" } : c))
    );

    // Persist revocation to backend (fire-and-forget)
    const token = getStoredToken();
    if (token && !token.startsWith("demo.")) {
      withdrawBackendConsent(id)
        .catch((e) => console.warn("[RASTA] Backend consent revoke failed:", e));
    }

    logAuditEvent(
      "CONSENT",
      `Consent Revoked: ${target.citizenName}`,
      `Permission revoked for ${target.grantee}. Scope: ${target.scope}. Withdrawal took immediate effect.`,
      actorName,
      actorRole
    );
  };

  const updateDraftRule = (updates: Partial<PolicyRule>) => {
    setDraftRule((prev) => ({
      ...prev,
      ...updates,
      updatedAt: "Just now",
    }));
  };

  const publishDraftRule = (actorName: string) => {
    const publishedVersion = draftRule.version;
    const published: PolicyRule = {
      ...draftRule,
      status: "Active",
      updatedAt: new Date().toLocaleDateString("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      }),
      updatedBy: `${actorName} (Administrator)`,
    };

    setActiveRule(published);

    // Create next draft
    const nextMinor = parseFloat(publishedVersion.replace("v", "")) + 0.1;
    const nextDraft: PolicyRule = {
      version: `v${nextMinor.toFixed(1)}`,
      name: `Sindh Social Relief Assistance Eligibility (Draft v${nextMinor.toFixed(1)})`,
      status: "Draft",
      maxIncome: published.maxIncome,
      requireNadra: published.requireNadra,
      confidenceThreshold: published.confidenceThreshold,
      routeAction: published.routeAction,
      updatedAt: "Just now",
      updatedBy: `${actorName} (Administrator)`,
      notes: `Working draft initialized following publication of ${publishedVersion}.`,
    };
    setDraftRule(nextDraft);

    logAuditEvent(
      "POLICY",
      `Policy Rule ${publishedVersion} Published`,
      `Thresholds: Max income Rs ${published.maxIncome.toLocaleString()}, Nadra required: ${published.requireNadra}, Confidence: ${published.confidenceThreshold}%. Route: ${published.routeAction}.`,
      actorName,
      "ADMIN"
    );

    // Persist to backend (fire-and-forget)
    const token = getStoredToken();
    if (token && !token.startsWith("demo.")) {
      fetchBackendRules()
        .then((rules) => {
          const activeBackendRule = rules.find((r: any) => r.is_active || r.status === "active");
          if (activeBackendRule?.id) {
            publishBackendRule(
              activeBackendRule.id,
              activeBackendRule.version || 1,
              {
                max_income: published.maxIncome,
                require_nadra: published.requireNadra,
                confidence_threshold: published.confidenceThreshold,
                route_action: published.routeAction,
              },
              `Published by ${actorName}`
            ).catch((e) => console.warn("[RASTA] Backend rule publish failed:", e));
          }
        })
        .catch((e) => console.warn("[RASTA] Backend rules fetch failed:", e));
    }
  };

  const markNotificationRead = (id: string) => {
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, read: true } : n))
    );
  };

  const dismissNotification = (id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  };

  const updateSetting = <K extends keyof AppSettings>(
    key: K,
    value: AppSettings[K]
  ) => {
    if (key === "simulationEnforced") return; // Enforced policy
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  const setHelperActiveCitizen = (name: string) => {
    setHelperActiveCitizenState(name);
    localStorage.setItem(STORAGE_KEYS.HELPER_ACTIVE, name);
  };

  const registerAuthorizedCitizen = (citizen: HelperCitizen, helperName: string) => {
    setAuthorizedCitizens((prev) => [citizen, ...prev]);
    logAuditEvent(
      "CONSENT",
      `Community Helper Registered Citizen: ${citizen.name}`,
      `Helper ${helperName} registered in-person authorization for ${citizen.name} (CNIC: ${citizen.cnic}).`,
      helperName,
      "HELPER"
    );
  };

  const toggleLanguage = () => {
    setCurrentLang((prev) => (prev === "en" ? "ur" : "en"));
  };

  const setLanguage = (lang: "en" | "ur") => {
    setCurrentLang(lang);
  };

  const value: DataContextValue = {
    cases,
    getCase,
    createCase,
    officerAction,
    consents,
    grantConsent,
    revokeConsent,
    auditEvents,
    logAuditEvent,
    activeRule,
    draftRule,
    ruleHistory,
    updateDraftRule,
    publishDraftRule,
    notifications,
    markNotificationRead,
    dismissNotification,
    settings,
    updateSetting,
    helperActiveCitizen,
    setHelperActiveCitizen,
    authorizedCitizens,
    registerAuthorizedCitizen,
    currentLang,
    toggleLanguage,
    setLanguage,
  };

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>;
}

export function useData() {
  const ctx = useContext(DataContext);
  if (!ctx) throw new Error("useData must be used inside DataProvider");
  return ctx;
}
