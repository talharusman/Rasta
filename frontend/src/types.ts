export type Role = "CITIZEN" | "HELPER" | "OFFICER" | "ADMIN" | "AUDITOR";

export interface AuthUser {
  id: string;
  name: string;
  email: string;
  role: Role;
  source: "api" | "demo";
  cnic?: string;
  phone?: string;
  avatarInitials: string;
  citizen_id?: string | null;
}

export interface AuthResult {
  accessToken: string;
  refreshToken?: string;
  user: AuthUser;
}

export interface TimelineEntry {
  id: string;
  title: string;
  time: string;
  description: string;
  type: "submit" | "verify" | "ai" | "officer" | "payment" | "evidence";
}

export interface CaseRecord {
  backendStatus?: import("./api").BackendCase["status"];
  backendRevision?: number;
  paymentStatus?: NonNullable<import("./api").BackendCase["payment"]>["status"];
  requiredDocuments?: import("./api").EvidenceType[];
  documents?: import("./api").BackendCase["documents"];
  assignedOfficerId?: string | null;
  id: string;
  person: string;
  cnic: string;
  dob?: string;
  citizenId?: string;
  phone: string;
  type: string;
  householdIncome: number;
  householdMembers: number;
  address: string;
  notes?: string;
  status: "Draft" | "Submitted" | "Processing" | "Checks passed" | "Needs review" | "More information" | "Verified" | "Rejected" | "Closed";
  priority: "P1" | "P2" | "P3";
  score: string;
  tone: "warning" | "success" | "muted" | "neutral" | "danger";
  date: string;
  submittedAt: string;
  submittedBy: string;
  submittedByRole: Role;
  aiRoute: string;
  aiReason: string;
  aiReasonUr?: string;
  aiConfidence: number;
  ruleVersion?: number;
  modelVersion?: string | null;
  nadraVerified?: boolean;
  nadraNote?: string;
  evidenceRequested?: boolean;
  evidenceNotes?: string[];
  officerDecisionNotes?: string;
  paymentTxnId?: string;
  paymentAmount?: number;
  timeline: TimelineEntry[];
}

export interface ConsentRecord {
  id: string;
  citizenName: string;
  citizenCnic: string;
  grantee: string;
  scope: string;
  grantedAt: string;
  expiresAt: string;
  status: "Active" | "Revoked";
  source: "citizen" | "helper_proxy";
}

export interface AuditEvent {
  id: string;
  timestamp: string;
  title: string;
  category: "CASE" | "AI_DECISION" | "NADRA" | "PAYMENT" | "CONSENT" | "POLICY" | "SECURITY";
  actor: string;
  actorRole: Role;
  details: string;
  hash: string;
  source: "api" | "local_ledger";
  ruleVersion?: number | string;
  modelVersion?: string | null;
}

export interface PolicyRule {
  version: string;
  name: string;
  status: "Active" | "Draft" | "Archived";
  maxIncome: number;
  requireNadra: boolean;
  confidenceThreshold: number;
  routeAction: "HUMAN" | "AUTO_APPROVE";
  updatedAt: string;
  updatedBy: string;
  notes: string;
}

export interface NotificationItem {
  id: string;
  title: string;
  message: string;
  caseId?: string;
  time: string;
  read: boolean;
  type: "alert" | "info" | "success";
}

export interface AppSettings {
  urduEntryPoint: boolean;
  voiceAssistance: boolean;
  lowBandwidth: boolean;
  prototypeDisclaimer: boolean;
  simulationEnforced: boolean;
}
