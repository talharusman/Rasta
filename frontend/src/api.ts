// OWNER: Member 4
// Browser client for RASTA backend APIs and synthetic hackathon adapters.
import type { AuthResult, AuthUser, Role } from "./types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type { Role, AuthUser, AuthResult };

export interface DemoAccount extends AuthUser {
  password: string;
  label: string;
  description: string;
}

export const demoAccounts: DemoAccount[] = [
  {
    id: "1a4c8fd6-5f1d-4d64-b143-e3ddbeeb7033",
    name: "Synthetic Citizen (Ayesha Bibi)",
    email: "citizen@rasta.com",
    password: "rasta-demo",
    role: "CITIZEN",
    label: "Citizen (Synthetic Citizen)",
    description: "Vulnerable applicant with pre-linked citizen profile",
    cnic: "99999-0000001-1",
    phone: "0300-0000001",
    avatarInitials: "SC",
    source: "demo",
  },
  {
    id: "7ad5b1c1-61ca-46bd-b2f0-1bb9dca2c17d",
    name: "Synthetic Helper (Sana Iqbal)",
    email: "helper@rasta.com",
    password: "rasta-demo",
    role: "HELPER",
    label: "Community Helper (Synthetic Helper)",
    description: "Field worker assisting citizens with consent & filings",
    phone: "0321-5551234",
    avatarInitials: "SH",
    source: "demo",
  },
  {
    id: "5b51743a-b609-42bb-88d3-55676a8dd357",
    name: "Synthetic Officer (Fatima Khan)",
    email: "officer@rasta.com",
    password: "rasta-demo",
    role: "OFFICER",
    label: "Department Officer (Synthetic Officer)",
    description: "Adjudicates claims, verifies identity, dispatches funds",
    avatarInitials: "SO",
    source: "demo",
  },
  {
    id: "e5da9580-182c-4163-b2fa-de6532ca4e54",
    name: "Synthetic Admin (Mariam Shah)",
    email: "admin@rasta.com",
    password: "rasta-demo",
    role: "ADMIN",
    label: "Administrator (Synthetic Admin)",
    description: "Manages system policy, rules v1, service health",
    avatarInitials: "SA",
    source: "demo",
  },
  {
    id: "6e51e997-8887-4da2-b1be-a28e98b964fe",
    name: "Synthetic Auditor (Omar Siddiqui)",
    email: "auditor@rasta.com",
    password: "rasta-demo",
    role: "AUDITOR",
    label: "Auditor (Synthetic Auditor)",
    description: "Read-only oversight of decision traces & immutable ledger",
    avatarInitials: "SU",
    source: "demo",
  },
];

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export function getStoredToken(): string | null {
  try {
    const raw = localStorage.getItem("rasta.session.v2");
    if (!raw) return null;
    const session = JSON.parse(raw);
    return session?.accessToken || null;
  } catch {
    return null;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getStoredToken();
  const headers = new Headers(init.headers || {});
  if (!headers.has("Content-Type") && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token && !headers.has("Authorization") && !token.startsWith("demo.")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers,
    });
  } catch (err) {
    throw new ApiError(0, `RASTA API endpoint (${path}) unreachable.`);
  }

  const contentType = response.headers.get("content-type") || "";
  let body: any = {};
  if (contentType.includes("application/json")) {
    body = await response.json().catch(() => ({}));
  }

  if (!response.ok) {
    const errMsg = body?.error?.message || body?.detail || body?.message || `Request failed with status ${response.status}`;
    throw new ApiError(response.status, errMsg);
  }
  return body as T;
}

function demoLogin(email: string, password: string): AuthResult {
  const account = demoAccounts.find((item) => item.email.toLowerCase() === email.trim().toLowerCase());
  if (!account || account.password !== password) {
    throw new ApiError(401, "Invalid credentials. Use a judge demo account or check email/password.");
  }
  const { password: _, label: __, description: ___, ...user } = account;
  return {
    accessToken: `demo.${user.id}.${Date.now()}`,
    user: { ...user, source: "demo" },
  };
}

export async function login(email: string, password: string): Promise<AuthResult> {
  try {
    const result = await request<{ access_token: string; refresh_token?: string }>(
      "/api/v1/auth/login",
      {
        method: "POST",
        body: JSON.stringify({ email: email.trim(), password }),
      }
    );
    // Fetch live actor profile from backend
    const currentUser = await getCurrentUser(result.access_token);
    return {
      accessToken: result.access_token,
      user: {
        ...currentUser,
        email: email.trim(),
        source: "api",
      },
    };
  } catch (error) {
    // If backend unreachable or login fails, fall back to matching demo account
    if (error instanceof ApiError && (error.status === 0 || error.status === 404 || error.status === 405 || error.status === 503)) {
      return demoLogin(email, password);
    }
    throw error;
  }
}

export async function getCurrentUser(token: string): Promise<AuthUser> {
  if (token.startsWith("demo.")) {
    const parts = token.split(".");
    const account = demoAccounts.find((a) => a.id === parts[1]);
    if (account) {
      const { password: _, label: __, description: ___, ...user } = account;
      return user;
    }
  }

  const result = await request<{
    id: string;
    name: string;
    role: string;
    is_active: boolean;
    tenant_id?: string;
    citizen_id?: string | null;
  }>("/api/v1/auth/me", {
    headers: { Authorization: `Bearer ${token}` },
  });

  const normalizedRole = (result.role ? result.role.toUpperCase() : "CITIZEN") as Role;
  return {
    id: result.id,
    name: result.name,
    email: "",
    role: normalizedRole,
    avatarInitials: result.name.split(" ").map((x) => x[0]).join("").slice(0, 2).toUpperCase(),
    source: "api",
    citizen_id: result.citizen_id ?? null,
  };
}

// REAL BACKEND INTEGRATION ENDPOINTS
export interface HealthStatus {
  service: string;
  status: string;
  connected: boolean;
}

export async function apiHealth(): Promise<{
  platform: HealthStatus;
  ai: HealthStatus;
  mock: HealthStatus;
}> {
  const check = async (path: string, serviceName: string): Promise<HealthStatus> => {
    try {
      const res = await request<{ service?: string; status?: string }>(path);
      return { service: res.service || serviceName, status: res.status || "ok", connected: true };
    } catch {
      return { service: serviceName, status: "offline (endpoint missing or server stopped)", connected: false };
    }
  };

  const [platform, ai, mock] = await Promise.all([
    check("/api/platform/health", "platform"),
    check("/api/ai/health", "ai"),
    check("/api/mock/health", "mock"),
  ]);

  return { platform, ai, mock };
}

// Backend platform methods
export async function fetchBackendCases(citizenId?: string): Promise<BackendCase[]> {
  const path = citizenId ? `/api/v1/cases?citizen_id=${citizenId}` : "/api/v1/cases";
  const res = await request<{ items: BackendCase[] }>(path);
  return res.items || [];
}

export async function fetchBackendReviewQueue(): Promise<BackendReviewCase[]> {
  const res = await request<{ items: BackendReviewCase[] }>("/api/v1/cases/review-queue");
  return res.items || [];
}

export async function fetchBackendCaseDetail(caseId: string): Promise<any> {
  return request<BackendCase>(`/api/v1/cases/${caseId}`);
}

export async function createBackendCase(payload: {
  citizen_id: string;
  claim_type?: string;
  idempotency_key: string;
  data: {
    name: string;
    mock_identity_id: string;
    monthly_income: number;
    household_size: number;
    payment_account: string;
    citizen_phone?: string;
  };
}): Promise<any> {
  return request<BackendCase>("/api/v1/cases", {
    method: "POST",
    body: JSON.stringify({
      claim_type: "relief_payment",
      ...payload,
    }),
  });
}

export async function submitBackendCase(caseId: string, expectedRevision: number): Promise<any> {
  return request<any>(`/api/v1/cases/${caseId}/submit`, {
    method: "POST",
    body: JSON.stringify({ expected_revision: expectedRevision }),
  });
}

export async function assignBackendOfficer(caseId: string, officerId: string, expectedRevision: number, reason: string): Promise<any> {
  return request<BackendCase>(`/api/v1/cases/${caseId}/assign`, {
    method: "POST",
    body: JSON.stringify({ officer_id: officerId, expected_revision: expectedRevision, reason }),
  });
}

export async function reviewBackendCase(
  caseId: string,
  action: "approve" | "reject" | "ask_proof",
  notes: string,
  expectedRevision: number,
  requiredDocuments: string[] = [],
  overrideReason?: string
): Promise<any> {
  return request<BackendCase>(`/api/v1/cases/${caseId}/review`, {
    method: "POST",
    body: JSON.stringify({
      action,
      notes,
      expected_revision: expectedRevision,
      required_documents: requiredDocuments,
      override_reason: overrideReason,
    }),
  });
}

export async function fetchBackendConsents(citizenId?: string): Promise<any[]> {
  const path = citizenId ? `/api/v1/consents?citizen_id=${citizenId}` : "/api/v1/consents";
  const res = await request<{ items: any[] }>(path);
  return res.items || [];
}

export async function grantBackendConsent(payload: {
  citizen_id: string;
  scope: string;
  purpose?: string | null;
  grantee_id?: string | null;
}): Promise<any> {
  return request<any>("/api/v1/consents", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function withdrawBackendConsent(consentId: string): Promise<any> {
  return request<any>(`/api/v1/consents/${consentId}/withdraw`, {
    method: "POST",
    body: "{}",
  });
}

export async function fetchBackendRules(): Promise<any[]> {
  const res = await request<{ items: any[] }>("/api/v1/rules");
  return res.items || [];
}

export async function publishBackendRule(ruleId: string, expectedVersion: number, conditions: any, reason: string): Promise<any> {
  return request<any>(`/api/v1/rules/${ruleId}`, {
    method: "PATCH",
    body: JSON.stringify({
      expected_version: expectedVersion,
      conditions_json: conditions,
      reason,
    }),
  });
}

export async function fetchBackendAuditLogs(): Promise<any[]> {
  const res = await request<{ items: any[] }>("/api/v1/audit-logs?limit=50");
  return res.items || [];
}

export async function fetchBackendMetrics(): Promise<any> {
  return request<any>("/api/v1/metrics/summary");
}

export interface ScamAssessment {
  label: "likely_scam" | "uncertain" | "no_scam_indicators";
  confidence: number;
  indicators: string[];
  explanation: string;
  recommended_action: string;
}

export async function checkBackendScam(citizenId: string, text: string): Promise<ScamAssessment> {
  const result = await request<{ payload: ScamAssessment }>("/api/v1/scam-checks", {
    method: "POST",
    body: JSON.stringify({ citizen_id: citizenId, text }),
  });
  return result.payload;
}

// AI and Mocks integration
export interface AiDecisionResponse {
  route: string;
  reason: string;
  confidence: number;
}

export async function requestAiDecision(): Promise<AiDecisionResponse> {
  return request<AiDecisionResponse>("/api/ai/decide", {
    method: "POST",
    body: "{}",
  });
}

export type NadraFailureScenario = "normal" | "timeout" | "not_found" | "name_mismatch";
export type RaastFailureScenario = "normal" | "mismatch" | "timeout";

export interface DemoFailureScenarios {
  nadra: NadraFailureScenario;
  raast: RaastFailureScenario;
}

export const DEMO_FAILURES_KEY = "rasta.demo.failure_scenarios";

export function getDemoFailureScenarios(): DemoFailureScenarios {
  try {
    const raw = localStorage.getItem(DEMO_FAILURES_KEY);
    if (!raw) return { nadra: "normal", raast: "normal" };
    const parsed = JSON.parse(raw);
    return {
      nadra: parsed.nadra || "normal",
      raast: parsed.raast || "normal",
    };
  } catch {
    return { nadra: "normal", raast: "normal" };
  }
}

export function saveDemoFailureScenarios(scenarios: DemoFailureScenarios): void {
  try {
    localStorage.setItem(DEMO_FAILURES_KEY, JSON.stringify(scenarios));
  } catch {}
}

export interface NadraVerifyResponse {
  verified: boolean;
  name?: string;
  note: string;
}

export async function verifyNadra(cnic: string): Promise<NadraVerifyResponse> {
  const scenario = getDemoFailureScenarios();
  if (scenario.nadra === "timeout") {
    await new Promise((resolve) => setTimeout(resolve, 800));
    throw new ApiError(504, "Simulated Timeout: NADRA identity gateway did not respond within the deadline.");
  }
  if (scenario.nadra === "not_found") {
    return {
      verified: false,
      note: "Simulated Record Not Found: Citizen identity does not exist in the NADRA database.",
    };
  }
  if (scenario.nadra === "name_mismatch") {
    return {
      verified: false,
      name: "Different Person",
      note: "Simulated Name Mismatch: Record name does not match citizen claim.",
    };
  }

  return request<NadraVerifyResponse>("/api/mock/nadra/verify", {
    method: "POST",
    body: JSON.stringify({ cnic }),
  });
}

export interface RaastPayResponse {
  status: string;
  transaction_id: string;
  cnic: string;
  amount: number;
  note: string;
}

export async function disburseRaast(cnic: string, amount: number): Promise<RaastPayResponse> {
  const scenario = getDemoFailureScenarios();
  if (scenario.raast === "timeout") {
    await new Promise((resolve) => setTimeout(resolve, 800));
    throw new ApiError(504, "Simulated Timeout: Raast payment switch timed out.");
  }
  if (scenario.raast === "mismatch") {
    throw new ApiError(422, "Simulated Account Mismatch: Raast title fetch failed for beneficiary account.");
  }

  return request<RaastPayResponse>("/api/mock/raast/pay", {
    method: "POST",
    body: JSON.stringify({ cnic, amount }),
  });
}

export interface SmsSendResponse {
  status: string;
  to: string;
  message: string;
  note: string;
}

export async function sendSms(phone: string, message: string): Promise<SmsSendResponse> {
  return request<SmsSendResponse>("/api/mock/sms/send", {
    method: "POST",
    body: JSON.stringify({ phone, message }),
  });
}

export type EvidenceType = "identity_proof" | "income_proof";

export interface BackendCase {
  case_id: string;
  status: "draft" | "submitted" | "processing" | "cleared" | "needs_proof" | "human_review" | "approved" | "rejected" | "closed";
  revision: number;
  assigned_officer_id: string | null;
  created_at: string;
  claim_type: string;
  user_explanation: string | null;
  user_explanation_ur?: string | null;
  required_documents: EvidenceType[];
  data: {
    name: string;
    mock_identity_id: string;
    monthly_income: number;
    household_size: number;
    payment_account: string;
    citizen_phone?: string | null;
  };
  documents: { id: string; type: EvidenceType; content_type: string; sha256: string }[];
  decision?: { route: string; confidence: number | null; identity_verified: boolean; rule_version: number; model_version: string | null };
  payment?: { status: "queued" | "pending" | "confirmed" | "failed"; amount: number | null; transaction_id: string | null } | null;
}

export type BackendReviewCase = Pick<BackendCase, "case_id" | "status" | "revision" | "assigned_officer_id" | "created_at">;

export async function fetchBackendCitizens() {
  const result = await request<{ items: { id: string; name: string; mock_identity_id: string }[] }>("/api/v1/citizens");
  return result.items;
}

export async function fetchBackendNotifications() {
  const result = await request<{ items: { id: string; case_id: string; message: string; created_at: string; delivery_state: string }[] }>("/api/v1/notifications");
  return result.items;
}

export async function uploadBackendEvidence(caseId: string, revision: number, type: EvidenceType, file: File) {
  const body = new FormData();
  body.append("file", file);
  body.append("type", type);
  body.append("expected_revision", String(revision));
  return request<{ revision: number }>(`/api/v1/cases/${caseId}/documents`, { method: "POST", body });
}

export async function downloadBackendEvidence(caseId: string, documentId: string): Promise<Blob> {
  const token = getStoredToken();
  if (!token || token.startsWith("demo.")) throw new Error("Sign in to view this document.");
  const response = await fetch(
    `${API_URL}/api/v1/cases/${encodeURIComponent(caseId)}/documents/${encodeURIComponent(documentId)}`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(response.status, body?.error?.message ?? "The document could not be downloaded.");
  }
  return response.blob();
}

export async function fetchBackendHistory(caseId: string) {
  return request<{ items: { id: string; action: string; notes: string; created_at: string }[] }>(
    `/api/v1/cases/${caseId}/history`
  );
}

export async function fetchBackendTrace(caseId: string) {
  return request<{
    rule_version: number;
    payload: {
      model_version?: string;
      reason?: string;
      flags?: string[];
      auditor_trace?: { evaluate_trace?: { routing_reason?: string } | null };
    };
  }>(`/api/v1/cases/${caseId}/decision-trace`);
}
