# Member 2 — AI & Decision Engineer: Remaining Work
**Coder's Cup 2026 | RASTA Relief Platform**
> *Ref: UX Spec §03, §07, §09 · Execution Plan §4 · Acceptance Tests §08*

---

## What's Already Done ✅

| Item | Status |
|---|---|
| `GET /api/ai/health` — health check | ✅ |
| `POST /api/ai/decide` — stub route exists | ✅ (stub only) |
| `backend/ai/routes.py` + `services.py` file structure | ✅ |

---

## What's Missing — The Entire AI System ❌

> [!CAUTION]
> The AI module is **100% stubbed**. `POST /api/ai/decide` always returns `route=HUMAN, confidence=0.0`. This is the **single biggest risk** for the demo. Judges will specifically observe: *"When confidence is low, AI says it is unsure and sends evidence and notes to a human."* — that only works if AI produces real, varying confidence scores.

---

## All AI Endpoints to Build

These are **internal** endpoints — called by M1 platform/agent, not directly by browser.

### 1. `POST /internal/ai/scam-check` — Scam SMS Classification
**Spec §03 Scenario 03**: *Citizen pastes suspicious SMS → system returns "Likely scam / Uncertain / No indicators" + reasons + recommended action.*

**Input**:
```json
{ "text": "Dear citizen, click here to claim Rs 25,000 from BENAZIR fund. OTP: 1234. Limited time!" }
```

**Output**:
```json
{
  "label": "likely_scam",
  "confidence": 0.91,
  "signals": ["OTP request", "urgency pressure", "suspicious link pattern", "impersonates government scheme"],
  "explanation": "This message requests a one-time PIN and creates urgency. RASTA never asks for OTPs via SMS.",
  "recommended_action": "Do not share the OTP. Contact your nearest relief office to verify."
}
```

**How to implement**:
- Use a **keyword/pattern classifier** with weighted signals (OTP, PIN, fee, click, limited time, unofficial link)
- OR use an LLM prompt: *"Classify this SMS as a potential scam. Return JSON with label, confidence, signals list, plain-language explanation."*
- Label set: `likely_scam` | `uncertain` | `no_scam_indicators`
- Include a **false-alarm rate note** in the response (e.g., `"false_alarm_rate": "~8% on synthetic test set"`)

**Judges check**: *"Message analysis explains concrete indicators; measured false-alarm results are available."*

---

### 2. `POST /internal/ai/extract-document` — OCR + Document Analysis
**Spec §03 Scenario 01**: *Upload synthetic ID/income proof → AI extracts fields → user sees editable preview with uncertain fields highlighted.*

**Input**: `multipart/form-data` with image file + `document_type` (id_card | income_proof | utility_bill)

**Output**:
```json
{
  "document_type": "id_card",
  "quality_ok": true,
  "quality_note": null,
  "extracted_fields": {
    "name": { "value": "Muhammad Ali", "confidence": 0.95 },
    "cnic": { "value": "42101-1234567-1", "confidence": 0.88 },
    "date_of_birth": { "value": null, "confidence": 0.0, "warning": "Field unreadable — please enter manually" }
  },
  "inconsistency_flags": [],
  "suggested_action": "Confirm the CNIC number before submitting."
}
```

**How to implement** (choose one):
- **Option A — Vision LLM** (fastest for hackathon): Send image to `gemini-1.5-flash` or GPT-4o with prompt: *"Extract fields from this Pakistani CNIC card. Return JSON: name, cnic, dob — with per-field confidence 0–1. If a field is unreadable, set confidence to 0 and add a warning."*
- **Option B — pytesseract**: `pip install pytesseract pillow` → OCR text → regex extract CNIC pattern `\d{5}-\d{7}-\d`

**Failure path** (blurry image): `quality_ok: false`, `quality_note: "Image too blurry. Please retake in better lighting or enter fields manually."` — **this is a specific judge test**.

---

### 3. `POST /internal/ai/match-identity` — Fuzzy Name Matching
**Spec §03 Scenario 04**: *"Name on form differs from mock identity record → system must NOT auto-assume match → show neutral prompt or send to officer."*

**Input**:
```json
{ "submitted_name": "M. Afzal", "mock_identity_id": "MOCK-421011234567" }
```

**Output**:
```json
{
  "match_score": 0.72,
  "verdict": "uncertain",
  "candidates": [
    { "name": "Muhammad Afzal", "score": 0.72, "mock_id": "MOCK-421011234567" }
  ],
  "action": "officer_review",
  "explanation": "Name abbreviation detected. Cannot confirm identity without additional verification."
}
```

**How to implement**:
```bash
pip install rapidfuzz
```
```python
from rapidfuzz import fuzz
score = fuzz.token_sort_ratio(submitted_name, identity_name) / 100.0
# score >= 0.95 → confirmed
# 0.70–0.95 → uncertain, prompt user to confirm
# < 0.70 → human_review, never auto-match
```

**Judges check**: *"Name variants and duplicates do not crash or cause arbitrary wrong identity matches."*

---

### 4. `POST /internal/ai/detect-duplicates` — Duplicate Claim Detection
**Spec §08**: *"Retry or double-click does not create an extra case or simulated transaction."*

**Input**:
```json
{ "mock_identity_id": "MOCK-421011234567", "claim_type": "relief_payment", "tenant_id": "..." }
```

**Output**:
```json
{
  "duplicate_found": true,
  "existing_case_id": "REL-20480",
  "existing_status": "under_review",
  "action": "block",
  "explanation": "An active claim for this identity already exists. Duplicate submissions are not permitted."
}
```

**How to implement** (simple DB query, no LLM needed):
```python
# In services.py:
existing = session.exec(
    select(Case).where(
        Case.mock_identity_id == identity_id,
        Case.status.not_in(["rejected", "closed"]),
        Case.tenant_id == tenant_id
    )
).first()
```

---

### 5. `POST /internal/ai/evaluate` — Unified Decision Routing
**Execution Plan §4**: *Combine all AI results + active rule version → produce route, confidence, risk score, citizen explanation, auditor trace.*

This is the **main endpoint called by M1's platform** when a case is submitted.

**Input**:
```json
{
  "case_id": "case_001",
  "rule_version": 2,
  "input": {
    "identity_verified": true,
    "name_match_score": 0.72,
    "document_quality": 0.90,
    "duplicate_flag": false,
    "scam_flag": false,
    "monthly_income": 35000,
    "household_size": 4
  }
}
```

**Routing logic** (from Execution Plan §4):

| Condition | Route |
|---|---|
| Confidence ≥ 0.95, no critical flags | `AUTO_CLEAR` |
| Confidence 0.70–0.95, only missing proof | `needs_proof` |
| Confidence < 0.70 | `human_review` |
| Duplicate flag, fraud signal, service unavailable | `human_review` (regardless of score) |

**Output**:
```json
{
  "case_id": "case_001",
  "route": "needs_proof",
  "confidence": 0.72,
  "risk_score": 0.28,
  "flags": ["name_match_uncertain"],
  "rule_version": 2,
  "model_version": "prototype-1",
  "user_explanation": "We need a clearer document or additional information to confirm your identity.",
  "auditor_trace": {
    "identity_verified": true,
    "name_match_score": 0.72,
    "income_threshold_check": "passed (35000 < 45000)",
    "rule_applied": "v2 — max_income=45000, confidence_threshold=0.80",
    "routing_reason": "name_match_score below confidence_threshold"
  }
}
```

**Critical**: The `rule_version` and `model_version` fields in the output are written by M1 to the `Decision` table. Without them, the **auditor trace acceptance test fails**.

---

### 6. `POST /internal/ai/explain` — Plain Language Explanation
**Spec §07**: Three citizen-facing outcomes with specific wording:

| Internal route | Citizen sees |
|---|---|
| `AUTO_CLEAR` | *"Your details passed the automated checks. Your application is moving forward."* |
| `needs_proof` | *"We need a clearer document or additional information."* |
| `human_review` | *"We cannot verify this confidently. An officer will review it."* |

**Add this to `services.py`** — a simple mapping function + optional LLM for custom reasons:
```python
CITIZEN_WORDING = {
    "AUTO_CLEAR": "Your details passed the automated checks. Your application is moving forward.",
    "needs_proof": "We need a clearer document or additional information.",
    "human_review": "We cannot verify this confidently. An officer will review it.",
}
```

---

### 7. `GET /internal/ai/metrics` — Evaluation Statistics
**Execution Plan §4**: *"Test labeled synthetic data; compute false alarms, missed scams, routing errors, latency."*

**What judges look for**: *"Measured false-alarm results are available."* — this means actual numbers, not just saying "it works".

**Minimum to show**:
```json
{
  "scam_detection": {
    "test_cases": 40,
    "correct": 36,
    "accuracy": 0.90,
    "false_alarm_rate": 0.08,
    "missed_scam_rate": 0.05
  },
  "routing": {
    "test_cases": 20,
    "correct_routes": 18,
    "accuracy": 0.90
  },
  "ocr": {
    "test_cases": 15,
    "field_accuracy": 0.87
  },
  "model_version": "prototype-1",
  "note": "Evaluated on synthetic labeled dataset. Not a production guarantee."
}
```

Build 40 synthetic scam/not-scam SMS examples, run classifier, report results honestly.

---

## Complete Workflow You Own

```
Case submitted by M1
       │
       ▼
POST /internal/ai/evaluate
       │
       ├──► extract-document  (if document uploaded)
       ├──► match-identity    (fuzzy name check vs NADRA mock)
       ├──► detect-duplicates (same CNIC + open case?)
       ├──► read active rule  (from DB via M1 service call)
       │
       ▼
Produce: route + confidence + risk + rule_version + model_version
       │
       ▼
Return to M1 → stored in Decision table → case status updated → audit written
```

---

## Implementation Priority Order

| Priority | Task | Time est. |
|---|---|---|
| 🔴 P0 | `/evaluate` endpoint with real routing logic (reads rule thresholds) | 2–3 hrs |
| 🔴 P0 | `/scam-check` with keyword/LLM classifier | 1–2 hrs |
| 🔴 P0 | `/match-identity` with RapidFuzz | 1 hr |
| 🟡 P1 | `/extract-document` with Vision LLM or pytesseract | 2–3 hrs |
| 🟡 P1 | `/detect-duplicates` (DB query, no LLM) | 30 min |
| 🟡 P1 | `/metrics` with synthetic test results | 1 hr |
| 🟢 P2 | `/explain` with Urdu translation | 1 hr |

---

## Judging Criteria Mapping

| Judging criterion | Your AI behavior |
|---|---|
| *"AI says it is unsure and hands to human"* | `/evaluate` → `human_review` when confidence < 0.70 |
| *"Blurry ID → suggest rescan"* | `/extract-document` → `quality_ok: false` |
| *"Scam message → concrete indicators"* | `/scam-check` → `signals[]` array |
| *"Name mismatch → officer with notes"* | `/match-identity` → `uncertain` → `officer_review` |
| *"Old decisions preserve rule version"* | Write `rule_version` to output → M1 stores in Decision |
| *"Three AI features minimum"* | scam classification ✓ OCR ✓ routing/fuzzy ✓ |
| *"Explainability"* | `/explain` → citizen wording + auditor trace |
| *"Measured evaluation results"* | `/metrics` with actual numbers |

---

## Definition of Done (Execution Plan §10)

> OCR, scam, names, duplicates, routing, reasons and measured synthetic evaluation.

- [ ] `/internal/ai/scam-check` returns label + signals + explanation
- [ ] `/internal/ai/extract-document` returns per-field confidence (or blurry flag)
- [ ] `/internal/ai/match-identity` uses RapidFuzz, never auto-matches below 0.95
- [ ] `/internal/ai/detect-duplicates` queries DB for existing active cases
- [ ] `/internal/ai/evaluate` reads active rule thresholds from DB, returns routing + trace
- [ ] `/api/ai/decide` updated to call `/internal/ai/evaluate` pipeline (not stub)
- [ ] `/internal/ai/metrics` returns measured synthetic evaluation stats
- [ ] 40+ synthetic scam test cases created and results honest
