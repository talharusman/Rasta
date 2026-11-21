# M3 CONTEXT (source of truth for Member 3 work)

## Ownership
- I may only edit: `backend/app/integrations/`, `backend/app/agent/`, `backend/app/jobs/`, `tests/test_m3_*.py`, deployment files (Dockerfile, .dockerignore, Procfile/railway config), and `frontend/vercel.json` only if Member 4 agrees.
- Never edit Member 1 (auth, cases, consent, rules, audit, main API), Member 2 (ai) or Member 4 (frontend) code. If I need something from them, write it in `backend/app/agent/platform_bridge.py` or `backend/app/agent/ai_client.py` as a stub with a clear TODO.

## Product
Public Relief Assistance Platform. PROTOTYPE ONLY. All identities, payments, SMS, policies are simulated. No real personal data.

## Case states (from team contract)
draft, submitted, processing, cleared, needs_proof, human_review, approved, rejected, closed.

"cleared" = automated checks passed, NO financial authority. Disbursement only for status "approved" (officer-approved).

## Standard error shape
```json
{"error": {"code": "...", "message": "...", "retryable": bool}, "request_id": "..."}
```
Codes: CONSENT_REQUIRED, CONSENT_REVOKED, FORBIDDEN, MISSING_EVIDENCE, IDENTITY_MISMATCH, DUPLICATE_CLAIM, SERVICE_UNAVAILABLE, VALIDATION_ERROR, RULE_VERSION_CONFLICT.

## Mock services (external simulators; each has its own API key in header X-Mock-Api-Key)
- NADRA (key NADRA_MOCK_KEY): POST /mock/nadra/verify, GET /mock/nadra/records/{id}
- Raast (key RAAST_MOCK_KEY): POST /mock/raast/account-validate, POST /mock/raast/disburse (requires Idempotency-Key header; idempotent), GET /mock/raast/transactions/{id}
- SMS (key SMS_MOCK_KEY): POST /mock/sms/send, GET /mock/sms/messages/{id}
- Fixture switches (developer/admin only, internal key): identity_mismatch, nadra_timeout, nadra_outage, duplicated_response, malformed_response, raast_outage, sms_failure, latency_ms.
- Synthetic IDs: mock_identity_id like MOCK-123456; accounts like MOCK-ACCOUNT-001.

## Adapters (the rest of the backend talks ONLY to these)
- IdentityProvider.verify(mock_identity_id, name, dob?) -> IdentityResult(status: verified|mismatch|not_found|duplicate|unavailable|malformed, record, issues[], latency_ms)
- IdentityProvider.get_record(mock_identity_id) -> IdentityResult
- PaymentProvider.validate_account(account_id, beneficiary_name) -> AccountResult(status: matched|mismatched|not_found|unavailable)
- PaymentProvider.disburse(case_id, amount, account_id) -> PaymentResult(status: success|pending|failed|unavailable|rejected_not_approved, transaction_id, idempotency_key)
- PaymentProvider.get_transaction(transaction_id) -> PaymentResult
- NotificationProvider.send(recipient, message, case_id) -> NotificationResult(status: sent|delivered|failed|unavailable, message_id)
- Adapters never raise to callers; they return a status.

## Internal routes I own (header X-Service-Key = INTERNAL_SERVICE_KEY)
POST /internal/agent/process-case {case_id}; GET /internal/agent/runs/{id}; POST /internal/jobs/notifications; GET /health; GET /ready.

## Agent sequence (team contract)
get_case_details -> check_consent -> verify_mock_identity -> analyze_document -> check_scam_message (if a message is attached) -> find_duplicate_claims -> evaluate_eligibility (active rules) -> evaluate routing (M2 /internal/ai/evaluate) -> record_decision -> request_more_evidence OR escalate_to_officer OR mark cleared -> send_notification.

Tools: get_case_details, check_consent, verify_mock_identity, analyze_document, check_scam_message, find_duplicate_claims, evaluate_eligibility, request_more_evidence, escalate_to_officer, record_decision, send_notification.

The agent has NO approve and NO disburse tool.

## M2 internal AI routes I call (HTTP, X-Service-Key)
POST /internal/ai/scam-check, /internal/ai/extract-document, /internal/ai/match-identity, /internal/ai/detect-duplicates, /internal/ai/evaluate, /internal/ai/explain.

- evaluate input: `{case_id, rule_version, input:{identity_verified, name_match_score, document_quality, duplicate_flag, scam_flag, monthly_income}}`
- evaluate output: `{case_id, route: cleared|needs_proof|human_review, confidence, risk_score, flags[], rule_version, model_version, user_explanation, auditor_trace}`

## M1 platform functions I call (via platform_bridge.py)
get_case(case_id), check_consent(citizen_id, grantee_id, scope), get_active_rules(), record_decision(case_id, decision), transition_case(case_id, to_status, actor, note), log_audit(actor_type, actor_id, action, resource, metadata), create_notification(case_id, recipient, message).

## Safety rules (never break)
1. A timeout, outage or malformed response is NEVER treated as verified. It becomes status unavailable/malformed -> route human_review with flag service_unavailable.
2. Critical flags (identity mismatch, duplicate, scam, service unavailable) force human_review regardless of confidence.
3. Never send a payment twice: idempotency key = "disburse-" + case_id, persisted with the original transaction id. On disburse timeout, look up the transaction by idempotency key before trying again.
4. Safe reads may retry (max 3, backoff 0.5s, 1s, 2s). Disburse is never blindly retried.
5. Log every provider call, agent step, retry and failure; record failed jobs, never lose them silently.
6. Every agent step is audited with actor_type="agent".
7. Never expose mock or internal keys to the browser.

## Environment variables
DATABASE_URL, INTERNAL_SERVICE_KEY, NADRA_MOCK_KEY, RAAST_MOCK_KEY, SMS_MOCK_KEY, MOCK_BASE_URL, AI_BASE_URL, CORS_ORIGINS, RUN_JOB_WORKER, LLM_API_KEY (optional), AGENT_MODE=deterministic|llm, SENTRY_DSN (optional).
