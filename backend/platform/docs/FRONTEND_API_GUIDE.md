# Frontend API guide

Base URL: `http://localhost:8000/api/v1`. Live OpenAPI schemas are available at `/docs` and `/openapi.json`. All data must be synthetic. This is an untested implementation; verify contracts during integration.

## Authentication

`POST /auth/login` with `{"email":"citizen@example.test","password":"YOUR_DEMO_PASSWORD"}` returns `access_token`, `refresh_token`, `token_type`, `expires_in`, `expires_at`. It does not return the actor; next call `GET /auth/me` with `Authorization: Bearer ACCESS_TOKEN`. Actor response includes `id`, `tenant_id`, `name`, `role`, `is_active`, `citizen_id` and creation time.

`POST /auth/refresh` takes `{"refresh_token":"..."}` and returns rotated token fields. Replace both tokens. Roles come from the backend database; never let users choose them. No signup endpoint. Do not persist secrets in shared-device storage unnecessarily.

## Conventions

UUID resource IDs; UTC timestamps; strict inputs reject unknown fields. Lists return `{"items":[]}` and most large lists accept `limit` (1–100, default 20) and `offset` (default 0). There is no cursor or total-count field. Cases use `case_id`; most other resources use `id`. Mutations require the last observed `expected_revision`. `CaseDetail` contains claim data, status, priority, assigned officer, revision, required documents, private document metadata and the latest citizen explanation. It excludes the complete AI trace.

## Citizen/helper flow

1. `GET /citizens` returns own profile or helper citizens with active `case:read` permission.
2. The citizen grants each required scope through `POST /consents`:
   - Processing: `{"citizen_id":"UUID","purpose":"processing","scope":"identity:verify"}` and another with `ai:process`.
   - Helper: `{"citizen_id":"UUID","grantee_id":"HELPER_UUID","scope":"case:read"}`. Separately grant `case:write`, `document:upload`, `case:submit`, `scam:check` as needed.
3. `POST /cases`:

```json
{
  "citizen_id":"CITIZEN_UUID",
  "claim_type":"relief_payment",
  "idempotency_key":"stable-random-client-key",
  "data":{
    "name":"Synthetic Citizen",
    "mock_identity_id":"MOCK-123456",
    "monthly_income":35000,
    "household_size":4,
    "payment_account":"MOCK-ACCOUNT-001"
  }
}
```

Returns 201 and full case detail, including `case_id`, `revision` and `status: draft`. Reuse the same key and identical body after network failure. Changed body under the same key returns 409.

4. `PATCH /cases/{id}` takes `{"expected_revision":1,"data":{...complete claim data...}}`; only draft/needs-proof cases can be edited.
5. `POST /cases/{id}/documents` accepts multipart `file`, `type` (`identity_proof` or `income_proof`) and `expected_revision`. JPEG, PNG, PDF only, maximum 5 MiB. Response: `{"document":{...},"revision":2}`. Uploaded evidence is private.
6. `POST /cases/{id}/submit` takes `{"expected_revision":2}` and returns 202: `{"case_id":"UUID","status":"submitted","revision":3,"run_id":"UUID"}`.
7. Poll `GET /cases/{id}`. A worker supplied by Member 3 is required to advance processing. Poll every two seconds initially, back off to ten, and pause while the tab is hidden.

`GET /cases` accepts status/citizen filters plus limit/offset. `GET /cases/{id}/history` returns transitions. `GET /cases/{id}/documents/{document_id}` streams authorized evidence; never construct storage URLs.

Statuses: draft → submitted → processing → cleared/needs_proof/human_review → approved/rejected → closed. Needs-proof cases can receive uploads and resubmit. Cleared does not mean approved or paid.

## Consent

`GET /consents?citizen_id=UUID` returns authorized grants including revoked history. `POST /consents/{id}/withdraw` has no body, is citizen-only and returns the grant with `revoked_at`. Processing withdrawal blocks queued/running work. Helper access ends on the next protected API request.

`GET /consents/access-check?citizen_id=UUID&scope=case:read` returns `{"allowed":true,"reason_code":null}` or false with a reason. This is only a UI hint: each operation rechecks access. Staff use their actual case/role endpoints, not helper permission checks.

Clear citizen-specific views on family switching, logout, consent denial and refresh failure. Do not display another family's cached data during loading.

## Officer/admin workflow

- `GET /cases/review-queue`: officer/admin, limit/offset. Metadata only for assigned or unassigned review cases; priority then age order. No confidence sort is implemented.
- `POST /cases/{id}/assign`: `{"officer_id":"UUID","expected_revision":4,"reason":"Review allocation"}`. Admin may assign an active tenant officer; officers may self-assign an unassigned review case.
- `POST /cases/{id}/review`: `{"action":"ask_proof","notes":"Please add income evidence","required_documents":["income_proof"],"expected_revision":5}`. Other actions: `approve`, `reject`. Assigned officer or admin only. Admin must add `override_reason`. Every action requires notes. Approval requires a current decision passing platform policy; override cannot bypass missing identity, critical flags or evidence.
- `POST /cases/{id}/close`: `{"expected_revision":6,"notes":"Review completed"}`; approved/rejected only.
- `GET /cases/{id}/decision-trace`: assigned officer/admin/auditor; optional `decision_id`. Returns stored decision and full payload.

## Users and policy

Admin: `GET /users?limit=20&offset=0`; `PATCH /users/{id}/role` takes `{"role":"officer","reason":"Demo staffing"}`. No self role edit. Citizen-linked accounts cannot be promoted.

Officer/admin/auditor: `GET /rules` and `GET /rules/{version_id}/history`. Admin publishes with `PATCH /rules/{active_version_id}`:

```json
{
  "expected_version":1,
  "reason":"Synthetic demo threshold adjustment",
  "conditions_json":{
    "max_monthly_income":45000,
    "required_documents":["identity_proof","income_proof"],
    "clear_confidence_min":0.95,
    "proof_confidence_min":0.7,
    "critical_flags":["identity_mismatch","potential_duplicate","fraud_indicator","identity_service_unavailable"]
  }
}
```

Returns 201 with new immutable version row. On version conflict reload. `POST /rules/evaluate` takes `{"case_id":"UUID"}` for assigned officer/admin; returns a conservative preview, not a persisted AI decision.

## Scam, audit and metrics

`POST /scam-checks`: citizen/helper, matching permissions and processing consent; `{"citizen_id":"UUID","text":"Synthetic suspicious SMS"}`. Returns 201 record with payload containing text, label, confidence and indicators. Labels: likely_scam, uncertain, no_scam_indicators. `GET /scam-checks/{id}` retrieves it. Missing AI configuration/provider failures return 503; do not display a safe result.

Admin/auditor: `GET /audit-logs` with optional action/resource plus limit/offset; `GET /metrics/summary` returns `cases_by_status` and `total_cases`. Auditors have no mutation permissions.

## Errors and retries

```json
{"error":{"code":"CONSENT_REVOKED","message":"Access not permitted","retryable":false},"request_id":"UUID"}
```

Responses also have `X-Request-ID`.

| HTTP | Codes / frontend action |
|---|---|
| 401 | UNAUTHENTICATED: attempt session refresh once, then login |
| 403 | FORBIDDEN, CONSENT_REQUIRED, CONSENT_REVOKED: stop protected actions and clear stale views |
| 404 | NOT_FOUND: unavailable resource; do not infer another user's data exists |
| 409 | CASE_VERSION_CONFLICT, RULE_VERSION_CONFLICT: reload; IDEMPOTENCY_CONFLICT: do not blindly retry; INVALID_TRANSITION, MISSING_EVIDENCE, CONFLICT: show explanation |
| 413/415 | FILE_TOO_LARGE / UNSUPPORTED_MEDIA_TYPE: select a supported smaller file |
| 422 | VALIDATION_ERROR: review fields; current validation envelope contains a generic message |
| 429 | RATE_LIMITED: back off |
| 503 | SERVICE_UNAVAILABLE: show pending/unavailable, never successful verification |

PDF identity-mismatch/duplicate codes appear as decision flags rather than standalone HTTP failures in this implementation. Preserve idempotency keys across reconnects. Do not blindly replay officer reviews, role edits or consent changes after an ambiguous response; reload first. Frontend never calls `/internal`, `/mock`, or external AI endpoints.
