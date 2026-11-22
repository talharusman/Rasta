// Central state store for RASTA with local persistence and real backend integration
import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import {
  ApiError,
  assignBackendOfficer,
  createBackendCase,
  fetchBackendCaseDetail,
  fetchBackendCitizens,
  fetchBackendNotifications,
  fetchBackendReviewQueue,
  uploadBackendEvidence,
  type BackendCase,
  type BackendReviewCase,
  type EvidenceType,
  fetchBackendAuditLogs,
  fetchBackendCases,
  fetchBackendConsents,
  fetchBackendRules,
  grantBackendConsent,
  publishBackendRule,
  requestAiDecision,
  reviewBackendCase,
  sendSms,
  simulateRaastDisbursement,
  submitBackendCase,
  verifyNadra,
  withdrawBackendConsent,
} from "./api";
import { useAuth } from "./auth";
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
  id?: string;
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
    dob?: string;
    type: string;
    householdIncome: number;
    householdMembers: number;
    address: string;
    notes?: string;
    submittedBy: string;
    submittedByRole: Role;
    paymentAccount?: string;
    idempotencyKey?: string;
    evidence?: Partial<Record<EvidenceType, File>>;
  }) => Promise<{ caseId: string; backendAi: boolean; backendNadra: boolean }>;
  assignCase: (caseId: string, revision: number) => Promise<void>;
  resumeCase: (caseId: string, evidence: Partial<Record<EvidenceType, File>>) => Promise<void>;
  officerAction: (
    caseId: string,
    action: "approve" | "reject" | "request_evidence",
    notes: string,
    officerName: string,
    overrideReason?: string
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
  }) => Promise<void>;
  revokeConsent: (id: string, actorName: string, actorRole: Role) => Promise<void>;

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
  publishDraftRule: (actorName: string) => Promise<void>;

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
    ruleVersion: 1,
    modelVersion: "fast-relief-v2",
    requiredDocuments: ["identity_proof", "income_proof"],
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
    ruleVersion: 1,
    modelVersion: "fast-relief-v1",
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
    ruleVersion: 1,
    modelVersion: "fast-relief-v1",
    requiredDocuments: ["identity_proof", "income_proof"],
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
    ruleVersion: 1,
    modelVersion: "fast-relief-v1",
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
    ruleVersion: 1,
    modelVersion: "fast-relief-v1",
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
    ruleVersion: 1,
    modelVersion: "fast-relief-v2",
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
  const { user } = useAuth();
  const liveActor = user?.source === "api" ? user.id : undefined;
  const liveRole = user?.source === "api" ? user.role : undefined;
  const [live, setLive] = useState<{
    owner: string;
    cases: CaseRecord[];
    citizens: HelperCitizen[];
    notifications: NotificationItem[];
    consents: ConsentRecord[];
    audit: AuditEvent[];
  }>();
  const [notificationActions, setNotificationActions] = useState<{
    owner: string; read: string[]; dismissed: string[];
  }>();
  const [livePolicy, setLivePolicy] = useState<{ owner: string; policy: PolicyRule }>();
  const [refreshVersion, setRefreshVersion] = useState(0);
  const refreshLive = () => setRefreshVersion((value) => value + 1);

  const [demoCases, setCases] = useState<CaseRecord[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.CASES);
      return saved ? (JSON.parse(saved) as CaseRecord[]).filter((item) => !("backendId" in item)) : initialCases;
    } catch {
      return initialCases;
    }
  });

  // Consents state
  const [demoConsents, setConsents] = useState<ConsentRecord[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.CONSENTS);
      return saved ? JSON.parse(saved) : initialConsents;
    } catch {
      return initialConsents;
    }
  });

  // Audit state
  const [demoAudit, setAuditEvents] = useState<AuditEvent[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.AUDIT);
      return saved ? JSON.parse(saved) : initialAudit;
    } catch {
      return initialAudit;
    }
  });

  // Rules state
  const [demoRule, setActiveRule] = useState<PolicyRule>(() => {
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
  const [demoNotifications, setNotifications] = useState<NotificationItem[]>(() => {
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

  const [demoCitizens, setAuthorizedCitizens] = useState<HelperCitizen[]>(() => {
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
    localStorage.setItem(STORAGE_KEYS.CASES, JSON.stringify(demoCases));
  }, [demoCases]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.CONSENTS, JSON.stringify(demoConsents));
  }, [demoConsents]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.AUDIT, JSON.stringify(demoAudit.filter((event) => event.source !== "api")));
  }, [demoAudit]);

  useEffect(() => {
    if (liveActor) return;
    localStorage.setItem(
      STORAGE_KEYS.RULES,
      JSON.stringify({ active: demoRule, draft: draftRule })
    );
  }, [liveActor, demoRule, draftRule]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.NOTIFICATIONS, JSON.stringify(demoNotifications));
  }, [demoNotifications]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.SETTINGS, JSON.stringify(settings));
  }, [settings]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.CITIZENS, JSON.stringify(demoCitizens));
  }, [demoCitizens]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.LANG, currentLang);
  }, [currentLang]);

  const activeRule = liveActor && livePolicy?.owner === liveActor ? livePolicy.policy : demoRule;
  const currentLive = liveActor && live?.owner === liveActor ? live : undefined;
  const cases = liveActor ? currentLive?.cases ?? [] : demoCases;
  const consents = liveActor ? currentLive?.consents ?? [] : demoConsents;
  const auditEvents = liveActor ? currentLive?.audit ?? [] : demoAudit;
  const actions = notificationActions?.owner === liveActor ? notificationActions : undefined;
  const notifications = liveActor
    ? (currentLive?.notifications ?? []).filter((item) => !actions?.dismissed.includes(item.id))
      .map((item) => ({ ...item, read: actions?.read.includes(item.id) ?? false }))
    : demoNotifications;
  const authorizedCitizens = liveActor ? currentLive?.citizens ?? [] : demoCitizens;

  useEffect(() => {
    if (!liveActor || !liveRole) {
      setLive(undefined);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      const [casesResult, queueResult, citizensResult, consentsResult, notificationsResult, auditResult] =
        await Promise.allSettled([
          fetchBackendCases(),
          liveRole === "OFFICER" ? fetchBackendReviewQueue() : Promise.resolve([]),
          liveRole === "HELPER" ? fetchBackendCitizens() : Promise.resolve([]),
          liveRole !== "OFFICER" ? fetchBackendConsents() : Promise.resolve([]),
          fetchBackendNotifications(),
          liveRole === "ADMIN" || liveRole === "AUDITOR" ? fetchBackendAuditLogs() : Promise.resolve([]),
        ]);
      if (cancelled) return;
      const rows = new Map<string, BackendReviewCase>();
      for (const result of [queueResult, casesResult]) {
        if (result.status === "fulfilled") {
          for (const row of result.value) rows.set(row.case_id, row);
        }
      }
      const owned = {
        owner: liveActor,
        cases: [...rows.values()].map(mapBackendCase),
        citizens: citizensResult.status === "fulfilled" ? citizensResult.value.map((citizen) => ({
          id: citizen.id, name: citizen.name, cnic: citizen.mock_identity_id, phone: "",
          relationship: "Authorized citizen", consentActive: true,
          casesCount: 0,
        })) : [],
        consents: consentsResult.status === "fulfilled" ? consentsResult.value.map((row) => ({
          id: row.id, citizenName: row.citizen_id, citizenCnic: "",
          grantee: row.grantee_id ?? "Relief processing", scope: row.scope,
          grantedAt: row.created_at, expiresAt: "", status: row.revoked_at ? "Revoked" as const : "Active" as const,
          source: "citizen" as const,
        })) : [],
        notifications: notificationsResult.status === "fulfilled" ? notificationsResult.value.map((row) => ({
          id: row.id, title: "Case update", message: row.message, caseId: row.case_id,
          time: relativeTime(row.created_at), read: false, type: "info" as const,
        })) : [],
        audit: auditResult.status === "fulfilled" ? auditResult.value.map((row) => ({
          id: row.id, timestamp: row.created_at, category: "CASE" as const,
          title: row.action, actor: row.actor_id ?? row.actor_type, actorRole: "ADMIN" as const,
          details: JSON.stringify(row.details), hash: row.id, source: "api" as const,
          ruleVersion: row.details?.rule_version, modelVersion: row.details?.model_version,
        })) : [],
      };
      setLive(owned);
      timer = setTimeout(load, 5000);
    };
    void load();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [liveActor, liveRole, refreshVersion]);

  useEffect(() => {
    if (!liveActor || !liveRole || !["OFFICER", "ADMIN", "AUDITOR"].includes(liveRole)) return;
    let cancelled = false;
    void fetchBackendRules().then((rules) => {
      const active = rules.find((rule) => rule.active);
      if (cancelled || !active) return;
      const policy: PolicyRule = {
        version: `v${active.version}`, name: active.rule_name, status: "Active",
        maxIncome: active.conditions_json.max_monthly_income, requireNadra: true,
        confidenceThreshold: Math.round(active.conditions_json.clear_confidence_min * 100),
        routeAction: "HUMAN", updatedAt: active.created_at, updatedBy: "Published policy", notes: "",
      };
      setLivePolicy({ owner: liveActor, policy });
      setDraftRule({ ...policy, status: "Draft" });
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [liveActor, liveRole]);

  function mapBackendCase(row: BackendReviewCase & Partial<BackendCase>): CaseRecord {
    const labels: Record<BackendCase["status"], CaseRecord["status"]> = {
      draft: "Draft", submitted: "Submitted", processing: "Processing", cleared: "Checks passed",
      needs_proof: "More information", human_review: "Needs review",
      approved: "Verified", rejected: "Rejected", closed: "Closed",
    };
    const confidence = row.decision?.confidence ?? row.confidence;
    const tone = row.status === "approved" ? "success" : row.status === "rejected" ? "danger"
      : row.status === "human_review" ? "warning" : "neutral";
    return {
      id: row.case_id, person: row.data?.name ?? "Unassigned case", cnic: row.data?.mock_identity_id ?? "—",
      phone: row.data?.citizen_phone ?? "—", type: row.claim_type ?? "Relief assistance",
      householdIncome: row.data?.monthly_income ?? 0, householdMembers: row.data?.household_size ?? 0,
      address: "—", status: labels[row.status], tone,
      priority: row.data && row.data.monthly_income < 30000 ? "P1" : "P2",
      score: confidence == null ? "—" : `${Math.round(confidence * 100)}%`,
      date: relativeTime(row.created_at), submittedAt: row.created_at, submittedBy: row.data?.name ?? "—",
      submittedByRole: "CITIZEN", aiRoute: row.decision?.route ?? "Pending",
      aiReason: row.user_explanation ?? "Automated assessment pending.",
      aiReasonUr: row.user_explanation_ur ?? undefined,
      aiConfidence: confidence ?? 0, nadraVerified: row.decision?.identity_verified,
      dob: row.data?.dob ?? undefined, citizenId: row.citizen_id,
      ruleVersion: row.decision?.rule_version, modelVersion: row.decision?.model_version,
      timeline: [], backendStatus: row.status, backendRevision: row.revision,
      requiredDocuments: row.required_documents, documents: row.documents, assignedOfficerId: row.assigned_officer_id,
      paymentStatus: row.payment?.status, paymentTxnId: row.payment?.transaction_id ?? undefined,
      paymentAmount: row.payment?.amount ?? undefined,
    };
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
  const demoSubmittedKeys = useRef<Map<string, { caseId: string; backendAi: boolean; backendNadra: boolean }>>(new Map());

  const createCase = async (payload: {
    person: string;
    cnic: string;
    phone: string;
    dob?: string;
    type: string;
    householdIncome: number;
    householdMembers: number;
    address: string;
    notes?: string;
    submittedBy: string;
    submittedByRole: Role;
    paymentAccount?: string;
    idempotencyKey?: string;
    evidence?: Partial<Record<EvidenceType, File>>;
  }) => {
    if (liveActor) {
      const citizenId = user?.role === "HELPER"
        ? authorizedCitizens.find((citizen) => citizen.name === helperActiveCitizen)?.id
        : user?.citizen_id;
      if (!citizenId) throw new Error("Select an authorized citizen first.");
      if (user?.role === "CITIZEN") {
        for (const scope of ["identity:verify", "ai:process"]) {
          await grantBackendConsent({ citizen_id: citizenId, scope, purpose: "processing" });
        }
      }
      const identity = payload.cnic.trim().toUpperCase();
      const phone = payload.phone.replace(/[ -]/g, "");
      if (phone && !/^\+920[0-9]{9}$/.test(phone)) {
        throw new Error("Enter a synthetic SMS number such as +920000000001, or leave it blank.");
      }
      const created = await createBackendCase({
        citizen_id: citizenId,
        idempotency_key: payload.idempotencyKey ?? crypto.randomUUID(),
        data: {
          name: payload.person,
          mock_identity_id: identity.startsWith("MOCK-") ? identity : `MOCK-${identity.replace(/-/g, "")}`,
          payment_account: payload.paymentAccount?.trim().toUpperCase() ?? "",
          monthly_income: payload.householdIncome, household_size: payload.householdMembers,
          citizen_phone: phone || undefined,
          dob: payload.dob || undefined,
        },
      });
      if (created.status === "draft") await uploadAndSubmit(created, payload.evidence ?? {});
      refreshLive();
      return { caseId: created.case_id, backendAi: false, backendNadra: false };
    }
    if (!liveActor && payload.idempotencyKey && demoSubmittedKeys.current.has(payload.idempotencyKey)) {
      return demoSubmittedKeys.current.get(payload.idempotencyKey)!;
    }

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
      // A failed or unreachable identity check is never treated as verified.
      nadraVerified = false;
      nadraNote = "Identity service unavailable - routed to a human officer";
    }

    const nextId = `REL-${Math.floor(20482 + Math.random() * 500)}`;
    const nowTime = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    const newCase: CaseRecord = {
      id: nextId,
      person: payload.person,
      cnic: payload.cnic,
      dob: payload.dob,
      phone: payload.phone,
      type: payload.type,
      householdIncome: payload.householdIncome,
      householdMembers: payload.householdMembers,
      address: payload.address,
      notes: payload.notes,
      status: aiRoute === "AUTO_APPROVE" && nadraVerified ? "Checks passed" : "Needs review",
      priority: payload.householdIncome < 30000 ? "P1" : "P2",
      score: `${Math.round(aiConfidence * 100)}%`,
      tone: aiRoute === "AUTO_APPROVE" && nadraVerified ? "success" : "warning",
      date: "Just now",
      submittedAt: new Date().toISOString(),
      submittedBy: payload.submittedBy,
      submittedByRole: payload.submittedByRole,
      aiRoute,
      aiReason,
      aiConfidence,
      ruleVersion: 1,
      modelVersion: "fast-relief-v2",
      requiredDocuments: ["identity_proof", "income_proof"],
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

    const outcome = { caseId: nextId, backendAi, backendNadra };
    if (payload.idempotencyKey) {
      demoSubmittedKeys.current.set(payload.idempotencyKey, outcome);
    }
    return outcome;
  };

  async function uploadAndSubmit(current: BackendCase, evidence: Partial<Record<EvidenceType, File>>) {
    let revision = current.revision;
    for (const [type, file] of Object.entries(evidence) as [EvidenceType, File][]) {
      const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
      const sha = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
      if (!current.documents.some((document) => document.type === type && document.sha256 === sha)
          || current.status === "needs_proof") {
        revision = (await uploadBackendEvidence(current.case_id, revision, type, file)).revision;
      }
    }
    await submitBackendCase(current.case_id, revision);
  }

  async function assignCase(caseId: string, revision: number) {
    if (!liveActor || liveRole !== "OFFICER") throw new Error("Officer session required.");
    await assignBackendOfficer(caseId, liveActor, revision, "Assigned for review");
    refreshLive();
  }

  async function resumeCase(caseId: string, evidence: Partial<Record<EvidenceType, File>>) {
    if (liveActor) {
      await uploadAndSubmit(await fetchBackendCaseDetail(caseId), evidence);
      refreshLive();
    } else {
      const nowTime = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      const uploadedTypes = Object.keys(evidence) as EvidenceType[];
      setCases((prev) =>
        prev.map((c) => {
          if (c.id !== caseId) return c;
          const newDocs = uploadedTypes.map((type, idx) => ({
            id: `doc-${Date.now()}-${idx}`,
            type,
            content_type: evidence[type]?.type || "image/jpeg",
            sha256: `demo-sha256-${Date.now()}-${idx}`,
          }));
          return {
            ...c,
            status: "Needs review" as const,
            tone: "warning" as const,
            evidenceRequested: false,
            documents: [...(c.documents || []), ...newDocs],
            timeline: [
              {
                id: `t-${Date.now()}-resub`,
                title: "Updated Information Submitted",
                time: nowTime,
                description: `Citizen submitted updated documents: ${uploadedTypes.map((t) => t.replace(/_/g, " ")).join(", ") || "Supporting files"}. Pending officer review.`,
                type: "evidence" as const,
              },
              ...c.timeline,
            ],
          };
        })
      );
      setNotifications((prev) => [
        {
          id: `notif-${Date.now()}`,
          title: "Documents Resubmitted",
          message: `Updated evidence received for ${caseId}. Pending officer review.`,
          caseId,
          time: "Just now",
          read: false,
          type: "info",
        },
        ...prev,
      ]);
    }
  }

  const officerAction = async (
    caseId: string,
    action: "approve" | "reject" | "request_evidence",
    notes: string,
    officerName: string,
    overrideReason?: string
  ) => {
    const targetCase = cases.find((c) => c.id === caseId);
    if (!targetCase) return { success: false, note: "Case not found" };

    if (liveActor) {
      try {
        let current = targetCase;
        if (!current.assignedOfficerId && liveRole === "OFFICER") {
          const assigned = await assignBackendOfficer(caseId, liveActor, current.backendRevision!, "Assigned for review");
          current = mapBackendCase(assigned);
        }
        const backendAction = action === "request_evidence" ? "ask_proof" : action;
        await reviewBackendCase(caseId, backendAction, notes || backendAction, current.backendRevision!,
          backendAction === "ask_proof" ? ["identity_proof", "income_proof"] : [], overrideReason);
        refreshLive();
        return { success: true };
      } catch (error) {
        refreshLive();
        const note = error instanceof ApiError && error.status === 409
          ? `${error.message} The case will refresh.`
          : error instanceof Error ? error.message : "Review failed.";
        return { success: false, note };
      }
    }

    const nowTime = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    if (action === "approve") {
      // Offline demo only: a locally simulated payment (honours the admin's
      // simulated Raast timeout / mismatch scenarios). No network call.
      let raastTxn: string;
      let smsSent = false;

      try {
        raastTxn = (await simulateRaastDisbursement(25000)).transaction_id;
      } catch (error) {
        return { success: false, note: error instanceof Error ? error.message : "Demo payment failed." };
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
            requiredDocuments: c.requiredDocuments && c.requiredDocuments.length > 0
              ? c.requiredDocuments
              : ["identity_proof", "income_proof"],
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

      return { success: true };
    }

    return { success: false };
  };

  // --- Backend sync helper for officer actions (fire-and-forget) ---
  const grantConsent = async (payload: {
    citizenName: string;
    citizenCnic: string;
    grantee: string;
    scope: string;
    durationMonths: number;
    source: "citizen" | "helper_proxy";
    actorName: string;
    actorRole: Role;
  }) => {
    if (liveActor) {
      if (!user?.citizen_id || user.role !== "CITIZEN") throw new Error("Only the citizen can grant access.");
      const scopes = payload.scope === "processing"
        ? ["identity:verify", "ai:process"] : ["case:read", "case:write", "document:upload", "case:submit"];
      await Promise.all(scopes.map((scope) => grantBackendConsent({ citizen_id: user.citizen_id!, scope,
        ...(payload.scope === "processing" ? { purpose: "processing" } : { grantee_id: payload.grantee }) })));
      refreshLive();
      return;
    }
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

    logAuditEvent(
      "CONSENT",
      `Consent Granted for ${payload.citizenName}`,
      `Scope: ${payload.scope}. Grantee: ${payload.grantee}. Valid for ${payload.durationMonths} months.`,
      payload.actorName,
      payload.actorRole
    );
  };

  const revokeConsent = async (id: string, actorName: string, actorRole: Role) => {
    if (liveActor) {
      await withdrawBackendConsent(id);
      refreshLive();
      return;
    }
    const target = consents.find((c) => c.id === id);
    if (!target) return;

    setConsents((prev) =>
      prev.map((c) => (c.id === id ? { ...c, status: "Revoked" } : c))
    );

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

  const publishDraftRule = async (actorName: string) => {
    if (liveActor) {
      const active = (await fetchBackendRules()).find((rule) => rule.active);
      if (!active) throw new Error("No active policy is configured.");
      const published = await publishBackendRule(active.id, active.version, {
        ...active.conditions_json,
        max_monthly_income: draftRule.maxIncome,
        clear_confidence_min: draftRule.confidenceThreshold / 100,
      }, `Published by ${actorName}`);
      setLivePolicy({ owner: liveActor, policy: { ...draftRule, status: "Active",
        version: `v${published.version}`, updatedBy: actorName } });
      return;
    }
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


  };

  const updateNotificationActions = (id: string, action: "read" | "dismissed") => {
    if (!liveActor) return;
    setNotificationActions((previous) => {
      const current = previous?.owner === liveActor ? previous : { owner: liveActor, read: [], dismissed: [] };
      return { ...current, [action]: [...new Set([...current[action], id])] };
    });
  };

  const markNotificationRead = (id: string) => {
    if (liveActor) return updateNotificationActions(id, "read");
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, read: true } : n))
    );
  };

  const dismissNotification = (id: string) => {
    if (liveActor) return updateNotificationActions(id, "dismissed");
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
    assignCase,
    resumeCase,
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
