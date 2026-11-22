// Local persistence for citizen claim drafts, idempotency keys, and offline save states.

export interface ClaimDraftData {
  userId?: string;
  helperActiveCitizen?: string;
  purpose: string;
  income: string;
  members: string;
  personName: string;
  cnic: string;
  phone: string;
  address: string;
  householdDesc: string;
  paymentAccount: string;
  step: number;
}

const DRAFT_STORAGE_KEY = "rasta.claim.draft_v1";
const IDEMPOTENCY_STORAGE_KEY = "rasta.claim.idempotency_v1";

/**
 * Computes a stable, normalized fingerprint of the claim draft fields.
 * If any material field changes, the fingerprint changes.
 */
export function computeDraftFingerprint(draft: ClaimDraftData): string {
  const parts = [
    draft.userId || "",
    draft.helperActiveCitizen || "",
    draft.purpose.trim(),
    draft.income.trim(),
    draft.members.trim(),
    draft.personName.trim().toLowerCase(),
    draft.cnic.trim().toUpperCase(),
    draft.phone.trim(),
    draft.address.trim().toLowerCase(),
    draft.householdDesc.trim().toLowerCase(),
    draft.paymentAccount.trim().toUpperCase(),
  ];
  return parts.join("::");
}

/**
 * Retrieves the stored idempotency key for this draft fingerprint,
 * or generates and persists a new UUID if none exists or if the draft materially changed.
 */
export function getOrGenerateIdempotencyKey(fingerprint: string): string {
  try {
    const raw = localStorage.getItem(IDEMPOTENCY_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as { fingerprint: string; key: string };
      if (parsed.fingerprint === fingerprint && parsed.key) {
        return parsed.key;
      }
    }
  } catch {
    // Ignore parse errors and generate fresh key
  }

  const newKey = crypto.randomUUID();
  try {
    localStorage.setItem(
      IDEMPOTENCY_STORAGE_KEY,
      JSON.stringify({ fingerprint, key: newKey, timestamp: Date.now() })
    );
  } catch {
    // Local storage unavailable
  }
  return newKey;
}

/**
 * Clears the persisted idempotency key after a confirmed successful submission.
 */
export function clearIdempotencyKey(): void {
  try {
    localStorage.removeItem(IDEMPOTENCY_STORAGE_KEY);
  } catch {}
}

/**
 * Saves claim draft data to localStorage.
 */
export function saveClaimDraft(draft: ClaimDraftData): void {
  try {
    localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft));
  } catch {}
}

/**
 * Loads persisted claim draft data from localStorage, if any.
 */
export function loadClaimDraft(): ClaimDraftData | null {
  try {
    const raw = localStorage.getItem(DRAFT_STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as ClaimDraftData;
  } catch {
    return null;
  }
}

/**
 * Clears persisted claim draft upon successful submission.
 */
export function clearClaimDraft(): void {
  try {
    localStorage.removeItem(DRAFT_STORAGE_KEY);
  } catch {}
}
