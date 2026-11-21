# For Member 2 (AI service: scam check, documents, identity name match, duplicates, routing)

From Member 3. The case-processing agent calls your six routes over HTTP. Only
`/internal/ai/evaluate` was fixed by the team contract. For the other five I had to pick
field names, so **please confirm or tell me what to change** (the whole client is one file:
`backend/app/agent/ai_client.py`, with working local stubs you can copy shapes from).

I never do fuzzy name matching, scam detection or duplicate detection myself. You do.

---

## Rules for every route

- Path `POST /internal/ai/<name>`, header `X-Service-Key` = `INTERNAL_SERVICE_KEY`
  (reject with 403 otherwise). JSON in, JSON object out.
- I wait **10 seconds**, then retry once on timeout or 5xx. Answer faster than that.
- If you cannot answer, return a **5xx**. Never return a made-up "all clear". I treat any
  failure as `unavailable` and send the case to a human officer.
- A reply that is not a JSON object, or is missing the key I need (listed below), is treated
  as malformed and also goes to a human officer.
- Keep `auditor_trace` JSON-serialisable (it is stored in the case decision).
- Use only synthetic data. This is a prototype.

## The six routes

### POST /internal/ai/evaluate   (fixed by the contract)
```json
in:  {"case_id": "c1", "rule_version": "rules-v1",
      "input": {"identity_verified": true, "name_match_score": 0.93, "document_quality": 0.95,
                "duplicate_flag": false, "scam_flag": false, "monthly_income": 20000}}
out: {"case_id": "c1", "route": "cleared|needs_proof|human_review", "confidence": 0.95,
      "risk_score": 0.1, "flags": ["..."], "rule_version": "rules-v1",
      "model_version": "m2-v1", "user_explanation": "...", "auditor_trace": {}}
```
`name_match_score` and `document_quality` can be `null` when a step could not run (no
document, or no registry name). Treat `null` as "unknown", not as good. `route` must be
exactly one of the three values or I treat the reply as malformed.
Note: I force `human_review` myself for identity mismatch, duplicates, scam and
unavailable services, whatever you return. You still should flag them.

### POST /internal/ai/match-identity   (proposed)
```json
in:  {"case_id": "c1", "input_name": "Zainab Khatoon", "registry_name": "Zenab Bibi"}
out: {"name_match_score": 0.42}          // number 0..1 (required); optional "model_version"
```
This is where spelling variants (Muhammad / Mohammad, Zenab / Zainab) are handled.

### POST /internal/ai/extract-document   (proposed; called once per document)
```json
in:  {"case_id": "c1", "document": {"id": "d1", "type": "identity_document", "quality": 0.95}}
out: {"document_type": "identity_document", "quality": 0.91, "fields": {}}   // quality 0..1 required
```
I pass the document record as the case stores it. If you need the file bytes or a URL,
tell me the field name and I will forward it.

### POST /internal/ai/scam-check   (proposed; only when the case has a message)
```json
in:  {"case_id": "c1", "message": "Send a processing fee to receive relief"}
out: {"scam_flag": true, "score": 0.8, "reasons": ["asks for a fee"]}   // scam_flag boolean required
```

### POST /internal/ai/detect-duplicates   (proposed)
```json
in:  {"case_id": "c1", "citizen_id": "u1", "mock_identity_id": "MOCK-200003",
      "name": "Mohammad Ali", "dob": "1985-03-14", "account_id": "MOCK-ACCOUNT-004"}
out: {"duplicate_flag": false, "matches": []}    // duplicate_flag boolean required
```
You need read access to other cases to do this (ask Member 1 for a function). The demo
data has a near-duplicate pair: `MOCK-200003 "Mohammad Ali"` and `MOCK-200004 "Muhammad Ali"`,
same birth date. That is meant to be caught here, not by me.

### POST /internal/ai/explain   (proposed)
```json
in:  {"case_id": "c1", "route": "human_review", "flags": ["low_name_match"], "rule_version": "rules-v1"}
out: {"user_explanation": "..."}       // non-empty string required
```
Plain language a citizen can read, no jargon, never promises money (`cleared` only means
"passed automated checks, waiting for an officer"). If you do not answer I use a short template.

## Flag names I use myself

`identity_mismatch`, `identity_not_found`, `duplicate_claim`, `scam_suspected`,
`service_unavailable`, `eligibility_failed`. Reuse these when they mean the same thing so
the officer notes line up. Your own extra flags are fine; I pass them through.

## How to develop without me

Set `AI_STUB=true` and I use my stubs. To test your real service from my side:
`AI_STUB` unset (or `false`), `AI_BASE_URL=http://localhost:8000`, `INTERNAL_SERVICE_KEY` set.
Mount your router in `backend/main.py` (it already includes `ai_router`).

## Done when

- [ ] All six routes exist under `/internal/ai/`, protected by `X-Service-Key`
- [ ] Each returns the required key from the list above
- [ ] You told me any field name that differs from this file
- [ ] With `AI_STUB` off, a clean demo case (`MOCK-123456`, "Muhammad Ali") ends `cleared`
      and `MOCK-200001` with a different applicant name ends `human_review`
