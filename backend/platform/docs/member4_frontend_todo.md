# Member 4 — Frontend & UX Lead: Remaining Work
**Coder's Cup 2026 | RASTA Relief Platform**
> *Ref: UX Spec §02–§06, §07, §08, §09 · Execution Plan §6 · Acceptance Tests §08*

---

## What's Already Done ✅

| Item | Status |
|---|---|
| Auth: real Supabase JWT login + demo fallback | ✅ |
| Role switching across all 5 roles | ✅ |
| Citizen claim form (text entry, income, household) | ✅ |
| Officer review queue + approve/reject/request-evidence | ✅ |
| Consent grant + revoke UI | ✅ |
| Admin rule editor + publish | ✅ |
| Auditor global audit log | ✅ |
| Helper citizen switcher | ✅ |
| Notifications panel | ✅ |
| Low-bandwidth mode toggle | ✅ |
| Backend wiring: `store.tsx` fires to live API | ✅ |
| TypeScript build passes (0 errors) | ✅ |

---

## What's Missing — Prioritized ❌

---

## 🔴 P0 — Without These, Demo Fails

### 1. Document Upload + AI Field Preview (Citizen Workflow)

**Spec §02 Step 3–4**: *"Upload or photograph a mock ID → AI extracts fields → citizen sees editable preview with uncertain fields highlighted → confirms or corrects."*

**This is the most visible missing feature for judges.** The entire citizen journey depends on it.

**Where to add**: In the Citizen workspace, after the basic claim form.

**Component: `DocumentScanStep.tsx`**

```
┌─────────────────────────────────────────────────────┐
│  📄 Upload Supporting Document                       │
│                                                     │
│  [ Choose file / Take photo ]  ← file input         │
│                                                     │
│  ── After upload, AI analyzes ──                    │
│                                                     │
│  Extracted Fields:                                  │
│  Name:    [Muhammad Ali        ] ✅ 95% confidence  │
│  CNIC:    [42101-123456-1      ] ⚠️ 88% — please verify │
│  DOB:     [________________   ] ❌ Unreadable — enter manually │
│                                                     │
│  ⚠️ "I could read your name but the ID number is   │
│      unclear. Please verify before submitting."     │
│                                                     │
│  [ Use these details ]  [ Enter manually ]          │
└─────────────────────────────────────────────────────┘
```

**API call**: `POST /cases/{id}/documents` (multipart) → then poll or call M2's `/internal/ai/extract-document` result.

**Failure state to show**:
- Blurry image → show `quality_ok: false` → *"Image too blurry. Please retake in better lighting or enter fields manually. Your draft is saved."*
- This is a **specific judge acceptance test**: *"Blurry ID → AI reports unreadable field, suggests rescan; user can continue."*

**Implementation tip**: Use a `<input type="file" accept="image/*" capture="environment">` — this opens camera on mobile.

---

### 2. Scam SMS Checker Panel (Citizen Workspace)

**Spec §03 Scenario 03**: *"Citizen pastes SMS → system returns 'Likely scam / Uncertain / No indicators' + reasons + recommended safe action."*

**This is a standalone panel in the Citizen view** — not part of the claim flow.

**Component: `ScamCheckerPanel.tsx`**

```
┌─────────────────────────────────────────────────────┐
│  🔍 Check a Suspicious Message                      │
│                                                     │
│  Paste the SMS you received:                        │
│  ┌─────────────────────────────────────────────┐   │
│  │ Dear citizen, click here to claim Rs 25,000 │   │
│  │ from BENAZIR fund. OTP: 1234. Hurry!        │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  [ Check Message ]                                  │
│                                                     │
│  ── Result ──────────────────────────────────────  │
│  🔴 LIKELY SCAM (91% confidence)                   │
│                                                     │
│  Warning signs detected:                           │
│  • Requests OTP/PIN — RASTA never does this        │
│  • Creates artificial urgency ("Hurry!")           │
│  • Impersonates a government scheme                │
│                                                     │
│  ✅ Safe action: Do not share the OTP.             │
│     Contact your nearest relief office to verify.  │
└─────────────────────────────────────────────────────┘
```

**API call**: `POST /api/v1/scam-checks` with `{ text: "...", citizen_id: "..." }`

**Result labels** to display with color coding:
- `likely_scam` → 🔴 red banner
- `uncertain` → 🟡 yellow banner + *"We cannot guarantee this is safe. Do not share OTPs."*
- `no_scam_indicators` → 🟢 green banner + *"No suspicious patterns detected, but always stay cautious."*

**Judges check**: *"Message analysis explains concrete indicators; measured false-alarm results available."* — show the `signals[]` array as bullet points.

---

### 3. Citizen-Facing AI Outcome Wording

**Spec §07**: Replace internal strings with the spec-mandated citizen phrases.

**Current**: UI shows raw `AUTO_CLEAR`, `HUMAN`, `needs_proof` strings.
**Required**:

| Internal value | What citizen must see |
|---|---|
| `AUTO_CLEAR` / `Verified` | *"✅ Your details passed the automated checks. Your application is moving forward."* |
| `HUMAN` / `Needs review` | *"👤 We cannot verify this confidently. An officer will review it."* |
| `needs_proof` / `More information` | *"📄 We need a clearer document or additional information."* |
| `Submitted` | *"⏳ Your application has been received and is being processed."* |
| `Rejected` | *"❌ Your application could not be approved. See officer notes below."* |

**Where to fix**: Find every place in `App.tsx` / `store.tsx` that renders case `status` or `aiRoute` to the citizen and replace with the lookup above.

---

### 4. Duplicate Submission Guard (UI)

**Spec §08**: *"Retry or double-click does not create an extra case."*

**Fix**: Disable the submit button after first click + show loading state:

```tsx
const [submitting, setSubmitting] = useState(false);

const handleSubmit = async () => {
  if (submitting) return;  // guard
  setSubmitting(true);
  try {
    await createCase(payload);
  } finally {
    setSubmitting(false);
  }
};

<button disabled={submitting} onClick={handleSubmit}>
  {submitting ? "Submitting…" : "Submit Claim"}
</button>
```

Also: store the last submitted `idempotency_key` in `localStorage` and check it before submitting again.

---

## 🟡 P1 — Important for Judging Score

### 5. Resume Draft / "More Information" Resubmission Flow

**Spec §04 Scenario 06**: *"Opens a case marked 'More information needed' → supplies new photo or corrected info → sees checklist of what's missing → confirmation when resubmitted."*

**Where to add**: In the Citizen case detail view, when status is `More information`:

```
┌─────────────────────────────────────────────────────┐
│  Case REL-20479 — More Information Required         │
│                                                     │
│  Officer has requested:                             │
│  ☐ Updated electricity bill (clearer scan)          │
│  ☐ Proof of household size                          │
│                                                     │
│  [ Upload New Document ]   ← triggers scan flow    │
│  [ Submit Updated Information ]                     │
└─────────────────────────────────────────────────────┘
```

---

### 6. Offline / Save State Indicator

**Spec §04 Scenario 08**: *"User sees: Saved locally / Syncing / Submitted indicators with no ambiguous success message."*

**Add a persistent status bar** at the bottom of citizen forms:

```tsx
// 3 states:
"💾 Draft saved locally"      // before backend submission
"🔄 Syncing with server…"    // mid-request
"✅ Submitted successfully"   // confirmed
"⚠️ No connection — draft saved. Will retry when online."  // offline
```

Use `navigator.onLine` + `window.addEventListener('online', ...)` to detect connectivity.

---

### 7. Rule Version Shown Per Case (Officer + Auditor)

**Spec §06 Scenario 12**: *"Old decision retains previous rule version."*
**Spec §06 Scenario 13**: *"Auditor sees rule version applied to each decision."*

**In the officer case detail view**, add a small badge:
```
Policy applied: v3.1 — Max income Rs 45,000 | NADRA required | Confidence ≥ 80%
```

This comes from the `rule_version` field in the Decision record (M1 + M2 provide this).

**In the auditor log**, show `rule_version` and `model_version` as columns.

---

### 8. Admin: Mock Failure Injection Controls

**Spec §06 Scenario 14**: *"Admin selects a prepared mock NADRA timeout, duplicate record, or payment-account mismatch fixture."*

**Add a "Demo Controls" card in the Admin workspace**:

```
┌─────────────────────────────────────────────────────┐
│  🧪 Demo Failure Scenarios                          │
│                                                     │
│  NADRA Service:  [Normal ▼]                         │
│    Options: Normal | Simulate Timeout | Record Not  │
│    Found | Name Mismatch                            │
│                                                     │
│  Raast Service:  [Normal ▼]                         │
│    Options: Normal | Account Mismatch | Timeout     │
│                                                     │
│  [ Apply Settings ]                                 │
│                                                     │
│  ⚠️ Prototype only. Affects next case submission.  │
└─────────────────────────────────────────────────────┘
```

**API call**: `POST /api/mock/fixtures/set` (M3 provides this).

---

### 9. Per-Case Audit Drill-Down (Auditor)

**Spec §06 Scenario 13**: *"Opens a completed or escalated case and investigates its history."*

**Current**: Auditor sees one global log. Needs a **per-case view**.

**Add**: When auditor clicks a case ID in the audit log → show filtered events for only that case, in chronological order:
- Case created → by whom, when
- Document uploaded
- AI decision (confidence, route, rule version, model version)
- Officer action (approve/reject/ask proof) with notes
- Consent status at time of action

**API calls**: `GET /api/v1/cases/{id}/decision-trace` + `GET /api/v1/cases/{id}/history` (M1 provides).

---

### 10. Helper: Access Denied on Revoked Consent

**Spec §04 Scenario 07**: *"Previously open helper screen must not be able to refresh or modify revoked data — show an access-ended message."*

**Add**: If `GET /cases` returns `403 CONSENT_REVOKED` for the helper:

```tsx
<div className="access-denied-banner">
  🚫 Access to {helperActiveCitizen}'s records has been withdrawn.
  Citizen has revoked your permission to view or manage their data.
</div>
```

---

## 🟢 P2 — Bonus (Only if Time Allows)

### 11. Urdu Voice Input
**Spec §03 Scenario 02**: *"Urdu voice input/output if feasible."*

```tsx
// Web Speech API — 2 lines to hook up:
const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
recognition.lang = 'ur-PK';
recognition.onresult = (e) => setFieldValue(e.results[0][0].transcript);
```

Add a 🎤 mic button next to text fields. Show recognized text before confirming.

---

### 12. Admin Digital Twin Rule Preview
**Execution Plan §8 P2**: Before publishing a rule, show which existing cases would be re-routed under the new thresholds.

**API**: `POST /api/v1/rules/evaluate` (M1 provides) → show a summary: *"Under this new rule, 3 of 12 pending cases would change from 'Human review' to 'Needs proof'."*

---

## Complete Citizen Journey — Step-by-Step (What Must Be Demoable)

```
1. Login as citizen@rasta.com
2. Click "New Claim" → fill form (name, CNIC, income, household)
3. Upload mock ID image → see AI-extracted fields with confidence
4. Correct any flagged fields → confirm
5. Click "Submit" (button disables immediately — no double submit)
6. See: "⏳ Your application has been received…"
7. AI processes → status changes to one of:
   ✅ "Your details passed automated checks…"
   📄 "We need a clearer document…"
   👤 "An officer will review it…"
8. If "More information" → see evidence checklist → upload new doc
9. Check suspicious SMS → paste → see scam analysis result
10. Open "My Data Sharing" → see helper consent → revoke it
11. See updated: "No active consents"
```

---

## Judging Criteria Mapping

| Judging criterion | Your UI |
|---|---|
| *"Platform works across multiple roles, not just chatbot"* | 5 role workspaces ✅ |
| *"Citizen scans document, corrects extracted fields"* | Document upload + field preview ❌ |
| *"Blurry ID → suggest rescan"* | Failure state in scan component ❌ |
| *"Scam message → concrete indicators"* | Scam checker panel ❌ |
| *"3 AI outcomes in citizen language"* | Spec-wording mapping ❌ |
| *"Duplicate submission blocked"* | Submit button guard ❌ |
| *"Consent revoked → helper sees access-ended"* | Access denied banner ❌ |
| *"Draft survives offline; resumable"* | Save state indicator ❌ |
| *"Admin controls mock failure scenarios"* | Fixture panel ❌ |
| *"Auditor reconstructs full decision trace"* | Per-case drill-down ❌ |
| *"Practical accessibility/low-bandwidth"* | Low-bandwidth mode ✅ |
| *"At least three optional platform features"* | Officer queue ✅ Rule editor ✅ Notifications ✅ Low-bandwidth ✅ |

---

## Definition of Done (Execution Plan §10)

> Functional user journeys for all roles, weak-network recovery, README/demo materials.

- [ ] Citizen can upload a document and see AI-extracted fields (or blurry error)
- [ ] Scam checker panel works end-to-end with real API call
- [ ] AI outcome shown in citizen-friendly spec wording (not raw `AUTO_CLEAR`)
- [ ] Submit button disabled after first click (no double submission)
- [ ] "More information" case shows evidence checklist + upload option
- [ ] Offline save state indicator (Saved / Syncing / Submitted)
- [ ] Admin has mock failure injection panel
- [ ] Auditor can drill into per-case history
- [ ] Helper sees access-denied when consent revoked
- [ ] Rule version shown in officer case detail + auditor log
- [ ] README updated with live URL + role credentials
