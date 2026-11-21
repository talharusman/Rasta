# Member 2 integration

The claim worker uses Member 2's local rule-based service for name matching, evidence quality, duplicate checks, routing, and explanations. The live Scam Shield uses the same service through the platform API. Citizens still submit claims and supporting evidence through the existing screens.

## Environment

Set these values in the root `.env`. Local addresses below assume the browser, worker, AI routes, and mock providers run on the same machine. Keep the existing Supabase URL, publishable key, JWT settings, and database connection.

| Variable | Value for a local run |
|---|---|
| `AI_STUB` | `false` to use Member 2 for claim processing |
| `AI_BASE_URL` | `http://127.0.0.1:8000`, the base URL of the shared FastAPI app |
| `AI_DUPLICATES_STRICT` | `true`, so the service fails if the live claim lookup is unavailable |
| `INTERNAL_SERVICE_KEY` | Server-only key sent by the claim agent as `X-Service-Key` |
| `AI_API_KEY` | Separate server-only key sent by the platform Scam Shield as `X-API-Key` |
| `RUN_JOB_WORKER` | `true` on exactly one API process |
| `AGENT_MODE` | `deterministic` |
| `MOCK_BASE_URL` | `http://127.0.0.1:8000` |
| `NADRA_MOCK_KEY`, `RAAST_MOCK_KEY`, `SMS_MOCK_KEY` | Existing server-only mock provider keys |
| `UPLOAD_DIR` | Absolute path that both the platform and AI service can read |
| `VITE_API_URL` | `http://localhost:8000` |
| `CORS_ORIGINS` | `http://localhost:5173`, plus any deployed browser origin |

The platform, worker, and AI must use the same `DATABASE_URL` and upload storage. Before starting, check that the database is on Alembic revision `0002`, mock fixtures are seeded, and the backend requirements are installed. See [Setup and credentials](SETUP.md) for the existing startup commands. Tesseract and `pytesseract` are optional for extracting text from images. The quality check works without them.

## Manual workflows

Use synthetic identities, documents, phone numbers, and messages. For scenarios that should clear, use different seeded identities or close the preceding claims. An open claim for the same citizen is itself a duplicate signal.

| Workflow | What to check |
|---|---|
| Clean claim | Submit as or on behalf of an authorized citizen. Use Muhammad Ali (`MOCK-123456`, `MOCK-ACCOUNT-001`), income below the current policy limit, and sharp JPEG or PNG images for both required proofs. Check that the case reaches `cleared`, its trace shows `m2-v1` and the pinned rule, and no payment exists. |
| Missing or blurry evidence | Submit with one required file missing or blurry. Check that the case asks for that document type. Upload a sharp replacement and resubmit. Confirm that the earlier file remains in history and only the latest file of that type is used in the new automated check. |
| PDF evidence | Upload a PDF as the latest required proof. Confirm the case goes to an officer with a PDF explanation and the file can still be downloaded. Request an image from the officer view and resubmit with a JPEG or PNG. |
| Identity matching | Try a known spelling variant and a clearly different name on separate claims. Look for the name match score in the trace. A mismatch goes to an officer. Other checks still apply to the spelling variant. |
| Duplicate claim and retry | Retry the same submission and check that only one processing job exists. Submit another open claim for the same identity in the same tenant and check that it goes to an officer. A matching identity in a separate tenant does not create a duplicate claim signal. |
| Consent and service failures | Withdraw processing consent while work is queued or running. Confirm the worker cannot save an outdated clearance. Make the AI unavailable or point its URL to an endpoint that rejects the service key. The case should go to an officer without payment. |
| Scam Shield | As a citizen with processing consent, try “Send a processing fee to receive relief”, “Click here for details”, and “Your appointment is tomorrow at 10”. Check for likely scam, uncertain, and no common indicators, with the reason and advice. Withdraw consent or interrupt the AI service and confirm the browser shows an error. |
| Policy and audit history | Publish a new threshold after a case enters processing. The running case should keep its pinned version, while new submissions use the updated policy. Review the rules and reasons in the auditor view, then switch to Urdu and check the saved case explanation. |
| Officer approval and payment | Assign and approve a cleared claim. Repeat the approval request or try the mock payment timeout and reconciliation path. Confirm that at most one payout is created and a transaction reference is shown only after confirmation. Check in-app notices and optional SMS delivery. |
