# For Member 4 (Frontend)

From Member 3. What you need to build or know for my part to show up in the UI.
Everything here is simulated: **show a clear "PROTOTYPE, simulated" label** (identity,
payments and SMS are all fake).

---

## 1. Never put these in the browser

`INTERNAL_SERVICE_KEY`, `NADRA_MOCK_KEY`, `RAAST_MOCK_KEY`, `SMS_MOCK_KEY`.
Do **not** call any `/internal/*` or `/mock/*` URL from the frontend. The browser only
talks to Member 1's normal API (login token) and the `/api/v1/admin/*` routes below.
`VITE_API_URL` is the only backend setting the frontend needs.

## 2. What a case status means (use these exact words)

After a citizen submits, the case changes by itself within seconds, so **poll the case**
(for example every 2 to 3 seconds for up to a minute) and show progress.

| Status | Show the citizen | Important |
|---|---|---|
| `submitted` | "Received" | |
| `processing` | "Being checked automatically" | |
| `cleared` | "Passed automated checks. Waiting for an officer." | **Not approved. No money is promised.** |
| `needs_proof` | "We need more information" + the list of missing items | Missing items are in the decision (`missing_evidence`), e.g. `identity_document` |
| `human_review` | "An officer will review your case" | |
| `approved` | "Approved by an officer" | Only an officer can set this. Payment follows. |
| `rejected`, `closed` | as per your design | |

Never show `cleared` as "approved" or "paid". Payment only happens for `approved` cases.

## 3. Admin screens (admin login required)

These two routes are for your admin panel. **Until Member 1 gives me the real admin-role
check they only accept an internal key, so a browser login will get 403. Ask Member 1 to
finish the admin dependency before you wire them up.**

### Fixture switches (demo the failure cases)
`GET /api/v1/admin/mock-conditions` returns the current switches.
`PUT /api/v1/admin/mock-conditions` with only the keys you want to change, for example
`{"nadra_outage": true}`. Booleans unless noted. Unknown keys give a 422.

| Switch | What it does to the demo |
|---|---|
| `identity_mismatch` | registry returns a different name |
| `nadra_timeout` | identity lookup hangs (the case still finishes, in `human_review`, after about 13 s) |
| `nadra_outage` | identity service down, case goes to `human_review` |
| `duplicated_response` | registry returns the person twice, case goes to `human_review` |
| `malformed_response` | registry returns broken data, case goes to `human_review` |
| `raast_outage` | payment service down (payment is retried safely, never doubled) |
| `sms_failure` | SMS is undeliverable (one re-send, then marked failed) |
| `latency_ms` (integer 0 to 60000) | slows every mock call |

Suggested UI: one toggle per switch, a "reset all" button (ask Member 1 whether
`DELETE` should be exposed to admins), and a banner when any switch is on.
Every change is written to the audit log.

### Jobs
`GET /api/v1/admin/jobs?status=queued|running|done|failed&kind=...` returns the latest 100:
```json
{"jobs": [{"id": "...", "kind": "disburse_case", "status": "failed", "attempts": 1,
           "max_attempts": 4, "run_after": "...", "last_error": "...", "dedupe_key": "disburse-case-1",
           "payload": {"case_id": "case-1"}, "created_at": "...", "updated_at": "..."}]}
```
Kinds: `process_case`, `send_notification`, `check_delivery`, `disburse_case`, `reconcile_payment`.
Suggested UI: a table with a red badge for `failed` and the `last_error` visible. Phone
numbers come masked (`***0001`) and message text is hidden. Do not try to show them.

## 4. Showing agent results to officers

The agent's reasoning is stored with the case by Member 1: ask them to return it from the
case endpoints. For `human_review` there is an **officer notes packet** (plain text in the
status-change note): summary, why the agent stopped with exact values, evidence seen,
what was tried, suggested questions to ask the citizen. Show it in a readable block. The
decision also has `flags`, `confidence`, `risk_score`, `rule_version`, `model_version`
and an `auditor_trace` (JSON) for the auditor view.

## 5. Error handling

Every error from our API looks like:
```json
{"error": {"code": "CONSENT_REQUIRED", "message": "...", "retryable": false}, "request_id": "..."}
```
Codes: `CONSENT_REQUIRED, CONSENT_REVOKED, FORBIDDEN, MISSING_EVIDENCE, IDENTITY_MISMATCH,
DUPLICATE_CLAIM, SERVICE_UNAVAILABLE, VALIDATION_ERROR, RULE_VERSION_CONFLICT`.
Show `message` to the user, show `request_id` in small text (useful for support), and offer
a retry button only when `retryable` is true. If consent is revoked the case goes to an
officer; tell the citizen that.

## 6. Demo data for your screens and screenshots

All fictional. Use these `mock_identity_id` values when creating demo cases:

| ID | Person | What happens |
|---|---|---|
| `MOCK-123456` | Muhammad Ali | clean: with a document, ends `cleared` |
| `MOCK-200001` | Zenab Bibi | enter a different name (e.g. "Zainab Khatoon"): `human_review` (name mismatch) |
| `MOCK-200002` | Rashid Khan | no birth date on record: still verified, noted for the officer |
| `MOCK-200003` / `MOCK-200004` | Mohammad / Muhammad Ali | near-duplicate pair, same birth date (caught by Member 2's duplicate check) |
| `MOCK-200005` | Fatima Noor | blocked record: `human_review` |
| `MOCK-200006` | Ayesha Siddiqui | her account `MOCK-ACCOUNT-006` is held by "A. Siddiqi Traders": when an officer approves, **payment is blocked**, a failed job shows in the admin jobs table, and the case goes back to `human_review` with a "Payment blocked" note |
| `MOCK-TIMEOUT-01` | (test) | identity lookup hangs, about 13 s, then `human_review` |
| `MOCK-MALFORMED-01` | (test) | broken registry response, `human_review` |

No document attached gives `needs_proof`. A message like "send money as a processing fee"
attached to the case gives `human_review` (scam). Accounts look like `MOCK-ACCOUNT-001`.

## 7. Deployment (only if you agree)

I may add `frontend/vercel.json` only with your OK. Tell me if you want it (SPA rewrite so
page refresh works). Also give Member 1 your final Vercel domain so it goes into the
backend's `CORS_ORIGINS`.

## Done when

- [ ] No key or `/internal` or `/mock` URL anywhere in the frontend code
- [ ] Case page polls and shows the status table above (cleared is never "approved")
- [ ] `needs_proof` shows the missing items; `human_review` shows the officer notes
- [ ] Admin page for switches and for jobs (after Member 1's admin check works)
- [ ] Standard error shape handled, with `request_id` shown
- [ ] "PROTOTYPE, simulated" label visible
