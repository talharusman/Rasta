export interface ClaimDraftData {
  purpose: string;
  income: string;
  members: string;
  personName: string;
  cnic: string;
  dob: string;
  phone: string;
  address: string;
  householdDesc: string;
  paymentAccount: string;
  step: number;
}

const draftKey = (scope: string) => `rasta.claim.draft_v2:${scope}`;
const retryKey = (scope: string) => `rasta.claim.idempotency_v2:${scope}`;

export function computeDraftFingerprint(draft: ClaimDraftData): string {
  const { step, ...fields } = draft;
  return JSON.stringify(fields);
}

export function getOrGenerateIdempotencyKey(scope: string, fingerprint: string): string {
  const key = retryKey(scope);
  try {
    const stored = JSON.parse(localStorage.getItem(key) ?? "null");
    if (stored?.fingerprint === fingerprint && typeof stored.key === "string") return stored.key;
  } catch {
    // A damaged draft does not prevent a new submission.
  }
  const id = crypto.randomUUID();
  try {
    localStorage.setItem(key, JSON.stringify({ fingerprint, key: id }));
  } catch {}
  return id;
}

export function saveClaimDraft(scope: string, draft: ClaimDraftData): boolean {
  try {
    localStorage.setItem(draftKey(scope), JSON.stringify(draft));
    return true;
  } catch {
    return false;
  }
}

export function loadClaimDraft(scope: string): Partial<ClaimDraftData> | null {
  try {
    const data = JSON.parse(localStorage.getItem(draftKey(scope)) ?? "null");
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    const fields = Object.fromEntries(Object.entries(data).filter(([, value]) => typeof value === "string"));
    return { ...fields, step: [1, 2, 3].includes(data.step) ? data.step : 1 };
  } catch {
    return null;
  }
}

export function clearClaimDraft(scope: string): void {
  try {
    localStorage.removeItem(draftKey(scope));
    localStorage.removeItem(retryKey(scope));
  } catch {}
}
