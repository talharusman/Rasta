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
    id: "demo-citizen",
    name: "Ayesha Bibi",
    email: "citizen@demo.rasta.pk",
    password: "rasta-demo",
    role: "CITIZEN",
    label: "Citizen (Ayesha Bibi)",
    description: "Vulnerable applicant, Urdu preferred, submitted REL-20481",
    cnic: "99999-0000001-1",
    phone: "0300-0000001",
    avatarInitials: "AB",
    source: "demo",
  },
  {
    id: "demo-helper",
    name: "Sana Iqbal",
    email: "helper@demo.rasta.pk",
    password: "rasta-demo",
    role: "HELPER",
    label: "Community Helper (Sana Iqbal)",
    description: "Field worker assisting citizens with consent & filings",
    phone: "0321-5551234",
    avatarInitials: "SI",
    source: "demo",
  },
  {
    id: "demo-officer",
    name: "Fatima Khan",
    email: "officer@demo.rasta.pk",
    password: "rasta-demo",
    role: "OFFICER",
    label: "Department Officer (Fatima Khan)",
    description: "Adjudicates claims, verifies identity, dispatches funds",
    avatarInitials: "FK",
    source: "demo",
  },
  {
    id: "demo-admin",
    name: "Mariam Shah",
    email: "admin@demo.rasta.pk",
    password: "rasta-demo",
    role: "ADMIN",
    label: "Administrator (Mariam Shah)",
    description: "Manages system policy, rules v3.2, service health",
    avatarInitials: "MS",
    source: "demo",
  },
  {
    id: "demo-auditor",
    name: "Omar Siddiqui",
    email: "auditor@demo.rasta.pk",
    password: "rasta-demo",
    role: "AUDITOR",
    label: "Auditor (Omar Siddiqui)",
    description: "Read-only oversight of decision traces & immutable ledger",
    avatarInitials: "OS",
    source: "demo",
  },
];

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init.headers ?? {}),
      },
    });
  } catch (err) {
    throw new ApiError(0, `RASTA API endpoint (${path}) unreachable.`);
  }

  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(
      response.status,
      body.detail ?? body.message ?? "The request could not be completed."
    );
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
    const result = await request<{ access_token: string; user: Omit<AuthUser, "source"> }>(
      "/api/v1/auth/login",
      {
        method: "POST",
        body: JSON.stringify({ email: email.trim(), password }),
      }
    );
    return {
      accessToken: result.access_token,
      user: {
        ...result.user,
        avatarInitials: result.user.name.split(" ").map((x) => x[0]).join("").slice(0, 2).toUpperCase(),
        source: "api",
      },
    };
  } catch (error) {
    // Backend /api/v1/auth is under development. Conspicuously fall back to the synthetic demo adapter.
    if (error instanceof ApiError && (error.status === 0 || error.status === 404 || error.status === 405)) {
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
  const result = await request<Omit<AuthUser, "source">>("/api/v1/auth/me", {
    headers: { Authorization: `Bearer ${token}` },
  });
  return {
    ...result,
    avatarInitials: result.name.split(" ").map((x) => x[0]).join("").slice(0, 2).toUpperCase(),
    source: "api",
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
      const res = await request<{ service: string; status: string }>(path);
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

export interface NadraVerifyResponse {
  verified: boolean;
  name?: string;
  note: string;
}

export async function verifyNadra(cnic: string): Promise<NadraVerifyResponse> {
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
